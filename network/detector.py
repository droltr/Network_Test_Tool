import os
import time
import socket
import platform
import subprocess
import psutil
from datetime import datetime
from typing import List
import ipaddress
import re
import logging

from utils.paths import command_env, log_file_path

# Configure logging to a file in the per-user state directory
logging.basicConfig(filename=log_file_path('network_detector_debug.log'), level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Try to import netifaces, use fallback if not available
try:
    import netifaces
    HAS_NETIFACES = True
except ImportError:
    HAS_NETIFACES = False

class NetworkDetector:
    def __init__(self):
        self.platform = platform.system().lower()
        
    def get_network_info(self):
        """Get comprehensive network information"""
        try:
            info = {
                'hostname': self.get_hostname(),
                'gateway': self.get_default_gateway(),
                'dns': self.get_dns_servers(),
                'connections': self.get_connection_status(),
                'interfaces': self.get_network_interfaces(),
                'timestamp': datetime.now().isoformat()
            }
            logging.debug(f"NetworkDetector.get_network_info - Collected info: {info}")
            return info
        except Exception as e:
            logging.error(f"NetworkDetector.get_network_info - {e}")
            return {'error': str(e)}
    
    def get_hostname(self):
        """Get computer hostname"""
        try:
            hostname = socket.gethostname()
            logging.debug(f"get_hostname - {hostname}")
            return hostname
        except Exception as e:
            logging.error(f"get_hostname - {e}")
            return "N/A"
    
    def get_local_ip(self) -> list[str]:
        """Get all local IP addresses (IPv4) for active interfaces."""
        ip_addresses = []
        try:
            for interface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith('127.'): # Exclude loopback
                        ip_addresses.append(addr.address)
            logging.debug(f"get_local_ip - {ip_addresses}")
        except Exception as e:
            logging.error(f"get_local_ip - {e}")
        return ip_addresses if ip_addresses else ["N/A"]
    
    def get_default_gateway(self) -> list[str]:
        """Get default gateway IP addresses."""
        gateways = []
        if HAS_NETIFACES:
            try:
                gws = netifaces.gateways()
                for gw_family in [netifaces.AF_INET]:
                    if gw_family in gws and gws[gw_family]:
                        for gw_info in gws[gw_family]:
                            gateways.append(gw_info[0])
                logging.debug(f"get_default_gateway - {gateways}")
            except Exception as e:
                logging.error(f"get_default_gateway - {e}")
        
        if not gateways and self.platform == "windows":
            try:
                result = subprocess.run(['ipconfig'], capture_output=True, text=True, encoding='cp850')
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'Default Gateway' in line:
                        parts = line.split(':')
                        if len(parts) > 1:
                            gateway = parts[1].strip()
                            if gateway and gateway != '0.0.0.0':
                                gateways.append(gateway)
                logging.debug(f"get_default_gateway (ipconfig) - {gateways}")
            except Exception as e:
                logging.error(f"get_default_gateway (ipconfig) - {e}")

        if not gateways and self.platform == "linux":
            for _iface, gateway in self._linux_default_routes():
                if gateway not in gateways:
                    gateways.append(gateway)
            logging.debug(f"get_default_gateway (/proc/net/route) - {gateways}")
        return gateways if gateways else ["N/A"]

    def _linux_default_routes(self):
        """Return (interface, gateway) pairs for IPv4 default routes, best metric first."""
        routes = []
        try:
            with open('/proc/net/route') as f:
                next(f)  # header
                for line in f:
                    fields = line.split()
                    if len(fields) < 8:
                        continue
                    iface, destination, gateway_hex, flags, metric = fields[0], fields[1], fields[2], int(fields[3], 16), int(fields[6])
                    # RTF_UP (0x1) and RTF_GATEWAY (0x2) on the 0.0.0.0 destination
                    if destination != '00000000' or not flags & 0x2:
                        continue
                    gateway = socket.inet_ntoa(bytes.fromhex(gateway_hex)[::-1])
                    routes.append((metric, iface, gateway))
        except (OSError, ValueError, StopIteration) as e:
            logging.error(f"_linux_default_routes - {e}")
        return [(iface, gateway) for _metric, iface, gateway in sorted(routes)]

    def get_primary_interface(self):
        """Return (interface name, IPv4) of the interface that carries the default route."""
        addrs = psutil.net_if_addrs()

        def ipv4_of(name):
            for addr in addrs.get(name, []):
                if addr.family == socket.AF_INET:
                    return addr.address
            return None

        if self.platform == "linux":
            for iface, _gateway in self._linux_default_routes():
                ip = ipv4_of(iface)
                if ip:
                    return iface, ip

        # Fallback: the address the OS would use to reach the internet
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 53))
                ip = s.getsockname()[0]
            for name in addrs:
                if ipv4_of(name) == ip:
                    return name, ip
            return "", ip
        except OSError:
            return "", None
    
    def get_dns_servers(self) -> list[str]:
        """Get DNS server addresses."""
        dns_servers = []
        try:
            if self.platform == "windows":
                result = subprocess.run(['ipconfig', '/all'], capture_output=True, text=True, encoding='cp850')
                lines = result.stdout.split('\n')
                for i, line in enumerate(lines):
                    if 'DNS Servers' in line or 'DNS Sunucuları' in line: # Handle Turkish locale
                        # Look for IP addresses in the current and next few lines
                        for j in range(i, min(i + 5, len(lines))):
                            ip_matches = re.findall(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', lines[j])
                            for ip in ip_matches:
                                if ip not in dns_servers:
                                    dns_servers.append(ip)
            else: # Linux/macOS
                # systemd-resolved: resolv.conf only lists the 127.0.0.53 stub,
                # so ask resolvectl for the real upstream servers first.
                dns_servers.extend(self._resolvectl_dns_servers())
                with open('/etc/resolv.conf', 'r') as f:
                    for line in f:
                        if line.startswith('nameserver'):
                            ip = line.split()[1].strip()
                            if ip not in dns_servers:
                                dns_servers.append(ip)
                # Drop the local stub when real servers are known
                upstream = [ip for ip in dns_servers if not ip.startswith('127.')]
                if upstream:
                    dns_servers = upstream
            logging.debug(f"get_dns_servers - {dns_servers}")
        except Exception as e:
            logging.error(f"get_dns_servers - {e}")
        return dns_servers if dns_servers else ["N/A"]
    
    def _resolvectl_dns_servers(self):
        """IPv4 DNS servers reported by systemd-resolved, or [] when unavailable."""
        try:
            result = subprocess.run(['resolvectl', 'dns'], capture_output=True, text=True, timeout=3,
                                    env=command_env())
        except (OSError, subprocess.SubprocessError):
            return []
        servers = []
        for ip in re.findall(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', result.stdout):
            if ip not in servers:
                servers.append(ip)
        return servers

    def get_mac_address(self):
        """Get MAC address of primary interface"""
        try:
            interfaces = psutil.net_if_addrs()
            for interface, addrs in interfaces.items():
                for addr in addrs:
                    if addr.family == psutil.AF_LINK and addr.address != '00:00:00:00:00:00':
                        logging.debug(f"get_mac_address - {addr.address}")
                        return addr.address
            logging.debug(f"get_mac_address - No MAC found")
            return "N/A"
        except Exception as e:
            logging.error(f"get_mac_address - {e}")
            return "N/A"
    
    def get_connection_status(self):
        """Get network connection status"""
        connections = []
        logging.debug("Getting connection status...")
        
        # Test internet connectivity
        try:
            internet_status = self.check_internet_connection()
            connections.append({
                'status': 'Connected' if internet_status else 'Disconnected',
                'description': 'Internet Connection'
            })
            logging.debug(f"Internet connection status: {'Connected' if internet_status else 'Disconnected'}")
        except Exception as e:
            logging.error(f"Error checking internet connection: {str(e)}")
            connections.append({
                'status': 'Error',
                'description': 'Internet Connection'
            })
        
        # Test local network connectivity
        try:
            local_status = self.test_local_network()
            connections.append({
                'status': 'Connected' if local_status else 'Disconnected',
                'description': 'Local Network'
            })
            logging.debug(f"Local network status: {'Connected' if local_status else 'Disconnected'}")
        except Exception as e:
            logging.error(f"Error checking local network: {str(e)}")
            connections.append({
                'status': 'Error',
                'description': 'Local Network'
            })
        
        # Test DNS resolution
        try:
            dns_status = self.test_dns_resolution()
            connections.append({
                'status': 'Working' if dns_status else 'Failed',
                'description': 'DNS Resolution'
            })
            logging.debug(f"DNS resolution status: {'Working' if dns_status else 'Failed'}")
        except Exception as e:
            logging.error(f"Error checking DNS resolution: {str(e)}")
            connections.append({
                'status': 'Error',
                'description': 'DNS Resolution'
            })
        
        logging.debug(f"Final connection statuses: {connections}")
        return connections
    
    def get_network_interfaces(self):
        """Get all network interfaces with their status."""
        interfaces = []
        try:
            # Get basic interface info with psutil
            net_interfaces = psutil.net_if_addrs()
            for interface_name, addrs in net_interfaces.items():
                interface_info = {'name': interface_name, 'status': 'Unknown', 'ipv4': 'N/A', 'mac': 'N/A'}
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        interface_info['ipv4'] = addr.address
                    elif addr.family == psutil.AF_LINK:
                        interface_info['mac'] = addr.address.lower()
                interfaces.append(interface_info)

            # On Windows, use netsh to get admin state
            if self.platform == "windows":
                try:
                    result = subprocess.run(['netsh', 'interface', 'show', 'interface'], capture_output=True, text=True, check=True)
                    lines = result.stdout.strip().split('\n')
                    for line in lines[3:]: # Skip header lines
                        parts = line.split()
                        if len(parts) >= 4:
                            status = parts[0]
                            name = " ".join(parts[3:])
                            for iface in interfaces:
                                if iface['name'] == name:
                                    iface['status'] = status
                                    break
                except (subprocess.CalledProcessError, FileNotFoundError):
                    pass # netsh might not be available or fail
            else:
                stats = psutil.net_if_stats()
                for iface in interfaces:
                    st = stats.get(iface['name'])
                    if st is not None:
                        iface['status'] = 'Up' if st.isup else 'Down'
                    iface['virtual'] = self.is_virtual_interface(iface['name'])

            logging.debug(f"get_network_interfaces - Detected Interfaces: {interfaces}")
            return interfaces
        except Exception as e:
            logging.error(f"get_network_interfaces - Error: {e}")
            return []

    def is_virtual_interface(self, name):
        """True for loopback, bridges, veth, tunnels and other non-hardware links (Linux)."""
        if self.platform != "linux":
            return name.lower().startswith('loopback')
        # Physical NICs (Ethernet, Wi-Fi, USB) expose a 'device' link in sysfs
        return not os.path.exists(f'/sys/class/net/{name}/device')

    def set_adapter_state(self, adapter_name, state):
        """Enable or disable a network adapter on Windows."""
        if self.platform != "windows":
            return False, "This function is only available on Windows."
        
        action = "enable" if state else "disable"
        try:
            command = ['netsh', 'interface', 'set', 'interface', f'name="{adapter_name}"', f'admin={action}']
            result = subprocess.run(command, capture_output=True, text=True, check=True, shell=True)
            if result.returncode == 0:
                return True, f"Adapter '{adapter_name}' {action}d successfully."
            else:
                return False, f"Failed to {action} adapter. Error: {result.stderr}"
        except subprocess.CalledProcessError as e:
            return False, f"Failed to {action} adapter. Make sure to run as administrator. Error: {e.stderr}"
        except FileNotFoundError:
            return False, "The 'netsh' command was not found. This script requires it to run."

    def check_internet_connection(self):
        """Test internet connectivity by trying to reach Google's DNS server and a well-known website."""
        try:
            # Try to connect to Google's public DNS server
            socket.create_connection(("8.8.8.8", 53), timeout=2)
            
            # Try to fetch a small page from a reliable website
            import urllib.request
            urllib.request.urlopen("http://www.google.com", timeout=2)
            logging.debug("Internet connection test: Connected")
            return True
        except Exception as e:
            logging.debug(f"Internet connection test failed: {str(e)}")
            return False
    
    def test_local_network(self):
        """Test local network connectivity by trying to reach the default gateway(s)."""
        gateways = self.get_default_gateway()
        logging.debug(f"Testing local network with gateways: {gateways}")
        for gateway in gateways:
            if gateway != "Unable to determine" and gateway != "N/A":
                try:
                    # Try to ping the gateway
                    if platform.system().lower() == 'windows':
                        cmd = ['ping', '-n', '1', gateway]
                    else:
                        cmd = ['ping', '-c', '1', gateway]
                    logging.debug(f"Running ping command: {' '.join(cmd)}")
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3,
                                            encoding='cp850' if self.platform == 'windows' else None,
                                            env=command_env())
                    if result.returncode == 0:
                        logging.debug(f"Local network test to {gateway} successful")
                        return True
                    else:
                        logging.debug(f"Ping to {gateway} failed with return code {result.returncode}")
                except Exception as e:
                    logging.debug(f"Error pinging gateway {gateway}: {str(e)}")
        logging.debug("Local network test failed for all gateways")
        return False
    
    def test_dns_resolution(self):
        """Test DNS resolution"""
        try:
            resolved_ip = socket.gethostbyname("google.com")
            logging.debug(f"DNS resolution successful: google.com -> {resolved_ip}")
            return True
        except Exception as e:
            logging.debug(f"DNS resolution failed: {str(e)}")
            return False

    def _ping_host(self, host):
        """Helper to ping a host"""
        try:
            if platform.system().lower() == 'windows':
                cmd = ['ping', '-n', '1', '-w', '1000', host]
            else:
                cmd = ['ping', '-c', '1', '-W', '1', host]
            
            # We don't need the output, just the return code
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=command_env())
            return result.returncode == 0
        except:
            return False

    def detect_network_issues(self, info=None):
        """Diagnose common network issues. Pass `info` to reuse a fresh get_network_info() result."""
        issues = []
        status = "ok"
        
        # Get current network info
        if info is None:
            info = self.get_network_info()
        interfaces = info.get('interfaces', [])
        gateways = info.get('gateway', [])
        
        # 1. Check for APIPA (169.254.x.x)
        for iface in interfaces:
            ipv4 = iface.get('ipv4', '')
            if ipv4.startswith('169.254'):
                issues.append({
                    "type": "apipa_address",
                    "severity": "warning",
                    "message": f"APIPA address detected on {iface.get('name')}",
                    "solution": ("DHCP server not responding. Try 'ipconfig /renew'" if self.platform == "windows"
                                 else "DHCP server not responding. Renew the DHCP lease."),
                    "adapter": iface.get('name'),
                    "address": ipv4
                })
                if status == "ok": status = "warning"

        # 2. Check for No Default Gateway
        # Only if we have an active interface (excluding loopback and APIPA)
        active_ifaces = [i for i in interfaces if i.get('ipv4') != 'N/A' and not i.get('ipv4').startswith('127.') and not i.get('ipv4').startswith('169.')]
        # Bridges, containers and VPN tunnels are not competing adapters
        physical_active = [i for i in active_ifaces if not i.get('virtual')]
        
        if active_ifaces and (not gateways or gateways == ['N/A'] or gateways == ['0.0.0.0']):
            issues.append({
                "type": "no_gateway",
                "severity": "critical",
                "message": "No default gateway configured",
                "solution": "Check DHCP settings or configure static IP"
            })
            status = "critical"

        # 3. Gateway Unreachable
        if gateways and gateways != ['N/A'] and gateways != ['0.0.0.0']:
            gateway_reachable = False
            for gw in gateways:
                if self._ping_host(gw):
                    gateway_reachable = True
                    break
            
            if not gateway_reachable:
                issues.append({
                    "type": "gateway_unreachable",
                    "severity": "critical",
                    "message": "Cannot reach default gateway",
                    "solution": "Check physical connection to router/switch"
                })
                status = "critical"

        # 4. DNS Resolution Failure
        # Check if we can ping 8.8.8.8 but not resolve google.com
        can_ping_google_dns = self._ping_host("8.8.8.8")
        can_resolve = self.test_dns_resolution()
        
        if can_ping_google_dns and not can_resolve:
            issues.append({
                "type": "dns_failure",
                "severity": "critical",
                "message": "DNS servers not responding",
                "solution": "Change DNS to 8.8.8.8 and 8.8.4.4",
                "dns": info.get('dns', [])
            })
            status = "critical"

        # 5. Multiple Active Adapters
        if len(physical_active) > 1:
            issues.append({
                "type": "multiple_adapters",
                "severity": "warning",
                "message": "Multiple active network adapters detected",
                "solution": "Disable unused adapters to prevent routing issues"
            })
            if status == "ok": status = "warning"

        return {
            "status": status,
            "issues": issues
        }

    def _ping_time(self, host, timeout=1):
        """Round-trip time of one ping in ms, or None when there is no reply."""
        if self.platform == 'windows':
            cmd = ['ping', '-n', '1', '-w', str(timeout * 1000), host]
        else:
            cmd = ['ping', '-c', '1', '-W', str(timeout), host]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2,
                                    encoding='cp850' if self.platform == 'windows' else None,
                                    env=command_env())
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        match = re.search(r'time[=<]\s*([\d.]+)\s*ms', result.stdout, re.IGNORECASE)
        return float(match.group(1)) if match else 0.0

    def probe_connection_path(self, info=None):
        """Check each link of This PC -> Gateway -> DNS -> Internet.

        Returns a list of four nodes: {'name', 'status', 'detail', 'ms'} where status is
        'ok', 'fail' or 'unknown' and ms is the latency of the link leading to that node.
        """
        if info is None:
            info = self.get_network_info()
        iface, local_ip = self.get_primary_interface()
        gateways = [g for g in info.get('gateway', []) if g not in ('N/A', '0.0.0.0')]
        dns_servers = [d for d in info.get('dns', []) if d != 'N/A']

        nodes = [{'name': 'This PC', 'status': 'ok' if local_ip else 'fail',
                  'detail': local_ip or 'no address', 'ms': None, 'iface': iface}]

        gateway_ms = self._ping_time(gateways[0]) if gateways else None
        nodes.append({'name': 'Gateway', 'status': 'ok' if gateway_ms is not None else 'fail',
                      'detail': gateways[0] if gateways else 'none', 'ms': gateway_ms})

        start = time.perf_counter()
        try:
            socket.getaddrinfo('google.com', 443, socket.AF_INET)
            dns_ms = (time.perf_counter() - start) * 1000
        except OSError:
            dns_ms = None
        nodes.append({'name': 'DNS', 'status': 'ok' if dns_ms is not None else 'fail',
                      'detail': 'resolving' if dns_ms is not None else 'not resolving',
                      'ms': dns_ms, 'server': dns_servers[0] if dns_servers else None})

        internet_ms = self._ping_time('8.8.8.8')
        if internet_ms is not None:
            nodes.append({'name': 'Internet', 'status': 'ok', 'detail': '8.8.8.8', 'ms': internet_ms})
        elif nodes[1]['status'] == 'fail':
            nodes.append({'name': 'Internet', 'status': 'unknown', 'detail': 'unknown', 'ms': None})
        else:
            nodes.append({'name': 'Internet', 'status': 'fail', 'detail': '8.8.8.8', 'ms': None})
        return nodes

    def get_network_status(self):
        """Get current network status"""
        return self.get_network_info()

    def diagnose(self):
        """Comprehensive method to diagnose network issues"""
        diagnosis = {
            'network_info': self.get_network_info(),
            'issues': self.detect_network_issues(),
            'timestamp': datetime.now().isoformat()
        }
        return diagnosis