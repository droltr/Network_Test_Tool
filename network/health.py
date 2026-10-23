"""Network health scan: finds configuration problems that ping tests miss.

Typical case: a VPN client was uninstalled but left routes, DNS servers, virtual adapters
or proxy settings behind, causing drops that a DNS flush or DHCP renew temporarily fixes.

Each check returns {'id', 'title', 'status', 'summary', 'details', 'fix', 'action'} where
status is 'ok', 'info', 'warn' or 'fail', and action names a quick action the GUI can offer.
Linux checks were tested on Fedora (NetworkManager + systemd-resolved).

> **⚠️ UNVERIFIED:** the Windows and macOS branches have not been run on those systems.
> To verify: run the scan on Windows 10/11 and macOS and compare with `route print`,
> `netsh winhttp show proxy` and `scutil --dns`.
"""
import json
import os
import platform
import random
import re
import shutil
import socket
import struct
import subprocess
import time

import psutil

from network.detector import NetworkDetector
from utils.paths import command_env, console_encoding

PLATFORM = platform.system().lower()
VPN_NAME_RE = re.compile(r"^(tun|tap|wg|ppp|utun|ipsec|vpn|nordlynx|proton|mullvad|tailscale|zt|cscotun|gpd|"
                         r"wintun|openvpn|wireguard|forticlient|globalprotect|anyconnect|expressvpn|surfshark)",
                         re.IGNORECASE)
VPN_DESC_RE = re.compile(r"(tap-windows|wintun|wireguard|openvpn|vpn|fortinet|cisco anyconnect|"
                         r"juniper|pulse secure|globalprotect|nordlynx|tailscale|zerotier)", re.IGNORECASE)


def _run(command, timeout=8):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=command_env(),
                                encoding=console_encoding(), errors="replace")
        return result.returncode, result.stdout + result.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def _check(check_id, title, status, summary, details=None, fix="", action=None):
    return {"id": check_id, "title": title, "status": status, "summary": summary,
            "details": details or [], "fix": fix, "action": action}


# ------------------------------------------------------------------ DNS query

def dns_query(server, timeout=2.0):
    """Send one real DNS query to `server`, bypassing local caches.

    Asks for a random name under example.com, so the answer cannot come from a cache.
    Any reply (NOERROR or NXDOMAIN) proves the server answers. Returns (answered, ms, rcode).
    """
    query_id = random.randint(0, 0xFFFF)
    name = f"ntt{random.randint(0, 10**9)}.example.com"
    question = b"".join(bytes([len(part)]) + part.encode() for part in name.split(".")) + b"\0"
    packet = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + question + struct.pack("!HH", 1, 1)
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        start = time.perf_counter()
        try:
            sock.sendto(packet, (server, 53))
            while True:
                data, _addr = sock.recvfrom(512)
                if len(data) >= 4 and struct.unpack("!H", data[:2])[0] == query_id:
                    rcode = struct.unpack("!H", data[2:4])[0] & 0x0F
                    return True, (time.perf_counter() - start) * 1000, rcode
        except OSError:
            return False, None, None


# ------------------------------------------------------------------ data sources

def _linux_routes():
    code, out = _run(["ip", "-j", "-4", "route", "show", "table", "all"])
    try:
        return json.loads(out) if code == 0 else []
    except ValueError:
        return []


def _windows_routes():
    """IPv4 routes from `route print -4`: list of dicts with dst, mask, gateway, interface, metric."""
    code, out = _run(["route", "print", "-4"])
    routes = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 5 and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]) and re.match(r"^\d+\.", parts[1]):
            routes.append({"dst": parts[0], "mask": parts[1], "gateway": parts[2], "interface": parts[3],
                           "metric": parts[4]})
    return routes


def _interface_up(name, stats):
    st = stats.get(name)
    return bool(st and st.isup)


# ------------------------------------------------------------------ checks

