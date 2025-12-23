import subprocess
import platform
import re
import logging
import psutil
import socket

class AdvancedDiagnostics:
    def __init__(self):
        self.platform = platform.system().lower()

    def get_arp_table(self):
        """Get ARP table entries."""
        entries = []
        try:
            if self.platform == "windows":
                # Run arp -a
                result = subprocess.run(['arp', '-a'], capture_output=True, text=True, encoding='cp850')
                lines = result.stdout.split('\n')
                
                current_interface = None
                
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    
                    # Check for Interface header
                    if line.startswith("Interface:"):
                        current_interface = line.split()[1]
                        continue
                        
                    # Parse entry lines (IP, MAC, Type)
                    # Example: 192.168.1.1       xx-xx-xx-xx-xx-xx     dynamic
                    parts = line.split()
                    if len(parts) == 3:
                        # Basic validation to ensure it looks like an ARP entry
                        if parts[0][0].isdigit() and '-' in parts[1]:
                            entries.append({
                                'ip': parts[0],
                                'mac': parts[1],
                                'type': parts[2],
                                'interface': current_interface
                            })
            else:
                # Linux/Mac implementation (simplified)
                result = subprocess.run(['arp', '-a'], capture_output=True, text=True)
                # Parsing logic would go here
                pass
                
        except Exception as e:
            logging.error(f"Error getting ARP table: {e}")
            
        return entries

    def get_active_connections(self):
        """Get list of active network connections."""
        conns = []
        try:
            # Use psutil for cross-platform connection info
            for c in psutil.net_connections(kind='inet'):
                # Only show established connections to reduce noise
                if c.status == 'ESTABLISHED':
                    laddr = f"{c.laddr.ip}:{c.laddr.port}"
                    raddr = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else "N/A"
                    
                    # Try to get process name
                    try:
                        process = psutil.Process(c.pid)
                        pname = process.name()
                    except:
                        pname = "Unknown"

                    conns.append({
                        'proto': 'TCP' if c.type == socket.SOCK_STREAM else 'UDP',
                        'local': laddr,
                        'remote': raddr,
                        'status': c.status,
                        'pid': c.pid,
                        'process': pname
                    })
        except Exception as e:
            logging.error(f"Error getting active connections: {e}")
            
        return conns

    def get_netbios_info(self, ip_address):
        """Get NetBIOS info for a specific IP (Windows only)."""
        if self.platform != "windows":
            return "Not supported on this OS"
            
        try:
            result = subprocess.run(['nbtstat', '-A', ip_address], capture_output=True, text=True, encoding='cp850')
            return result.stdout
        except Exception as e:
            return str(e)
