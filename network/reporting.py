import os
import json
import csv
from datetime import datetime
import platform
from network.detector import NetworkDetector
from network.advanced import AdvancedDiagnostics
from utils.paths import state_dir

class ReportGenerator:
    def __init__(self, report_dir=None):
        self.detector = NetworkDetector()
        self.advanced = AdvancedDiagnostics()
        # Only used for relative/omitted filenames; created on demand. Never the working directory:
        # in an installed build it is read-only (e.g. Program Files).
        self.report_dir = report_dir or os.path.join(state_dir(), "reports")

    def _target_path(self, filename, default_name):
        """Absolute path to write to. Absolute filenames are used as given; relative ones go to report_dir."""
        if not filename:
            filename = default_name
        filename = os.path.expanduser(filename)
        if not os.path.isabs(filename):
            filename = os.path.join(self.report_dir, filename)
        filepath = os.path.abspath(filename)
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return filepath

    @staticmethod
    def _write(filepath, content, newline=None):
        """Write the whole file in one go, so a failure while collecting data never leaves a partial file."""
        with open(filepath, 'w', encoding='utf-8', newline=newline) as f:
            f.write(content)

    def collect_data(self):
        """Collect all available network data for the report."""
        network_info = self.detector.get_network_info()
        data = {
            "timestamp": datetime.now().isoformat(),
            "system_info": {
                "hostname": platform.node(),
                "os": f"{platform.system()} {platform.release()}",
                "processor": platform.processor()
            },
            "network_info": network_info,
            # Reuse the info collected above instead of probing everything a second time
            "diagnostics": self.detector.detect_network_issues(network_info),
            "arp_table": self.advanced.get_arp_table(),
            # Active connections might be too verbose for a summary report,
            # but we can include a count or top 10
            "connection_count": len(self.advanced.get_active_connections())
        }
        return data

    def generate_text_report(self, filename=None):
        """Generate a human-readable text report."""
        filepath = self._target_path(filename, f"network_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        data = self.collect_data()
        diagnostics = data.get('diagnostics') or {}
        network_info = data.get('network_info') or {}
        lines = []
        w = lines.append

        w("==================================================\n")
        w("              NETWORK DIAGNOSTIC REPORT           \n")
        w("==================================================\n\n")

        w(f"Date/Time: {data['timestamp']}\n")
        w(f"Hostname:  {data['system_info']['hostname']}\n")
        w(f"OS:        {data['system_info']['os']}\n\n")

        w("--------------------------------------------------\n")
        w("1. NETWORK STATUS\n")
        w("--------------------------------------------------\n")

        # Diagnostics Summary
        status = str(diagnostics.get('status', 'unknown')).upper()
        w(f"Overall Status: {status}\n\n")

        if network_info.get('error'):
            w(f"Network information could not be collected: {network_info['error']}\n\n")

        if diagnostics.get('issues'):
            w("Detected Issues:\n")
            for issue in diagnostics['issues']:
                w(f"  - [{str(issue.get('severity', 'info')).upper()}] {issue.get('message', '')}\n")
                if issue.get('solution'):
                    w(f"    Solution: {issue['solution']}\n")
        else:
            w("No issues detected.\n")
        w("\n")

        # Interface Details
        w("Network Interfaces:\n")
        for iface in network_info.get('interfaces', []):
            ipv4 = iface.get('ipv4') or 'N/A'
            if ipv4 != 'N/A' and not ipv4.startswith('127.'):
                w(f"  Name: {iface.get('name')}\n")
                w(f"  IP:   {ipv4}\n")
                w(f"  MAC:  {iface.get('mac')}\n")
                w(f"  Status: {iface.get('status', 'Unknown')}\n")
                w("\n")

        w(f"Gateway: {', '.join(str(g) for g in network_info.get('gateway') or [])}\n")
        w(f"DNS:     {', '.join(str(d) for d in network_info.get('dns') or [])}\n\n")

        w("--------------------------------------------------\n")
        w("2. ARP TABLE (First 10 entries)\n")
        w("--------------------------------------------------\n")
        w(f"{'IP Address':<16} {'MAC Address':<18} {'Type':<10}\n")
        w("-" * 44 + "\n")

        arp_table = data.get('arp_table') or []
        for entry in arp_table[:10]:
            w(f"{entry.get('ip', ''):<16} {entry.get('mac', ''):<18} {entry.get('type', ''):<10}\n")

        if len(arp_table) > 10:
            w(f"... and {len(arp_table) - 10} more entries.\n")

        w("\n")
        w(f"Total Active Connections: {data['connection_count']}\n")

        w("\n==================================================\n")
        w("End of Report\n")

        self._write(filepath, "".join(lines))
        return filepath

    def generate_json_report(self, filename=None):
        """Generate a JSON report for machine processing."""
        filepath = self._target_path(filename, f"network_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        data = self.collect_data()
        # ensure_ascii=False keeps non-ASCII names readable; default=str covers datetimes and other objects
        self._write(filepath, json.dumps(data, indent=4, ensure_ascii=False, default=str))
        return filepath

    def generate_csv_arp_report(self, filename=None):
        """Export ARP table to CSV."""
        filepath = self._target_path(filename, f"arp_table_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        data = self.collect_data()

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["IP Address", "MAC Address", "Type", "Interface"])
            for entry in data.get('arp_table') or []:
                writer.writerow([entry.get('ip', ''), entry.get('mac', ''), entry.get('type', ''),
                                 entry.get('interface', '')])

        return filepath
