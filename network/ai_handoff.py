"""Build a diagnostic package that the user can paste into their own AI assistant.

The package is Markdown: instructions for the assistant, a short summary for humans and
the full data as a JSON block. Nothing is sent anywhere by this module.
"""
import ipaddress
import json
import platform
import re
import socket
from datetime import datetime

from network.advanced import AdvancedDiagnostics
from network.detector import NetworkDetector
from version import __version__

SCHEMA_VERSION = 1

MODES = {
    "simple": "Simple explanation",
    "expert": "Expert analysis",
}

ANSWER_LANGUAGES = ["Same as my question", "English", "Turkish", "German", "French", "Spanish", "Italian",
                    "Dutch", "Portuguese", "Russian", "Arabic", "Chinese", "Japanese"]

PROMPTS = {
    "simple": """You are helping someone who is not a network expert understand the results of
"Network Test Tool", a desktop network diagnostic app. The data below was collected on
their computer. Please:

1. Give a one-paragraph overall verdict: is the connection healthy, and if not, where is
   the problem (this computer, the local network/router, DNS, the internet provider, or
   the remote service)?
2. List each problem you find in plain language, with the evidence from the data.
3. Give step-by-step fixes, easiest and safest first. Say which steps need administrator
   rights or a router restart.
4. Say which additional test in Network Test Tool would help if the data is not enough
   (Diagnose host, Port scanner, Speed test, iPerf3, Troubleshooter, Network health scan,
   Connection monitor).

Rules: use only the data provided and do not invent values. Clearly separate what the
data shows from what you are assuming. Avoid jargon or explain it briefly.""",
    "expert": """You are a senior network engineer reviewing output from "Network Test Tool", a
desktop network diagnostic app. The data below was collected on the user's computer.
Please:

1. Assess each layer: interfaces and addressing, default route and gateway, DNS
   resolution, path latency and loss (ping/traceroute), throughput (speed test / iPerf3)
   and any recorded outages.
2. Correlate the results and identify root-cause candidates, ranked by likelihood, with
   the supporting evidence and any contradicting evidence.
3. Point out anomalies such as leftover VPN routes or adapters, unreachable DNS servers,
   asymmetric throughput, retransmits, MTU or bufferbloat symptoms, and silent hops versus
   real loss.
4. Recommend concrete next diagnostic steps and fixes, including the exact commands for
   the user's operating system.

Rules: use only the data provided; state confidence for each conclusion and mark
assumptions explicitly.""",
}


# ------------------------------------------------------------------ collection

def collect_system_snapshot():
    """Current system, network and diagnostic state (runs pings; call off the GUI thread)."""
    detector = NetworkDetector()
    info = detector.get_network_info()
    diagnostics = detector.detect_network_issues(info)
    path = detector.probe_connection_path(info)
    iface, ip = detector.get_primary_interface()
    advanced = AdvancedDiagnostics()
    try:
        arp_entries = len(advanced.get_arp_table())
    except Exception:
        arp_entries = None
    try:
        established = len(advanced.get_active_connections())
    except Exception:
        established = None

    interfaces = []
    for entry in info.get('interfaces', []):
        if entry.get('ipv4', '').startswith('127.') or entry.get('name') == 'lo':
            continue
        interfaces.append({key: entry.get(key) for key in ('name', 'status', 'ipv4', 'mac', 'virtual')
                           if key in entry})

    return {
        "system": {
            "os": f"{platform.system()} {platform.release()}",
            "os_version": platform.version(),
            "machine": platform.machine(),
            "hostname": info.get('hostname') or socket.gethostname(),
        },
        "network": {
            "primary_interface": iface,
            "primary_ipv4": ip,
            "default_gateways": info.get('gateway', []),
            "dns_servers": info.get('dns', []),
            "interfaces": interfaces,
            "connectivity_checks": info.get('connections', []),
            "connection_path": path,
            "arp_entries": arp_entries,
            "established_connections": established,
        },
        "detected_issues": diagnostics,
    }


def recent_result_for_ai(entry):
    """Trim stored results to what helps an analysis (drop UI-only fields)."""
    data = dict(entry.get('data') or {})
    if entry.get('kind') == 'iperf':
        data.pop('samples', None)   # per-second samples are already in 'intervals'
    return {
        "type": entry.get('kind'),
        "target": entry.get('target'),
        "summary": entry.get('summary'),
        "time": entry.get('time'),
        "details": data,
    }


