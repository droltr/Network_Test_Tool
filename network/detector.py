import socket
import platform
import subprocess
import psutil
from datetime import datetime
from typing import List
import ipaddress
import re

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
            return info
        except Exception as e:
            return {'error': str(e)}
    
    def get_hostname(self):
        """Get computer hostname"""
        return socket.gethostname()
    
    def get_local_ip(self) -> list[str]:
        """Get all local IP addresses (IPv4) for active interfaces."""
        ip_addresses = []
        try:
            for interface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith('127.'): # Exclude loopback
                        ip_addresses.append(addr.address)
            print(f"DEBUG: get_local_ip - Detected IPs: {ip_addresses}")
        except Exception as e:
            print(f"DEBUG: get_local_ip - Error: {e}")
            pass
        return ip_addresses if ip_addresses else ["Unable to determine"]
    
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
                print(f"DEBUG: get_default_gateway - Detected Gateways (netifaces): {gateways}")
            except Exception as e:
                print(f"DEBUG: get_default_gateway - Error (netifaces): {e}")
        
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
                print(f"DEBUG: get_default_gateway - Detected Gateways (ipconfig): {gateways}")
            except Exception as e:
                print(f"DEBUG: get_default_gateway - Error (ipconfig): {e}")
        return gateways if gateways else ["Unable to determine"]
    
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
                with open('/etc/resolv.conf', 'r') as f:
                    for line in f:
                        if line.startswith('nameserver'):
                            ip = line.split()[1].strip()
                            if ip not in dns_servers:
                                dns_servers.append(ip)
            print(f"DEBUG: get_dns_servers - Detected DNS: {dns_servers}")
        except Exception as e:
            print(f"DEBUG: get_dns_servers - Error: {e}")
            pass
        return dns_servers if dns_servers else ["Unable to determine"]
    
    def get_mac_address(self):
        """Get MAC address of primary interface"""
        try:
            interfaces = psutil.net_if_addrs()
            for interface, addrs in interfaces.items():
                for addr in addrs:
                    if addr.family == psutil.AF_LINK and addr.address != '00:00:00:00:00:00':
                        return addr.address
            return "Unable to determine"
        except:
            return "Unable to determine"
    
    def get_connection_status(self):
        """Get network connection status"""
        connections = []
        
        # Test internet connectivity
        internet_status = self.check_internet_connection()
        connections.append({
            'status': 'Connected' if internet_status else 'Disconnected',
            'description': 'Internet Connection'
        })
        
        # Test local network connectivity
        local_status = self.test_local_network()
        connections.append({
            'status': 'Connected' if local_status else 'Disconnected',
            'description': 'Local Network'
        })
        
        # Test DNS resolution
        dns_status = self.test_dns_resolution()
        connections.append({
            'status': 'Working' if dns_status else 'Failed',
            'description': 'DNS Resolution'
        })
        
        return connections
    
    def get_network_interfaces(self):
        """Get all network interfaces"""
        interfaces = []
        try:
            net_interfaces = psutil.net_if_addrs()
            for interface_name, addrs in net_interfaces.items():
                interface_info = {'name': interface_name}
                
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        interface_info['ipv4'] = addr.address
                    elif addr.family == psutil.AF_LINK:
                        interface_info['mac'] = addr.address.lower() # Convert MAC to lowercase
                
                interfaces.append(interface_info)
            print(f"DEBUG: get_network_interfaces - Detected Interfaces: {interfaces}")
            return interfaces
        except Exception as e:
            print(f"DEBUG: get_network_interfaces - Error: {e}")
            return []

    def check_internet_connection(self):
        """Test internet connectivity by trying to reach Google's DNS server and a well-known website."""
        try:
            # Try to connect to Google's public DNS server
            socket.create_connection(("8.8.8.8", 53), timeout=2)
            
            # Try to fetch a small page from a reliable website
            import urllib.request
            urllib.request.urlopen("http://www.google.com", timeout=2)
            return True
        except:
            return False
    
    def test_local_network(self):
        """Test local network connectivity by trying to reach the default gateway(s)."""
        gateways = self.get_default_gateway()
        for gateway in gateways:
            if gateway != "Unable to determine":
                try:
                    # Try to ping the gateway
                    if platform.system().lower() == 'windows':
                        cmd = ['ping', '-n', '1', gateway]
                    else:
                        cmd = ['ping', '-c', '1', gateway]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3, encoding='cp850')
                    if result.returncode == 0:
                        return True
                except Exception:
                    pass
        return False
    
    def test_dns_resolution(self):
        """Test DNS resolution"""
        try:
            socket.gethostbyname("google.com")
            return True
        except:
            return False

    def detect_network_issues(self):
        """Diagnose common network issues"""
        issues = []
        
        # Check internet connectivity
        if not self.check_internet_connection():
            issues.append("No internet connectivity")
        
        # Check local network
        if not self.test_local_network():
            issues.append("Local network connection issues")
        
        # Check DNS
        if not self.test_dns_resolution():
            issues.append("DNS resolution problems")
        
        return issues if issues else ["No network issues detected"]

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