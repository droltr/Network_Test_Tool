import subprocess
import platform
import re
import logging
import socket

from utils.paths import command_env, console_encoding

class TraceRoute:
    def __init__(self):
        self.platform = platform.system().lower()
        self.is_running = False
        self.process = None

    def stop(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
            except:
                pass

    def run_trace(self, target, callback, max_hops=30):
        """
        Run traceroute and call callback with structured data for each hop.
        callback(data): data is a dict with keys: hop, ip, time, ms, status, destination
        (time is a display string such as "1.2 ms" or "*", ms is a float or None).
        """
        self.is_running = True

        try:
            target_ip = socket.gethostbyname(target)
        except OSError:
            target_ip = target

        if self.platform == "windows":
            command = ["tracert", "-d", "-h", str(max_hops), "-w", "1000", target]
        else:
            # One probe per hop keeps the trace fast; the GUI shows one latency per hop
            command = ["traceroute", "-n", "-q", "1", "-w", "1", "-m", str(max_hops), target]

        try:
            # On Windows, we need to prevent the console window from appearing
            startupinfo = None
            if self.platform == "windows":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                encoding=console_encoding(),
                errors="replace",
                startupinfo=startupinfo,
                env=command_env()
            )

            for line in iter(self.process.stdout.readline, ''):
                if not self.is_running:
                    break

                line = line.strip()
                if not line:
                    continue

                parsed = self._parse_line(line)
                if parsed:
                    parsed['destination'] = parsed.get('ip') == target_ip
                    callback(parsed)

            self.process.stdout.close()
            self.process.wait()

        except FileNotFoundError:
            logging.error("Trace route failed: command not found")
            callback({"error": "Traceroute command not found."})
        except Exception as e:
            logging.error(f"Trace route failed: {e}")
            callback({"error": str(e)})
        finally:
            self.is_running = False

    def _parse_line(self, line):
        """Parse a line of traceroute output."""
        if self.platform == "windows":
            # Example: "  1    <1 ms    <1 ms    <1 ms  192.168.1.1"
            # Example: "  2     *        *        *     Request timed out."

            # Skip header lines
            if line.startswith("Tracing") or line.startswith("over"):
                return None

            try:
                parts = line.split()
                if not parts or not parts[0].isdigit():
                    return None

                hop = int(parts[0])

                # Check for timeout
                if "Request timed out" in line:
                    return {
                        "hop": hop,
                        "time": "*",
                        "ms": None,
                        "ip": "Request timed out",
                        "status": "timeout"
                    }

                # Logic to find IP: it's usually the last element
                ip = parts[-1]

                # Extract times: look for 'ms' or '<1'
                # Simple average calculation
                total_time = 0
                count = 0

                for part in parts[1:-1]:
                    if part == "ms": continue
                    if part == "<1":
                        total_time += 0.5
                        count += 1
                    elif part.isdigit():
                        total_time += int(part)
                        count += 1

                avg = total_time / count if count > 0 else None
                return {
                    "hop": hop,
                    "time": f"{avg:.1f} ms" if avg is not None else "*",
                    "ms": avg,
                    "ip": ip,
                    "status": "ok"
                }
            except Exception as e:
                logging.debug(f"Failed to parse line '{line}': {e}")
                return None
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
