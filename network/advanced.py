import shutil
import subprocess
import platform
import re
import logging
import psutil
import socket

from utils.paths import run_command

# arp -a section header, e.g. "Interface: 10.90.0.3 --- 0x9" (Turkish "Arabirim: 10.90.0.3 --- 0x9"):
# matched by its shape because the label is translated
ARP_HEADER_RE = re.compile(r'^\S.*?:\s*(\d{1,3}(?:\.\d{1,3}){3})\s+---\s+0x[0-9a-f]+', re.IGNORECASE)



class AdvancedDiagnostics:
    def __init__(self):
        self.platform = platform.system().lower()

    def get_arp_table(self):
        """Get ARP table entries."""
        entries = []
        try:
            if self.platform == "windows":
                result = run_command(['arp', '-a'], timeout=10)
                lines = result.stdout.split('\n')

                current_interface = None

                for line in lines:
                    line = line.strip()
                    if not line: continue

                    header = ARP_HEADER_RE.match(line)
                    if header:
                        current_interface = header.group(1)
                        continue

                    # Parse entry lines (IP, MAC, Type)
                    # Example: 192.168.1.1       xx-xx-xx-xx-xx-xx     dynamic
                    parts = line.split()
                    if len(parts) == 3:
                        # Basic validation to ensure it looks like an ARP entry
                        if parts[0][0].isdigit() and '-' in parts[1]:
                            # The type word is translated too ("statik", "statisch", "estático")
                            kind = parts[2].lower()
                            entries.append({
                                'ip': parts[0],
                                'mac': parts[1],
                                'type': 'static' if 'stat' in kind or 'stát' in kind else 'dynamic',
                                'interface': current_interface
                            })
            elif self.platform == "linux":
                entries = self._linux_neighbours()
            else:
                entries = self._bsd_arp()

        except Exception as e:
            logging.error(f"Error getting ARP table: {e}")

        return entries

    def _linux_neighbours(self):
        """IPv4 neighbour table from `ip neigh`, falling back to /proc/net/arp."""
        entries = []
        try:
            result = run_command(['ip', '-4', 'neigh', 'show'], timeout=5)
            # Example: 192.168.1.1 dev eth0 lladdr f4:92:bf:0a:11:3c REACHABLE
            for line in result.stdout.splitlines():
                match = re.match(r'(\S+) dev (\S+) lladdr (\S+)(?: router)?(?: proxy)? (\S+)', line.strip())
                if not match:
                    continue  # FAILED / INCOMPLETE entries have no MAC
                ip, iface, mac, state = match.groups()
                entries.append({
                    'ip': ip,
                    'mac': mac.lower(),
                    'type': 'static' if state in ('PERMANENT', 'NOARP') else 'dynamic',
                    'interface': iface
                })
            if entries or result.returncode == 0:
                return entries
        except (OSError, subprocess.SubprocessError) as e:
            logging.debug(f"ip neigh failed, using /proc/net/arp: {e}")

        with open('/proc/net/arp') as f:
            next(f)  # header
            for line in f:
                fields = line.split()
                if len(fields) < 6 or fields[3] == '00:00:00:00:00:00':
                    continue
                flags = int(fields[2], 16)
                entries.append({
                    'ip': fields[0],
                    'mac': fields[3].lower(),
                    'type': 'static' if flags & 0x4 else 'dynamic',  # ATF_PERM
                    'interface': fields[5]
                })
        return entries

    def _bsd_arp(self):
        """macOS / BSD `arp -an` output: ? (192.168.1.1) at f4:92:.. on en0 ifscope [ethernet]"""
        entries = []
        result = run_command(['arp', '-an'], timeout=10)
        for line in result.stdout.splitlines():
            match = re.search(r'\((\S+)\) at (\S+) on (\S+)(.*)', line)
            if match and match.group(2) != '(incomplete)':
                entries.append({
                    'ip': match.group(1),
                    'mac': match.group(2).lower(),
                    'type': 'static' if 'permanent' in match.group(4) else 'dynamic',
                    'interface': match.group(3)
                })
        return entries

    def get_active_connections(self, include_all=False):
        """Get list of network connections.

        By default only established connections are returned (used for report counts).
        With include_all=True, listening sockets and UDP endpoints are included too.
        """
        conns = []
        process_names = {}
        try:
            # Use psutil for cross-platform connection info
            for c in psutil.net_connections(kind='inet'):
                # Only show established connections to reduce noise
                if not include_all and c.status != 'ESTABLISHED':
                    continue
                laddr = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "*:*"
                raddr = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ("N/A" if not include_all else "*:*")

                # Try to get process name; sockets of other users have no PID without root
                if c.pid is None:
                    pname = "Unknown"
                elif c.pid in process_names:
                    pname = process_names[c.pid]
                else:
                    try:
                        pname = psutil.Process(c.pid).name()
                    except (psutil.Error, OSError):
                        pname = "Unknown"
                    process_names[c.pid] = pname

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

    def lookup_netbios(self, ip_address):
        """NetBIOS node status lookup.

        Returns {'ok': bool, 'output': str, 'error': str or None}. Uses nbtstat on Windows and
        nmblookup (samba-client) elsewhere.
        """
        if self.platform == "windows":
            command = ['nbtstat', '-A', ip_address]
        else:
            if not shutil.which('nmblookup'):
                return {'ok': False, 'output': '',
                        'error': "nmblookup was not found. Install the samba-client package to use NetBIOS lookups."}
            command = ['nmblookup', '-A', ip_address]

        try:
            result = run_command(command, timeout=15)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'output': '', 'error': f"No response from {ip_address}"}
        except Exception as e:
            return {'ok': False, 'output': '', 'error': str(e)}

        output = (result.stdout + result.stderr).strip()
        # A reply is a NetBIOS name table: names with a <xx> suffix ("WORKSTATION <00> UNIQUE").
        # nbtstat exits with 0 and prints a translated "Host not found." for silent hosts.
        no_reply = result.returncode != 0 or not re.search(r'<[0-9A-Fa-f]{2}>', output)
        return {'ok': not no_reply, 'output': output,
                'error': f"No response from {ip_address}" if no_reply else None}

    def get_netbios_info(self, ip_address):
        """Get NetBIOS info for a specific IP as text."""
        result = self.lookup_netbios(ip_address)
        return result['output'] or result['error'] or ''