def check_routes():
    stats = psutil.net_if_stats()
    details, problems = [], []
    if PLATFORM == "linux":
        routes = [r for r in _linux_routes() if r.get("table", "main") in ("main", None) or "table" not in r]
        defaults = [r for r in routes if r.get("dst") == "default"]
        splits = [r for r in routes if r.get("dst") in ("0.0.0.0/1", "128.0.0.0/1")]
        for r in defaults + splits:
            dev = r.get("dev", "?")
            down = "linkdown" in r.get("flags", []) or not _interface_up(dev, stats)
            details.append(f"{r.get('dst')} via {r.get('gateway', 'direct')} dev {dev} metric {r.get('metric', 0)}"
                           + ("  (interface down)" if down else ""))
            if down:
                problems.append(f"route {r.get('dst')} points to {dev}, which is down or missing")
        if splits:
            problems.append("0.0.0.0/1 + 128.0.0.0/1 routes override the default route; this is how VPN "
                            "clients capture traffic")
        if len({r.get("dev") for r in defaults}) > 1:
            details.append("Several default routes exist; the lowest metric wins.")
        code, out = _run(["ip", "-j", "rule"])
        try:
            rules = json.loads(out) if code == 0 else []
        except ValueError:
            rules = []
        extra = [r for r in rules if r.get("table") not in ("local", "main", "default")]
        for r in extra:
            details.append(f"policy rule {r.get('priority')}: table {r.get('table')}"
                           + (f" fwmark {r.get('fwmark')}" if r.get("fwmark") else ""))
        if extra and not any(VPN_NAME_RE.match(n) and _interface_up(n, stats) for n in stats):
            problems.append("extra routing rules exist although no VPN interface is up")
    elif PLATFORM == "windows":
        routes = _windows_routes()
        defaults = [r for r in routes if r["dst"] == "0.0.0.0" and r["mask"] == "0.0.0.0"]
        splits = [r for r in routes if (r["dst"], r["mask"]) in (("0.0.0.0", "128.0.0.0"), ("128.0.0.0", "128.0.0.0"))]
        for r in defaults + splits:
            details.append(f"{r['dst']}/{r['mask']} via {r['gateway']} if {r['interface']} metric {r['metric']}")
        if splits:
            problems.append("0.0.0.0/1 + 128.0.0.0/1 routes override the default route (VPN style)")
    else:
        code, out = _run(["netstat", "-rn", "-f", "inet"])
        details = [line for line in out.splitlines() if line.startswith(("default", "0/1", "128.0/1"))]
        if any(line.startswith(("0/1", "128.0/1")) for line in details):
            problems.append("0/1 + 128.0/1 routes override the default route (VPN style)")

    if not details:
        return _check("routes", "Routing table", "fail", "No default route: traffic cannot leave this network.",
                      [], "Renew the DHCP lease or reconnect the network.", "renew_ip")
    if problems:
        return _check("routes", "Routing table", "warn", problems[0][0].upper() + problems[0][1:] + ".",
                      details + [f"Problem: {p}" for p in problems[1:]],
                      "Disconnect or remove the leftover VPN connection; then renew the IP address. A reboot also "
                      "clears routes that a removed VPN left behind.", "renew_ip")
    return _check("routes", "Routing table", "ok", "Default route looks normal.", details)


def check_dns():
    detector = NetworkDetector()
    servers = [s for s in detector.get_dns_servers() if s != "N/A"]
    if not servers:
        return _check("dns", "DNS servers", "fail", "No DNS server is configured.", [],
                      "Renew the IP address or set DNS manually (for example 1.1.1.1 and 8.8.8.8).", "renew_ip")
    details, dead = [], []
    for server in servers[:6]:
        answered, ms, rcode = dns_query(server)
        if answered:
            details.append(f"{server}: answered in {ms:.1f} ms (rcode {rcode})")
        else:
            details.append(f"{server}: no answer within 2 s")
            dead.append(server)
    if PLATFORM == "linux" and shutil.which("resolvectl"):
        code, out = _run(["resolvectl", "dns"])
        stats = psutil.net_if_stats()
        for line in out.splitlines():
            match = re.match(r"Link \d+ \(([^)]+)\):\s*(.*)", line)
            if match and match.group(2).strip():
                iface = match.group(1)
                state = "up" if _interface_up(iface, stats) else "down"
                details.append(f"per-link DNS on {iface} ({state}): {match.group(2).strip()}")
                if state == "down" or (VPN_NAME_RE.match(iface) and state != "up"):
                    dead.append(f"servers on {iface}")
    if dead and len(dead) >= len(servers):
        return _check("dns", "DNS servers", "fail", "None of the configured DNS servers answer.", details,
                      "Flush the DNS cache and renew the IP address. If a VPN was removed, its DNS servers may still "
                      "be configured; remove them or switch to 1.1.1.1 / 8.8.8.8.", "flush_dns")
    if dead:
        return _check("dns", "DNS servers", "warn", f"Some DNS servers do not answer: {', '.join(dead)}.", details,
                      "Lookups that hit a dead server stall for seconds, which feels like short drops. Remove the "
                      "dead server (often left by a VPN) and flush the DNS cache.", "flush_dns")
    return _check("dns", "DNS servers", "ok", f"All {len(servers)} DNS server(s) answer.", details)


