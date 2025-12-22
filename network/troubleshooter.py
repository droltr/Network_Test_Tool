import platform
import subprocess
import socket
from datetime import datetime
from .detector import NetworkDetector
from .ping import PingTester
from .speed_test import SpeedTester

class Troubleshooter:
    def __init__(self):
        self.detector = NetworkDetector()
        self.ping_tester = PingTester()
        self.speed_tester = SpeedTester()

    def run_troubleshooting(self, progress_callback=None):
        log = []
        def log_and_callback(message):
            log.append(message)
            if progress_callback:
                progress_callback(message)

        log_and_callback(f"--- Automated Network Troubleshooting --- ({datetime.now().isoformat()})\n")

        # 1. Device and Network Info
        log_and_callback("1. Gathering Device and Network Information...")
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

        # 2. Connectivity Tests

        log_and_callback("2. Performing Connectivity Tests...")
        # Ping Gateway
        gateway = info.get('gateway', [None])[0]
        if gateway:
            log_and_callback(f"    Pinging gateway ({gateway})...")
            ping_result = self.ping_tester.ping_host(gateway, count=3)
            if ping_result and not ping_result.get('error') and 'avg_time' in ping_result.get('statistics', {}):
                log_and_callback(f"        Success ({ping_result['statistics']['avg_time']:.2f}ms avg)")
            else:
                log_and_callback("        Failed to ping gateway.")
        else:
            log_and_callback("    Gateway not found, skipping ping test.")

        # Ping DNS
        dns_server = info.get('dns', [None])[0]
        if dns_server:
            log_and_callback(f"    Pinging primary DNS server ({dns_server})...")
            ping_result = self.ping_tester.ping_host(dns_server, count=3)
            if ping_result and not ping_result.get('error') and 'avg_time' in ping_result.get('statistics', {}):
                log_and_callback(f"        Success ({ping_result['statistics']['avg_time']:.2f}ms avg)")
            else:
                log_and_callback("        Failed to ping DNS server.")
        else:
            log_and_callback("    DNS server not found, skipping ping test.")

        # Ping External Host
        log_and_callback("    Pinging external host (8.8.8.8)...")
        ping_result = self.ping_tester.ping_host("8.8.8.8", count=3)
        if ping_result and not ping_result.get('error') and 'avg_time' in ping_result.get('statistics', {}):
            log_and_callback(f"        Success ({ping_result['statistics']['avg_time']:.2f}ms avg)\n")
        else:
            log_and_callback("        Failed to ping external host.\n")

        # 3. Traceroute
        log_and_callback("3. Performing Traceroute to 1.1.1.1...")
        log.extend(self.run_traceroute("1.1.1.1", progress_callback))

        log_and_callback("\n--- Troubleshooting Complete ---")
        return "\n".join(log)

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
            
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)

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
