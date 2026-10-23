import ipaddress
import subprocess
import platform
import re
import logging
import socket
import threading

from utils.paths import NO_WINDOW, command_env, decode_output


def _is_ip(token):
    try:
        ipaddress.ip_address(token.strip('[]'))
        return True
    except ValueError:
        return False


class TraceRoute:
    """Runs tracert / traceroute. One instance may run several traces one after another.

    stop() cancels the running trace. A stop() that arrives while no trace runs cancels the next
    run_trace() call instead (a worker thread that is stopped before it got to start the trace);
    the cancellation is used up by that call, so later traces run normally.
    """

    def __init__(self):
        self.platform = platform.system().lower()
        self.is_running = False
        self.process = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()   # cancellation of the current (or next) run

    def stop(self):
        with self._lock:
            self.is_running = False
            self._cancel.set()
            process = self.process
        if process:
            try:
                process.terminate()
            except OSError:
                pass

    def _start_process(self, command, cancel):
        """Popen the trace command unless the run was cancelled; None when cancelled. Checked under the
        lock that stop() takes, so a stop() either sees the new process or prevents it from starting."""
        with self._lock:
            if cancel.is_set():
                return None
            # Binary pipe decoded per line: decode_output picks UTF-8 or the OEM code page.
            # CREATE_NO_WINDOW keeps tracert from opening a console in the windowed build.
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=NO_WINDOW,
                env=command_env()
            )
            return self.process

    def run_trace(self, target, callback, max_hops=30, line_callback=None):
        """
        Run traceroute and call callback with structured data for each hop.
        callback(data): data is a dict with keys: hop, ip, time, ms, status, destination
        (time is a display string such as "1.2 ms" or "*", ms is a float or None).
        line_callback, if given, receives every raw output line.
        """
        with self._lock:
            cancel = self._cancel
            if cancel.is_set():
                # A stop() that arrived before this call (e.g. from another thread) cancels this run only
                self._cancel = threading.Event()
                return
            self.is_running = True

        try:
            target_ip = socket.gethostbyname(target)
        except (OSError, UnicodeError, ValueError):
            target_ip = target

        if self.platform == "windows":
            command = ["tracert", "-d", "-h", str(max_hops), "-w", "1000", target]
        else:
            # One probe per hop keeps the trace fast; the GUI shows one latency per hop
            command = ["traceroute", "-n", "-q", "1", "-w", "1", "-m", str(max_hops), target]

        try:
            process = self._start_process(command, cancel)
            if process is None:
                return

            for raw in iter(process.stdout.readline, b''):
                if cancel.is_set():
                    break

                line = decode_output(raw).strip()
                if not line:
                    continue
                if line_callback:
                    line_callback(line)

                parsed = self._parse_line(line)
                if parsed:
                    parsed['destination'] = parsed.get('ip') == target_ip
                    callback(parsed)

            process.stdout.close()
            if cancel.is_set() and process.poll() is None:
                process.terminate()
            process.wait(timeout=5)

        except FileNotFoundError:
            logging.error("Trace route failed: command not found")
            callback({"error": "Traceroute command not found."})
        except Exception as e:
            logging.error(f"Trace route failed: {e}")
            callback({"error": str(e)})
        finally:
            with self._lock:
                self.is_running = False
                if self._cancel is cancel and cancel.is_set():
                    self._cancel = threading.Event()   # this run's stop() must not cancel the next run

    def _parse_line(self, line):
        """Parse a line of traceroute output."""
        if self.platform == "windows":
            # Example: "  1    <1 ms    <1 ms    <1 ms  192.168.1.1"
            # Example: "  2     *        *        *     Request timed out."
            # Example: "  1     *     10.90.0.3  reports: Destination host unreachable."
            # Parsed by structure: the header, footer and messages are translated
            # (Turkish "İstek zaman aşımına uğradı."), the numbers, '*' and addresses are not.
            parts = line.split()
            if not parts or not parts[0].isdigit():
                return None
            hop = int(parts[0])

            # Up to three probe columns: "*", "<1 ms", "12 ms" (the unit word may be localized)
            times, i = [], 1
            while i < len(parts) and len(times) < 3:
                token = parts[i]
                match = re.fullmatch(r'(<?)(\d+)(\D*)', token)
                if token == '*':
                    times.append(None)
                elif match and not _is_ip(token):
                    times.append(0.5 if match.group(1) else float(match.group(2)))
                    if not match.group(3) and i + 1 < len(parts) and parts[i + 1].isalpha():
                        i += 1  # separate unit ("ms")
                else:
                    break
                i += 1

            ip = next((p.strip('[]') for p in parts[i:] if _is_ip(p)), None)
            replies = [t for t in times if t is not None]
            if not replies:
                return {
                    "hop": hop,
                    "time": "*",
                    "ms": None,
                    # An address here is a router reporting the destination as unreachable
                    "ip": f"Unreachable (reported by {ip})" if ip else "Request timed out",
                    "status": "timeout"
                }

            avg = sum(replies) / len(replies)
            return {
                "hop": hop,
                "time": f"{avg:.1f} ms",
                "ms": avg,
                "ip": ip or "*",
                "status": "ok"
            }
        else:
            # Linux/macOS with -n -q 1:
            #   " 1  192.168.1.1  1.123 ms"
            #   " 3  *"
            #   " 7  8.8.8.8  13.8 ms !H"
            parts = line.split()
            if not parts or not parts[0].isdigit():
                return None  # header ("traceroute to ...") or continuation lines

            hop = int(parts[0])
            if len(parts) < 2 or parts[1] == "*":
                return {"hop": hop, "time": "*", "ms": None, "ip": "*", "status": "timeout"}

            ip = parts[1]
            match = re.search(r'([\d.]+)\s*ms', line)
            ms = float(match.group(1)) if match else None
            return {
                "hop": hop,
                "time": f"{ms:.1f} ms" if ms is not None else "*",
                "ms": ms,
                "ip": ip,
                "status": "ok" if ms is not None else "timeout"
            }
