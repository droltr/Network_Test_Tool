import platform
import subprocess
import socket
from datetime import datetime
from .detector import NetworkDetector
from .ping import PingTester
from .speed_test import SpeedTester

from utils.paths import command_env

class Troubleshooter:
    def __init__(self):
        self.detector = NetworkDetector()
        self.ping_tester = PingTester()
        self.speed_tester = SpeedTester()

    # Step ids reported through event_callback, in execution order
    STEPS = ('info', 'gateway', 'dns', 'external', 'trace')

    def run_troubleshooting(self, progress_callback=None, event_callback=None):
        """Run all checks. progress_callback gets each log line; event_callback(step, status, value)
        gets structured step updates (status: running, done, failed, partial, skipped)."""
        log = []
        def log_and_callback(message):
            log.append(message)
            if progress_callback:
                progress_callback(message)

        def event(step, status, value=""):
            if event_callback:
                event_callback(step, status, value)

        def ping_step(step, host):
            event(step, 'running', host)
            ping_result = self.ping_tester.ping_host(host, count=3)
            if ping_result and not ping_result.get('error') and 'avg_time' in ping_result.get('statistics', {}):
                avg = ping_result['statistics']['avg_time']
                event(step, 'done', f"{avg:.2f} ms")
                return avg
            event(step, 'failed', "failed")
            return None

        log_and_callback(f"--- Automated Network Troubleshooting --- ({datetime.now().isoformat()})\n")

        # 1. Device and Network Info
        log_and_callback("1. Gathering Device and Network Information...")
        event('info', 'running')
        info = self.detector.get_network_info()
        log_and_callback(f"    Hostname: {info.get('hostname', 'N/A')}")
        log_and_callback(f"    Operating System: {platform.system()} {platform.release()}")
        log_and_callback(f"    Processor: {platform.processor()}")
        log_and_callback(f"    Python Version: {platform.python_version()}\n")

        log_and_callback("    Network Interfaces:")
        for iface in info.get('interfaces', []):
            ipv4 = iface.get('ipv4', 'N/A')
            # Only show active interfaces (not 127.x.x.x or 169.x.x.x)
            if ipv4 != 'N/A' and not ipv4.startswith('127.') and not ipv4.startswith('169.'):
                log_and_callback(f"        Name: {iface.get('name', 'N/A')}")
                log_and_callback(f"        Status: {iface.get('status', 'N/A')}")
                log_and_callback(f"        IPv4: {ipv4}")
                log_and_callback(f"        MAC: {iface.get('mac', 'N/A')}\n")

        log_and_callback(f"    Default Gateway: {info.get('gateway', ['N/A'])[0]}")
        log_and_callback(f"    DNS Servers: {', '.join(info.get('dns', ['N/A']))}\n")
        event('info', 'done', "done")

        # 2. Connectivity Tests

        log_and_callback("2. Performing Connectivity Tests...")
        # Ping Gateway
        gateway = info.get('gateway', [None])[0]
        if gateway == 'N/A':
            gateway = None
        if gateway:
            log_and_callback(f"    Pinging gateway ({gateway})...")
            avg = ping_step('gateway', gateway)
            if avg is not None:
                log_and_callback(f"        Success ({avg:.2f}ms avg)")
            else:
                log_and_callback("        Failed to ping gateway.")
                log_and_callback("        [SUGGESTION] Check physical connection to router/switch.")
                log_and_callback("        [SUGGESTION] Ensure router is powered on.")
        else:
            event('gateway', 'failed', "not found")
            log_and_callback("    Gateway not found, skipping ping test.")
            log_and_callback("    [SUGGESTION] Check DHCP settings or configure static IP.")

        # Ping DNS
        dns_server = info.get('dns', [None])[0]
        if dns_server == 'N/A':
            dns_server = None
        if dns_server:
            log_and_callback(f"    Pinging primary DNS server ({dns_server})...")
            avg = ping_step('dns', dns_server)
            if avg is not None:
                log_and_callback(f"        Success ({avg:.2f}ms avg)")
            else:
                log_and_callback("        Failed to ping DNS server.")
                log_and_callback("        [SUGGESTION] Try changing DNS to Google (8.8.8.8) or Cloudflare (1.1.1.1).")
        else:
            event('dns', 'failed', "not found")
            log_and_callback("    DNS server not found, skipping ping test.")
            log_and_callback("    [SUGGESTION] Configure DNS servers manually.")

        # Ping External Host
        log_and_callback("    Pinging external host (8.8.8.8)...")
        avg = ping_step('external', "8.8.8.8")
        if avg is not None:
            log_and_callback(f"        Success ({avg:.2f}ms avg)\n")
        else:
            log_and_callback("        Failed to ping external host.\n")
            log_and_callback("        [SUGGESTION] Check internet subscription or ISP status.")
            log_and_callback("        [SUGGESTION] Verify firewall settings are not blocking traffic.\n")

        # 3. Traceroute
        log_and_callback("3. Performing Traceroute to 1.1.1.1...")
        event('trace', 'running', "1.1.1.1")
        trace_log = self.run_traceroute("1.1.1.1", progress_callback)
        log.extend(trace_log)
        event('trace', *self._summarize_trace(trace_log, "1.1.1.1"))

        log_and_callback("\n--- Troubleshooting Complete ---")
        return "\n".join(log)

    @staticmethod
    def _summarize_trace(lines, target):
        """(status, value) for the traceroute step from its raw output lines."""
        if any("not found" in line or "error occurred" in line for line in lines):
            return 'failed', "not available"
        last_reply = 0
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit() and parts[1] != '*' and 'Request' not in line:
                last_reply = int(parts[0])
                if target in parts[1:]:
                    return 'done', f"{last_reply} hops"
        if last_reply == 0:
            return 'failed', "no reply"
        return 'partial', f"stopped at hop {last_reply}"

    def run_traceroute(self, host, progress_callback=None):
        log = []
        def log_and_callback(message):
            log.append(message)
            if progress_callback:
                progress_callback(message)

        try:
            if platform.system().lower() == "windows":
                command = ["tracert", "-d", "-h", "15", "-w", "1000", host]
            else:
                command = ["traceroute", "-n", "-m", "15", "-q", "1", host]
            
            env = command_env()
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       universal_newlines=True, env=env)

            for line in iter(process.stdout.readline, ''):
                log_and_callback(line.strip())
            
            process.stdout.close()
            return_code = process.wait()
            if return_code != 0:
                log_and_callback(f"Traceroute finished with error code {return_code}")

        except FileNotFoundError:
            log_and_callback("Traceroute command not found. Skipping.")
        except Exception as e:
            log_and_callback(f"An error occurred during traceroute: {e}")
        
        return log