# ------------------------------------------------------------------ privacy

MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Well-known public resolvers stay readable; they help the analysis and identify no one
KEEP_PUBLIC = {"8.8.8.8", "8.8.4.4", "1.1.1.1", "1.0.0.1", "9.9.9.9", "208.67.222.222", "208.67.220.220"}


def redact(text, mask_mac=True, mask_public_ip=True, mask_hostname=True, hostname=None):
    """Replace identifying values with stable placeholders (MAC_1, PUBLIC_IP_1, HOSTNAME)."""
    if mask_hostname and hostname and len(hostname) > 1:
        text = re.sub(re.escape(hostname), "HOSTNAME", text, flags=re.IGNORECASE)

    if mask_mac:
        macs = {}

        def mac_token(match):
            value = match.group(0).lower().replace("-", ":")
            if value in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
                return match.group(0)
            macs.setdefault(value, f"MAC_{len(macs) + 1}")
            return macs[value]
        text = MAC_RE.sub(mac_token, text)

    if mask_public_ip:
        public = {}

        def ip_token(match):
            value = match.group(0)
            try:
                address = ipaddress.ip_address(value)
            except ValueError:
                return value
            if not address.is_global or value in KEEP_PUBLIC:
                return value
            public.setdefault(value, f"PUBLIC_IP_{len(public) + 1}")
            return public[value]
        text = IPV4_RE.sub(ip_token, text)
    return text


# ------------------------------------------------------------------ rendering

def build_package(snapshot, recent_results, extra_logs, mode="simple", question="",
                  answer_language="Same as my question", privacy=None):
    """Return the Markdown package as a string."""
    privacy = privacy or {}
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "schema": "network-test-tool/diagnostics",
        "schema_version": SCHEMA_VERSION,
        "generated_by": f"Network Test Tool {__version__}",
        "created": created,
        "snapshot": snapshot,
        "recent_tests": recent_results,
        "logs": extra_logs,
    }

    issues = (snapshot or {}).get("detected_issues", {}) or {}
    network = (snapshot or {}).get("network", {}) or {}
    lines = ["# Network diagnostics for AI analysis", ""]
    lines += ["## Instructions for the AI assistant", "", PROMPTS.get(mode, PROMPTS["simple"]), ""]
    if answer_language and answer_language != "Same as my question":
        lines += [f"Write your answer in {answer_language}.", ""]
    else:
        lines += ["Write your answer in the language of the user's question below (English if there is none).",
                  ""]
    lines += ["## The user's question", "", question.strip() or "(No question; analyse the data.)", ""]

    lines += ["## Summary", ""]
    if snapshot:
        system = snapshot.get("system", {})
        lines.append(f"- System: {system.get('os', '?')} ({system.get('machine', '?')})")
        lines.append(f"- Primary interface: {network.get('primary_interface') or '?'} "
                     f"{network.get('primary_ipv4') or ''}".rstrip())
        lines.append(f"- Gateway: {', '.join(network.get('default_gateways') or ['?'])}; "
                     f"DNS: {', '.join(network.get('dns_servers') or ['?'])}")
        path = network.get("connection_path") or []
        if path:
            steps = []
            for node in path:
                ms = f" {node['ms']:.1f} ms" if node.get('ms') is not None else ""
                steps.append(f"{node['name']} [{node['status']}{ms}]")
            lines.append("- Connection path: " + " → ".join(steps))
        lines.append(f"- Detected issues: {issues.get('status', '?')}, {len(issues.get('issues', []))} issue(s)")
        for issue in issues.get("issues", []):
            lines.append(f"  - [{issue.get('severity')}] {issue.get('message')} — {issue.get('solution')}")
    for test in recent_results:
        lines.append(f"- {test['type']} · {test['target']} · {test['summary']} ({test['time']})")
    for name in extra_logs:
        lines.append(f"- Log included: {name}")
    lines += ["", "## Data (JSON)", "", "```json", json.dumps(payload, indent=2, ensure_ascii=False, default=str),
              "```", ""]

    text = "\n".join(lines)
    hostname = ((snapshot or {}).get("system") or {}).get("hostname")
    return redact(text, privacy.get("mac", True), privacy.get("public_ip", True), privacy.get("hostname", True),
                  hostname)


def default_filename():
    return f"network-diagnostics-{datetime.now():%Y%m%d-%H%M%S}.md"
