import socket
import threading
import ipaddress
from typing import List, Dict, Optional, Callable
import time


class PortScanner:
    """Advanced port scanner with threading support and progress tracking."""
    
    def __init__(self):
        self.is_scanning = False
        self.progress_callback = None
        self.result_callback = None
        self.results = []
        
    def scan_port(self, host: str, port: int, timeout: float = 1.0) -> Dict:
        """Scan a single port on a host."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                # Try to get service name
                try:
                    service = socket.getservbyport(port)
                except:
                    service = "Unknown"
                
                return {
                    'port': port,
                    'status': 'Open',
                    'service': service
                }
            else:
                return {
                    'port': port,
                    'status': 'Closed',
                    'service': None
                }
        except Exception as e:
            return {
                'port': port,
                'status': 'Error',
                'service': None,
                'error': str(e)
            }
    
    def scan_ports(self, host: str, ports: List[int], timeout: float = 1.0, 
                   progress_callback: Optional[Callable] = None,
                   result_callback: Optional[Callable] = None):
        """Scan multiple ports on a host with progress tracking."""
        self.is_scanning = True
        self.progress_callback = progress_callback
        self.result_callback = result_callback
        self.results = []
        
        total_ports = len(ports)
        
        for i, port in enumerate(ports):
            if not self.is_scanning:
                break
                
            result = self.scan_port(host, port, timeout)
            self.results.append(result)
            
            # Update progress
            if self.progress_callback:
                progress = int((i + 1) / total_ports * 100)
                self.progress_callback(progress)
            
            # Report result if callback provided
            if self.result_callback:
                self.result_callback(result)
                
        self.is_scanning = False
    
    def scan_ports_threaded(self, host: str, ports: List[int], timeout: float = 1.0,
                           progress_callback: Optional[Callable] = None,
                           result_callback: Optional[Callable] = None,
                           complete_callback: Optional[Callable] = None):
        """Scan ports in a separate thread."""
        def scan_worker():
            results = self.scan_ports(host, ports, timeout, progress_callback, result_callback)
            if complete_callback:
                complete_callback(results)
        
        thread = threading.Thread(target=scan_worker, daemon=True)
        thread.start()
        return thread
    
    def stop_scan(self):
        """Stop the current scan."""
        self.is_scanning = False
    
    @staticmethod
    def get_common_ports() -> Dict[str, List[int]]:
        """Get predefined lists of common ports."""
        return {
            'Common': [21, 22, 23, 25, 53, 80, 110, 143, 443, 993, 995],
            'Web': [80, 443, 8080, 8443, 8000, 3000, 5000],
            'FTP': [20, 21, 989, 990],
            'Mail': [25, 110, 143, 465, 587, 993, 995],
            'Database': [1433, 1521, 3306, 5432, 6379, 27017],
            'Remote': [22, 23, 3389, 5900, 5901],
            'All Common (1-1024)': list(range(1, 1025))
        }


class NetworkScanner:
    """Network device discovery scanner."""
    
    def __init__(self):
        self.is_scanning = False
        
    def ping_host(self, host: str, timeout: float = 1.0) -> bool:
        """Ping a single host to check if it's alive."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, 80))  # Try port 80 first
            sock.close()
            
            if result == 0:
                return True
            
            # If port 80 fails, try ICMP ping using os command
            import subprocess
            import platform
            
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            command = ['ping', param, '1', host]
            
            result = subprocess.run(command, capture_output=True, timeout=timeout)
            return result.returncode == 0
            
        except Exception:
            return False
    
    def scan_network(self, network: str, progress_callback: Optional[Callable] = None) -> List[Dict]:
        """Scan a network range for active devices."""
        self.is_scanning = True
        devices = []
        
        try:
            net = ipaddress.ip_network(network, strict=False)
            hosts = list(net.hosts())
            total_hosts = len(hosts)
            
            for i, host in enumerate(hosts):
                if not self.is_scanning:
                    break
                
                host_str = str(host)
                if self.ping_host(host_str):
                    try:
                        hostname = socket.gethostbyaddr(host_str)[0]
                    except:
                        hostname = "Unknown"
                    
                    devices.append({
                        'ip': host_str,
                        'hostname': hostname,
                        'status': 'Active'
                    })
                
                if progress_callback:
                    progress = int((i + 1) / total_hosts * 100)
                    progress_callback(progress)
                    
        except Exception as e:
            print(f"Network scan error: {e}")
        
        self.is_scanning = False
        return devices
    
    def scan_network_threaded(self, network: str, 
                             progress_callback: Optional[Callable] = None,
                             complete_callback: Optional[Callable] = None):
        """Scan network in a separate thread."""
        def scan_worker():
            results = self.scan_network(network, progress_callback)
            if complete_callback:
                complete_callback(results)
        
        thread = threading.Thread(target=scan_worker, daemon=True)
        thread.start()
        return thread
    
    def stop_scan(self):
        """Stop the current scan."""
        self.is_scanning = False