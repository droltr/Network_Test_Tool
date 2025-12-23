import os
import json
import csv
from datetime import datetime
import platform
from network.detector import NetworkDetector
from network.advanced import AdvancedDiagnostics

class ReportGenerator:
    def __init__(self):
        self.detector = NetworkDetector()
        self.advanced = AdvancedDiagnostics()
        self.report_dir = os.path.join(os.getcwd(), "reports")
        if not os.path.exists(self.report_dir):
            os.makedirs(self.report_dir)

    def collect_data(self):
        """Collect all available network data for the report."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "system_info": {
                "hostname": platform.node(),
                "os": f"{platform.system()} {platform.release()}",
                "processor": platform.processor()
            },
            "network_info": self.detector.get_network_info(),
            "diagnostics": self.detector.detect_network_issues(),
            "arp_table": self.advanced.get_arp_table(),
            # Active connections might be too verbose for a summary report, 
            # but we can include a count or top 10
            "connection_count": len(self.advanced.get_active_connections())
        }
        return data

    def generate_text_report(self, filename=None):
        """Generate a human-readable text report."""
        data = self.collect_data()
        if not filename:
            filename = f"network_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        filepath = os.path.join(self.report_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("==================================================\n")
            f.write("              NETWORK DIAGNOSTIC REPORT           \n")
            f.write("==================================================\n\n")
            
            f.write(f"Date/Time: {data['timestamp']}\n")
            f.write(f"Hostname:  {data['system_info']['hostname']}\n")
            f.write(f"OS:        {data['system_info']['os']}\n\n")
            
            f.write("--------------------------------------------------\n")
            f.write("1. NETWORK STATUS\n")
            f.write("--------------------------------------------------\n")
            
            # Diagnostics Summary
            status = data['diagnostics']['status'].upper()
            f.write(f"Overall Status: {status}\n\n")
            
            if data['diagnostics']['issues']:
                f.write("Detected Issues:\n")
                for issue in data['diagnostics']['issues']:
                    f.write(f"  - [{issue['severity'].upper()}] {issue['message']}\n")
                    f.write(f"    Solution: {issue['solution']}\n")
            else:
                f.write("No issues detected.\n")
            f.write("\n")

            # Interface Details
            f.write("Network Interfaces:\n")
            for iface in data['network_info'].get('interfaces', []):
                ipv4 = iface.get('ipv4', 'N/A')
                if ipv4 != 'N/A' and not ipv4.startswith('127.'):
                    f.write(f"  Name: {iface.get('name')}\n")
                    f.write(f"  IP:   {ipv4}\n")
                    f.write(f"  MAC:  {iface.get('mac')}\n")
                    f.write(f"  Status: {iface.get('status', 'Unknown')}\n")
                    f.write("\n")

            f.write(f"Gateway: {', '.join(data['network_info'].get('gateway', []))}\n")
            f.write(f"DNS:     {', '.join(data['network_info'].get('dns', []))}\n\n")

            f.write("--------------------------------------------------\n")
            f.write("2. ARP TABLE (First 10 entries)\n")
            f.write("--------------------------------------------------\n")
            f.write(f"{'IP Address':<16} {'MAC Address':<18} {'Type':<10}\n")
            f.write("-" * 44 + "\n")
            
            for entry in data['arp_table'][:10]:
                f.write(f"{entry['ip']:<16} {entry['mac']:<18} {entry['type']:<10}\n")
            
            if len(data['arp_table']) > 10:
                f.write(f"... and {len(data['arp_table']) - 10} more entries.\n")
            
            f.write("\n")
            f.write(f"Total Active Connections: {data['connection_count']}\n")
            
            f.write("\n==================================================\n")
            f.write("End of Report\n")
            
        return filepath

    def generate_json_report(self, filename=None):
        """Generate a JSON report for machine processing."""
        data = self.collect_data()
        if not filename:
            filename = f"network_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = os.path.join(self.report_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
            
        return filepath

    def generate_csv_arp_report(self, filename=None):
        """Export ARP table to CSV."""
        data = self.collect_data()
        if not filename:
            filename = f"arp_table_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
        filepath = os.path.join(self.report_dir, filename)
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["IP Address", "MAC Address", "Type", "Interface"])
            for entry in data['arp_table']:
                writer.writerow([entry['ip'], entry['mac'], entry['type'], entry.get('interface', '')])
                
        return filepath