def check_virtual_adapters():
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    found = []
    descriptions = {}
    if PLATFORM == "windows":
        code, out = _run(["powershell", "-NoProfile", "-Command",
                          "Get-NetAdapter -IncludeHidden | Select-Object Name,InterfaceDescription,Status | "
                          "ConvertTo-Json"], timeout=15)
        try:
            data = json.loads(out) if code == 0 else []
            for item in data if isinstance(data, list) else [data]:
                descriptions[item.get("Name", "")] = item.get("InterfaceDescription", "")
        except ValueError:
            pass
    for name in stats:
        description = descriptions.get(name, "")
        if VPN_NAME_RE.match(name) or VPN_DESC_RE.search(description):
            up = stats[name].isup
            has_ip = any(a.family == socket.AF_INET for a in addrs.get(name, []))
            found.append((name, description, up, has_ip))
    if PLATFORM == "linux" and shutil.which("nmcli"):
        code, out = _run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"])
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] in ("vpn", "wireguard", "tun"):
                found.append((f"profile '{parts[0]}'", parts[1], bool(parts[2:] and parts[2]), False))
    if not found:
        return _check("adapters", "VPN and virtual adapters", "ok", "No VPN adapters or VPN profiles found.")
    details = [f"{name}{' — ' + desc if desc else ''}: {'up' if up else 'down'}"
               f"{', has an IPv4 address' if has_ip else ''}" for name, desc, up, has_ip in found]
    active = [f for f in found if f[2]]
    if active:
        return _check("adapters", "VPN and virtual adapters", "info",
                      f"{len(active)} VPN connection(s) are active; traffic may go through them.", details)
    return _check("adapters", "VPN and virtual adapters", "warn",
                  "VPN adapters or profiles are present but not connected. If you removed that VPN, these are "
                  "leftovers.", details,
                  "Delete unused VPN profiles and adapters (Linux: nmcli connection delete <name>; Windows: Device "
                  "Manager → Network adapters → uninstall the TAP/Wintun/WireGuard adapter).")


