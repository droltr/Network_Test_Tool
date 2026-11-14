import platform
from datetime import datetime
from .detector import NetworkDetector
from .ping import PingTester
from .speed_test import SpeedTester
from .trace import TraceRoute


class _Stopped(Exception):
    """Raised between steps after Troubleshooter.stop()."""


class Troubleshooter:
    def __init__(self):
        self.detector = NetworkDetector()
        self.ping_tester = PingTester()
        self.speed_tester = SpeedTester()
        self.tracer = TraceRoute()
        self.stopped = False

    def stop(self):
        """Cancel a running run_troubleshooting(): ends the current ping and the traceroute process
        and skips the remaining steps."""
        self.stopped = True
        self.ping_tester.stop()
        self.tracer.stop()

    # Step ids reported through event_callback, in execution order
    STEPS = ('info', 'gateway', 'dns', 'external', 'trace')

    def run_troubleshooting(self, progress_callback=None, event_callback=None):
        """Run all checks. progress_callback gets each log line; event_callback(step, status, value)
        gets structured step updates (status: running, done, failed, partial, skipped)."""
        log = []
        try:
            self._run_steps(log, progress_callback, event_callback)
        except _Stopped:
            log.append("\n--- Troubleshooting stopped ---")
        return "\n".join(log)

    def _run_steps(self, log, progress_callback, event_callback):
        def log_and_callback(message):
            log.append(message)
            if progress_callback:
                progress_callback(message)

        def event(step, status, value=""):
            if event_callback:
                event_callback(step, status, value)

        def ping_step(step, host):
            if self.stopped:
                raise _Stopped
            event(step, 'running', host)
            ping_result = self.ping_tester.ping_host(host, count=3)
            if self.stopped:
                raise _Stopped
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
        if self.stopped:
            raise _Stopped
        log_and_callback("3. Performing Traceroute to 1.1.1.1...")
        event('trace', 'running', "1.1.1.1")
        trace_log, hops = self.run_traceroute("1.1.1.1", progress_callback)
        log.extend(trace_log)
        if self.stopped:
            raise _Stopped
        event('trace', *self._summarize_trace(hops))

        log_and_callback("\n--- Troubleshooting Complete ---")

    @staticmethod
    def _summarize_trace(hops):
        """(status, value) for the traceroute step from the parsed hops of TraceRoute."""
        if any('error' in hop for hop in hops):
            return 'failed', "not available"
        replied = [hop['hop'] for hop in hops if hop.get('status') == 'ok']
        reached = [hop['hop'] for hop in hops if hop.get('destination')]
        if reached:
            return 'done', f"{reached[0]} hops"
        if not replied:
            return 'failed', "no reply"
        return 'partial', f"stopped at hop {max(replied)}"

    def run_traceroute(self, host, progress_callback=None):
        """Trace to host with up to 15 hops. Returns (raw output lines, parsed hop dicts)."""
        log, hops = [], []
        def log_and_callback(message):
            log.append(message)
            if progress_callback:
                progress_callback(message)

        def on_hop(hop):
            hops.append(hop)
            if 'error' in hop:
                log_and_callback(f"Traceroute failed: {hop['error']}")

        # TraceRoute parses the hops by structure, so translated tracert output is understood too,
        # and stop() can terminate the process
        self.tracer.run_trace(host, on_hop, max_hops=15, line_callback=log_and_callback)
        return log, hops
