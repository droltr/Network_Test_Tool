import subprocess
import platform
import re
import logging
import threading
import time

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

    def run_trace(self, target, callback):
        """
        Run traceroute and call callback with structured data for each hop.
        callback(data): data is a dict with keys: hop, ip, time, status
        """
        self.is_running = True
        
        if self.platform == "windows":
            command = ["tracert", "-d", "-w", "1000", target]
        else:
            command = ["traceroute", "-n", "-w", "1", target]

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
                startupinfo=startupinfo
            )

            for line in iter(self.process.stdout.readline, ''):
                if not self.is_running:
                    break
                
                line = line.strip()
                if not line:
                    continue

                parsed = self._parse_line(line)
                if parsed:
                    callback(parsed)

            self.process.stdout.close()
            self.process.wait()

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
                        "ip": "Request timed out",
                        "status": "timeout"
                    }

                # Extract times (usually 3 columns)
                times = []
                ip_index = -1
                
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
                
                avg_time = f"{total_time / count:.1f} ms" if count > 0 else "*"

                return {
                    "hop": hop,
                    "time": avg_time,
                    "ip": ip,
                    "status": "ok"
                }
            except Exception as e:
                logging.debug(f"Failed to parse line '{line}': {e}")
                return None
        else:
            # Linux/Mac parsing (simplified)
            # Example: " 1  192.168.1.1  1.123 ms  1.000 ms  0.900 ms"
            try:
                parts = line.split()
                if not parts or not parts[0].isdigit():
                    return None
                
                hop = int(parts[0])
                ip = parts[1]
                
                # Extract time (just take the first one for simplicity)
                time_val = parts[2] if len(parts) > 2 else "*"
                
                return {
                    "hop": hop,
                    "time": f"{time_val} ms",
                    "ip": ip,
                    "status": "ok"
                }
            except:
                return None