def check_proxy():
    details = []
    for var in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        if os.environ.get(var):
            details.append(f"environment {var}={os.environ[var]}")
    if PLATFORM == "linux":
        kde = os.path.expanduser("~/.config/kioslaverc")
        try:
            with open(kde, encoding="utf-8") as f:
                match = re.search(r"^ProxyType=(\d)", f.read(), re.MULTILINE)
            if match and match.group(1) != "0":
                details.append(f"KDE proxy enabled (ProxyType={match.group(1)}) in {kde}")
        except OSError:
            pass
        if shutil.which("gsettings"):
            code, out = _run(["gsettings", "get", "org.gnome.system.proxy", "mode"])
            if code == 0 and out.strip().strip("'") not in ("none", ""):
                details.append(f"GNOME proxy mode: {out.strip()}")
    elif PLATFORM == "windows":
        code, out = _run(["reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                          "/v", "ProxyEnable"])
        if re.search(r"ProxyEnable\s+REG_DWORD\s+0x1", out):
            details.append("Windows (WinINET) proxy is enabled for this user")
        code, out = _run(["netsh", "winhttp", "show", "proxy"])
        if code == 0 and "Direct access" not in out:
            details.append("WinHTTP proxy: " + " ".join(out.split())[:160])
    if details:
        return _check("proxy", "Proxy settings", "warn", "A proxy is configured. If it is unreachable, web traffic "
                      "fails while ping still works.", details,
                      "Turn the proxy off in system settings if you did not set it up on purpose.")
    return _check("proxy", "Proxy settings", "ok", "No system proxy is configured.")


def check_mtu(target="8.8.8.8"):
    """Detect MTU black holes: large DF packets dropped silently instead of being reported."""
    def probe(payload):
        if PLATFORM == "windows":
            cmd = ["ping", "-n", "1", "-w", "1500", "-f", "-l", str(payload), target]
        elif PLATFORM == "darwin":
            cmd = ["ping", "-c", "1", "-t", "2", "-D", "-s", str(payload), target]
        else:
            cmd = ["ping", "-c", "1", "-W", "2", "-M", "do", "-s", str(payload), target]
        code, out = _run(cmd, timeout=5)
        too_big = bool(re.search(r"(too long|needs to be fragmented|frag needed|mtu)", out, re.IGNORECASE))
        return code == 0, too_big

    small_ok, _ = probe(56)
    if not small_ok:
        return _check("mtu", "Packet size (MTU)", "info", f"Skipped: {target} does not answer ping.")
    ok, reported = probe(1472)
    if ok:
        return _check("mtu", "Packet size (MTU)", "ok", "Full-size 1500-byte packets reach the internet.")
    low, high = 1200, 1472
    while low < high:
        middle = (low + high + 1) // 2
        if probe(middle)[0]:
            low = middle
        else:
            high = middle - 1
    path_mtu = low + 28
    if reported:
        return _check("mtu", "Packet size (MTU)", "info",
                      f"Path MTU is {path_mtu} bytes and the network reports it correctly.",
                      [f"Largest unfragmented ping payload: {low} bytes",
                       "1492 is normal for PPPoE connections."])
    return _check("mtu", "Packet size (MTU)", "warn",
                  f"Packets above {path_mtu} bytes are dropped silently (MTU black hole).",
                  [f"Largest unfragmented ping payload: {low} bytes"],
                  "Some sites will hang or load partially. Lower the interface MTU to "
                  f"{path_mtu} or fix the router or VPN that drops the 'fragmentation needed' messages.")


def check_ipv6():
    """A default IPv6 route without working IPv6 makes many connections wait before falling back."""
    has_route = False
    if PLATFORM == "linux":
        code, out = _run(["ip", "-j", "-6", "route", "show", "default"])
        has_route = code == 0 and out.strip() not in ("", "[]")
    if not has_route:
        return _check("ipv6", "IPv6 connectivity", "ok", "No IPv6 default route; IPv4 is used.")
    try:
        with socket.create_connection(("2001:4860:4860::8888", 53), timeout=3):
            pass
        return _check("ipv6", "IPv6 connectivity", "ok", "IPv6 works.")
    except OSError as e:
        return _check("ipv6", "IPv6 connectivity", "warn",
                      "An IPv6 route exists but IPv6 does not reach the internet.", [str(e)],
                      "Connections may stall before falling back to IPv4. Fix IPv6 on the router or disable it on "
                      "this connection.")


def check_resolv_conf():
    if PLATFORM != "linux":
        return None
    path = "/etc/resolv.conf"
    try:
        target = os.path.realpath(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return _check("resolvconf", "resolv.conf", "warn", f"Cannot read {path}: {e}")
    managed = "systemd/resolve" in target or "NetworkManager" in text or "systemd-resolved" in text
    vpn_marks = [line for line in text.splitlines() if re.search(r"vpn|openvpn|wireguard|wg-quick", line, re.I)]
    details = [f"{path} -> {target}"] + vpn_marks[:3]
    if vpn_marks:
        return _check("resolvconf", "resolv.conf", "warn", "resolv.conf was written by a VPN tool.", details,
                      "Restore it: sudo ln -sf ../run/systemd/resolve/stub-resolv.conf /etc/resolv.conf, then "
                      "restart NetworkManager.")
    if not managed:
        return _check("resolvconf", "resolv.conf", "info", "resolv.conf is a static file, not managed by the "
                      "network service.", details)
    return _check("resolvconf", "resolv.conf", "ok", "Managed by the system resolver.", details)


def check_windows_winsock():
    if PLATFORM != "windows":
        return None
    code, out = _run(["netsh", "winsock", "show", "catalog"], timeout=15)
    providers = set(re.findall(r"Provider Path:\s*(.+)", out))
    third_party = [p for p in providers if "system32" not in p.lower() and "syswow64" not in p.lower()]
    if third_party:
        return _check("winsock", "Winsock catalog", "warn", "Non-Windows network providers are installed in "
                      "Winsock (often left by VPN or security software).", sorted(third_party),
                      "Run 'netsh winsock reset' as administrator and restart.")
    return _check("winsock", "Winsock catalog", "ok", "Only Windows providers are registered.")


CHECKS = [
    ("routes", "Routing table", check_routes),
    ("dns", "DNS servers", check_dns),
    ("adapters", "VPN and virtual adapters", check_virtual_adapters),
    ("proxy", "Proxy settings", check_proxy),
    ("mtu", "Packet size (MTU)", check_mtu),
    ("ipv6", "IPv6 connectivity", check_ipv6),
    ("resolvconf", "resolv.conf", check_resolv_conf),
    ("winsock", "Winsock catalog", check_windows_winsock),
]


def run_scan(progress_callback=None):
    """Run every check for this OS; progress_callback(check_id, result_or_None) before/after each."""
    results = []
    for check_id, title, func in CHECKS:
        if progress_callback:
            progress_callback(check_id, None)
        try:
            result = func()
        except Exception as e:   # one broken check must not stop the scan
            result = _check(check_id, title, "info", f"Check could not run: {e}")
        if result is None:
            continue
        results.append(result)
        if progress_callback:
            progress_callback(check_id, result)
    return results


def scan_as_text(results):
    lines = ["Network health scan"]
    for r in results:
        lines.append(f"[{r['status'].upper()}] {r['title']}: {r['summary']}")
        lines += [f"    {d}" for d in r["details"]]
        if r["fix"]:
            lines.append(f"    Fix: {r['fix']}")
    return "\n".join(lines)
