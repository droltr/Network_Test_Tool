"""Game connection: find the Counter-Strike 2 server (a Valve SDR relay) the game talks to and
localize packet loss on the path to it (home network, internet provider, transit, Valve).

Steps:
- fetch_relays() downloads Valve's relay list (SDR config) and caches it in the state directory.
- find_game_process() finds cs2.exe and the local UDP ports it owns.
- capture_game_peers() runs a short, elevated, header-only pktmon capture and returns the remote
  addresses the game's ports exchanged packets with (UDP has no remote address in the socket table).
- scan_relays() pings one address of every relay site to compare them.
- PathDiagnosis traces the route to a relay and pings every responding hop each second;
  localize_loss() turns the per-hop loss into a zone.

Loss that appears at a router but not at the hops after it is not real loss: routers answer ICMP
in a low-priority path and rate-limit it. Only loss that starts at a hop and persists to the
destination counts.

Anti-cheat safety (binding; the app must never look like a cheat to Valve Anti-Cheat):
1. The game process is never opened. It is found by name in the system process snapshot
   (psutil.process_iter with "pid" and "name"), its UDP ports come from the system-wide UDP table
   (psutil.net_connections, GetExtendedUdpTable) filtered by pid. No process handle, no memory
   access, no injection or hooking, no command line queries.
2. Game files, configs, launch options, Steam files and the game's console or logs are never read
   or written.
3. No packet is ever sent to the game server's game port, and game traffic is never spoofed,
   injected, modified, blocked or delayed (no firewall rules, no QoS changes). The only probes are
   ICMP echo requests to relays and routers and traceroute. The capture is passive (pktmon at the
   NDIS layer, filtered to UDP, 96-byte headers only) and never alters traffic.
4. Probe rates stay modest: by default at most one probe per second per target.
"""
import ctypes
import ipaddress
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime

import psutil

from network.monitor import _percentile
from network.ping import ping_reply
from network.trace import TraceRoute
from utils import winnet
from utils.paths import run_command, state_dir

SDR_CONFIG_URL = "https://api.steampowered.com/ISteamApps/GetSDRConfig/v1/?appid=730"
SDR_CACHE_NAME = "valve-sdr-config.json"
GAME_PROCESS_NAMES = ("cs2.exe", "cs2")
BURST_GAP_S = 0.003          # packets closer than this belong to one server tick (one burst)
LATE_GAP_MS = 40             # a gap between bursts longer than this is a visible hitch at 64 tick
TRACE_GIVE_UP_TIMEOUTS = 6   # consecutive silent hops after which the trace is stopped
MAX_DIAGNOSIS_S = 3600       # longest path diagnosis; bounds the kept history (3600 rounds x hops)
CGNAT = ipaddress.ip_network("100.64.0.0/10")
ERROR_CANCELLED = 1223       # the user declined the UAC prompt

MIN_TARGET_PROBES = 10       # fewer probes to the target say nothing about its loss
ZONE_LABELS = {"none": "No loss", "home": "Home network", "isp": "Internet provider",
               "transit": "Transit network", "server": "Valve server", "inconclusive": "Inconclusive"}


class GameServerError(Exception):
    """An error whose message can be shown to the user as is."""


def _cancelled(cancel):
    """cancel is None, a threading.Event (or anything with is_set) or a callable returning bool."""
    if cancel is None:
        return False
    if hasattr(cancel, "is_set"):
        return cancel.is_set()
    return bool(cancel())


def _is_private(ip):
    """Private, loopback, link-local or carrier-grade NAT (100.64.0.0/10) address."""
    try:
        address = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return False
    if address.version == 4 and address in CGNAT:
        return True
    return address.is_private or address.is_loopback or address.is_link_local


def _same_prefix(a, b, prefix):
    try:
        return (ipaddress.ip_network(f"{a}/{prefix}", strict=False)
                == ipaddress.ip_network(f"{b}/{prefix}", strict=False))
    except (ValueError, TypeError):
        return False


def ping_ms(ip, timeout=1.0):
    """One ICMP echo: round-trip time in ms or None. Uses IcmpSendEcho on Windows (no ping.exe per
    probe, status codes instead of translated text); "<1 ms" counts as 0.5 ms like the ping parser."""
    try:
        echo = winnet.icmp_echo(ip, timeout_ms=int(timeout * 1000))
    except OSError:
        echo = None
    if echo is not None:
        status, rtt = echo
        if status != winnet.IP_SUCCESS or rtt is None:
            return None
        return rtt if rtt > 0 else 0.5
    reply = ping_reply(ip, timeout)
    return reply[0] if reply else None


def _series_stats(times, sent, lost):
    """Loss and latency figures of one target (same fields as the monitor's session report)."""
    jitter = (sum(abs(a - b) for a, b in zip(times, times[1:])) / (len(times) - 1)) if len(times) > 1 else None

    def r(value):
        return round(value, 2) if value is not None else None
    return {"sent": sent, "lost": lost, "loss_percent": round(100 * lost / sent, 2) if sent else 0.0,
            "min_ms": r(min(times)) if times else None,
            "avg_ms": r(sum(times) / len(times)) if times else None,
            "p95_ms": r(_percentile(times, 0.95)) if times else None,
            "max_ms": r(max(times)) if times else None,
            "jitter_ms": r(jitter)}


# ---------------------------------------------------------------------------- Valve relays

def parse_sdr_config(data):
    """Relay sites from a GetSDRConfig response: [{'pop', 'desc', 'ips'}], sorted by description.
    Sites without relays (Valve's internal ones) are left out."""
    pops = (data or {}).get("pops") if isinstance(data, dict) else None
    if not isinstance(pops, dict):
        raise GameServerError("The Valve relay list has an unexpected format.")
    relays = []
    for pop, info in pops.items():
        if not isinstance(info, dict):
            continue
        ips = []
        for relay in info.get("relays") or []:
            ip = relay.get("ipv4") if isinstance(relay, dict) else None
            if ip and ip not in ips:
                ips.append(ip)
        if ips:
            relays.append({"pop": pop, "desc": info.get("desc") or pop, "ips": ips})
    relays.sort(key=lambda r: (r["desc"].lower(), r["pop"]))
    return relays


def _sdr_cache_path():
    return os.path.join(state_dir(), SDR_CACHE_NAME)


def fetch_relays(timeout=10):
    """Valve's current relay list; falls back to the cached copy when the download fails."""
    error = None
    try:
        request = urllib.request.Request(SDR_CONFIG_URL, headers={"User-Agent": "network-test-tool"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        relays = parse_sdr_config(data)
        if not relays:
            raise GameServerError("The Valve relay list is empty.")
        try:
            with open(_sdr_cache_path(), "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError as e:
            logging.debug(f"Cannot cache the Valve relay list: {e}")
        return relays
    except (OSError, ValueError, GameServerError) as e:
        error = e
        logging.info(f"Valve relay list download failed, using the cache: {e}")
    try:
        with open(_sdr_cache_path(), encoding="utf-8") as f:
            relays = parse_sdr_config(json.load(f))
        if relays:
            return relays
    except (OSError, ValueError, GameServerError):
        pass
    raise GameServerError(f"Cannot download Valve's relay list and no saved copy exists ({error}). "
                          "Check the internet connection and try again.")


def find_relay(ip, relays):
    """The relay site that owns ip; else one with an address in the same /24; else None."""
    for relay in relays or []:
        if ip in relay["ips"]:
            return relay
    for relay in relays or []:
        if any(_same_prefix(ip, other, 24) for other in relay["ips"]):
            return relay
    return None


# ---------------------------------------------------------------------------- game process

def find_game_process(names=GAME_PROCESS_NAMES):
    """{'pid', 'name', 'udp_ports'} of the running game, or None.

    Only system-wide snapshots are read (process list and UDP table); the game process itself is
    never opened (see "Anti-cheat safety" above). With several matches the one owning the most UDP
    ports wins."""
    wanted = {n.lower() for n in names}
    candidates = {}
    for proc in psutil.process_iter(["pid", "name"]):
        name = (proc.info.get("name") or "")
        if name.lower() in wanted:
            candidates[proc.info["pid"]] = name
    if not candidates:
        return None
    ports = {pid: set() for pid in candidates}
    try:
        for conn in psutil.net_connections(kind="udp"):
            if conn.pid in ports and conn.laddr:
                ports[conn.pid].add(conn.laddr.port)
    except (psutil.Error, OSError) as e:
        logging.debug(f"UDP table unavailable: {e}")
    pid = max(candidates, key=lambda p: len(ports[p]))
    return {"pid": pid, "name": candidates[pid], "udp_ports": sorted(ports[pid])}


# ---------------------------------------------------------------------------- packet capture

# Header line of one logged packet and the tab-indented line after it (pktmon etl2txt)
_PKT_HEADER_RE = re.compile(
    r"::(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:\.(\d+))?\s.*?\bPktGroupId\s+(\d+),.*?"
    r"\bDirection\s+(\w+)\s*,.*?\bComponent\s+(\d+),\s*Edge\s+(\d+)")
_PKT_UDP_RE = re.compile(
    r"(\d+\.\d+\.\d+\.\d+)\.(\d+)\s*>\s*(\d+\.\d+\.\d+\.\d+)\.(\d+):\s*UDP\b")


def _pkt_time(stamp, fraction):
    when = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").timestamp()
    return when + (float("0." + fraction) if fraction else 0.0)


def parse_pktmon_text(text, local_ports):
    """Parse `pktmon etl2txt` output.

    Returns (peers, rx_times, tx_times): peers is [{'ip', 'port', 'rx', 'tx'}] sorted by packet
    count, rx_times and tx_times the packet times (epoch seconds, sorted) to and from the top peer.

    pktmon logs a packet once at every component and edge it passes (NIC, filter drivers, ...),
    each time with a new PktGroupId, so packets cannot be deduplicated by id. Each flow direction
    is counted only at the (component, edge) where it was seen first.
    A packet belongs to the game when its local side uses one of local_ports; with no ports given,
    the Direction field decides which side is local.
    """
    ports = set(local_ports or ())
    first_point = {}     # (peer ip, peer port, local port, direction) -> (component, edge)
    counts = {}          # (ip, port) -> {'rx', 'tx'}
    times = {}           # (ip, port, direction) -> [epoch seconds]
    header = None
    for line in text.splitlines():
        if not line.startswith(("\t", " ")):
            match = _PKT_HEADER_RE.search(line)
            header = match.groups() if match else None
            continue
        if header is None:
            continue
        match = _PKT_UDP_RE.search(line)
        current, header = header, None
        if not match:
            continue
        stamp, fraction, _group, direction, component, edge = current
        src, sport, dst, dport = match.group(1), int(match.group(2)), match.group(3), int(match.group(4))
        direction = direction.lower()
        if ports:
            if dport in ports and (direction == "rx" or sport not in ports):
                kind, peer, local = "rx", (src, sport), dport
            elif sport in ports:
                kind, peer, local = "tx", (dst, dport), sport
            else:
                continue
        elif direction == "rx":
            kind, peer, local = "rx", (src, sport), dport
        elif direction == "tx":
            kind, peer, local = "tx", (dst, dport), sport
        else:
            continue
        flow = (peer[0], peer[1], local, kind)
        point = (component, edge)
        if first_point.setdefault(flow, point) != point:
            continue   # the same packet seen again further along the stack
        counts.setdefault(peer, {"rx": 0, "tx": 0})[kind] += 1
        times.setdefault((peer[0], peer[1], kind), []).append(_pkt_time(stamp, fraction))
    peers = [{"ip": ip, "port": port, "rx": c["rx"], "tx": c["tx"]} for (ip, port), c in counts.items()]
    peers.sort(key=lambda p: (-(p["rx"] + p["tx"]), p["ip"], p["port"]))
    if not peers:
        return peers, [], []
    top = (peers[0]["ip"], peers[0]["port"])
    return (peers, sorted(times.get((*top, "rx"), [])), sorted(times.get((*top, "tx"), [])))


def stream_stats(times, tick_rate=64):
    """Regularity of a packet stream. Packets less than 3 ms apart form one burst (one server tick
    can be sent as several packets); a healthy 64-tick stream has ~64 bursts per second and no gap
    much longer than 1/64 s."""
    ordered = sorted(times or [])
    stats = {"packets": len(ordered), "bursts_per_s": None, "expected_per_s": tick_rate,
             "median_gap_ms": None, "max_gap_ms": None, "gaps_over_40ms": 0}
    if not ordered:
        return stats
    bursts = [ordered[0]]
    for previous, current in zip(ordered, ordered[1:]):
        if current - previous >= BURST_GAP_S:
            bursts.append(current)
    gaps = [(b - a) * 1000 for a, b in zip(bursts, bursts[1:])]
    span = bursts[-1] - bursts[0]
    if span > 0:
        stats["bursts_per_s"] = round((len(bursts) - 1) / span, 1)
    if gaps:
        ordered_gaps = sorted(gaps)
        middle = len(ordered_gaps) // 2
        median = ordered_gaps[middle] if len(ordered_gaps) % 2 else (ordered_gaps[middle - 1] + ordered_gaps[middle]) / 2
        stats.update(median_gap_ms=round(median, 1), max_gap_ms=round(max(gaps), 1),
                     gaps_over_40ms=sum(1 for g in gaps if g > LATE_GAP_MS))
    return stats


def _ps_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


CAPTURE_BUSY_MESSAGE = "Another packet capture (pktmon) is already in use; stop it and try again."


def build_capture_script(etl_path, txt_path, cancel_path, status_path, seconds):
    """PowerShell script of the elevated capture.

    It first makes sure pktmon is unused: no running PktMon trace session and no packet filters
    (pktmon has one global filter list and one capture, so another user's setup must not be touched);
    otherwise it writes 'busy' to status_path and changes nothing. pktmon's messages are translated,
    so the checks use exit codes and the layout of `pktmon filter list` (a dashed column-header
    underline and numbered rows), not words. Only what this script set up is undone: the capture is
    stopped only if our start succeeded, the filters are removed only if our filter was added, also
    when the script fails or is cancelled (cancel_path appears). The result ('ok', 'cancelled',
    'busy' or 'error: ...') goes to status_path.
    """
    seconds = max(1, int(seconds))
    return f"""# Network Test Tool: passive, header-only UDP capture for the Game connection page.
# Leaves pktmon alone if it is already in use; undoes only what it set up itself.
$ErrorActionPreference = 'Continue'
$etl = {_ps_quote(etl_path)}
$txt = {_ps_quote(txt_path)}
$cancel = {_ps_quote(cancel_path)}
$status = {_ps_quote(status_path)}
$result = 'error'
$filterAdded = $false
$started = $false
try {{
    # A running capture is an ETW session named PktMon: logman exits 0 when it exists
    logman query PktMon -ets | Out-Null
    if ($LASTEXITCODE -eq 0) {{ $result = 'busy'; throw 'busy' }}
    $filters = pktmon filter list 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {{ throw "pktmon filter list failed with exit code $LASTEXITCODE" }}
    # Existing filters are listed as a table: a dashed header underline and numbered rows
    if ($filters -match '(?m)^\\s*-+(\\s+-+)+\\s*$' -or $filters -match '(?m)^\\s*\\d+\\s+\\S') {{
        $result = 'busy'; throw 'busy'
    }}
    pktmon filter add NetworkTestToolGame -t UDP | Out-Null
    if ($LASTEXITCODE -ne 0) {{ throw "pktmon filter add failed with exit code $LASTEXITCODE" }}
    $filterAdded = $true
    pktmon start --capture --pkt-size 96 --file-name $etl | Out-Null
    if ($LASTEXITCODE -ne 0) {{ throw "pktmon start failed with exit code $LASTEXITCODE" }}
    $started = $true
    $deadline = (Get-Date).AddSeconds({seconds})
    $result = 'ok'
    while ((Get-Date) -lt $deadline) {{
        if (Test-Path -LiteralPath $cancel) {{ $result = 'cancelled'; break }}
        Start-Sleep -Milliseconds 250
    }}
}} catch {{
    if ($result -ne 'busy') {{ $result = 'error: ' + $_.Exception.Message }}
}} finally {{
    if ($started) {{ pktmon stop | Out-Null }}
    # There were no filters before ours, so removing all removes only ours
    if ($filterAdded) {{ pktmon filter remove | Out-Null }}
}}
if ($result -eq 'ok') {{
    pktmon etl2txt $etl --out $txt | Out-Null
    if ($LASTEXITCODE -ne 0) {{ $result = "error: pktmon etl2txt failed with exit code $LASTEXITCODE" }}
}}
Set-Content -LiteralPath $status -Value $result -Encoding UTF8
"""


class _ShellExecuteInfo(ctypes.Structure):
    """SHELLEXECUTEINFOW (shellapi.h)."""
    _fields_ = [("cbSize", ctypes.c_uint32), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
                ("lpVerb", ctypes.c_wchar_p), ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
                ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
                ("lpIDList", ctypes.c_void_p), ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                ("dwHotKey", ctypes.c_uint32), ("hIconOrMonitor", ctypes.c_void_p), ("hProcess", ctypes.c_void_p)]


SEE_MASK_NOCLOSEPROCESS = 0x40
SEE_MASK_NO_CONSOLE = 0x8000
SW_HIDE = 0
WAIT_TIMEOUT = 0x102


def is_elevated():
    if not sys.platform.startswith("win"):
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def powershell_parameters(script_path):
    """Command line arguments of powershell.exe for running script_path, quoted by the C runtime rules."""
    return subprocess.list2cmdline(["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                    "-WindowStyle", "Hidden", "-File", script_path])


def _run_powershell_script(script_path, timeout, cancel=None, cancel_path=None):
    """Run a .ps1 hidden, with the UAC prompt unless this process is already elevated, and wait for it.
    Only our own PowerShell child is ever opened here."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    info.lpVerb = None if is_elevated() else "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = powershell_parameters(script_path)
    info.nShow = SW_HIDE
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == ERROR_CANCELLED:
            raise GameServerError("Administrator permission was declined. The capture needs it to see which "
                                  "server the game talks to.")
        raise GameServerError(f"Cannot start the capture (Windows error {error}).")
    if not info.hProcess:
        raise GameServerError("Cannot start the capture (no process handle).")
    try:
        deadline = time.monotonic() + timeout
        cancel_sent = False
        while True:
            if kernel32.WaitForSingleObject(info.hProcess, 250) != WAIT_TIMEOUT:
                break
            if not cancel_sent and (_cancelled(cancel) or time.monotonic() > deadline):
                # The script polls for this file and then stops pktmon itself
                try:
                    with open(cancel_path, "w") as f:
                        f.write("cancel")
                except OSError:
                    pass
                cancel_sent = True
                deadline = time.monotonic() + 30
            elif cancel_sent and time.monotonic() > deadline:
                raise GameServerError("The capture did not finish in time. Run 'pktmon stop' in an administrator "
                                      "terminal if a capture is still running.")
        code = ctypes.c_uint32(0)
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return code.value
    finally:
        kernel32.CloseHandle(info.hProcess)


def capture_game_peers(ports, seconds=10, cancel=None, debug=False, tick_rate=64):
    """Capture UDP headers for `seconds` and return the remote peers of the game's local ports.

    Returns {'peers', 'stream' (inbound stream of the top peer), 'stream_tx', 'started', 'seconds'}.
    Windows only; needs administrator rights (asks with UAC). With debug the .etl/.txt are kept in
    the state directory and their paths returned under 'files'.
    """
    if not sys.platform.startswith("win"):
        raise GameServerError("Finding the game server needs Windows (pktmon).")
    seconds = max(1, int(seconds))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = state_dir()
    base = os.path.join(folder, f"game-capture-{stamp}")
    paths = {"script": base + ".ps1", "etl": base + ".etl", "txt": base + ".txt",
             "cancel": base + ".cancel", "status": base + ".status"}
    started = datetime.now()
    try:
        with open(paths["script"], "w", encoding="utf-8-sig") as f:
            f.write(build_capture_script(paths["etl"], paths["txt"], paths["cancel"], paths["status"], seconds))
        _run_powershell_script(paths["script"], seconds + 60, cancel, paths["cancel"])
        try:
            with open(paths["status"], encoding="utf-8-sig") as f:
                status = f.read().strip()
        except OSError:
            status = "error: the capture script did not report a result"
        if status == "busy":
            raise GameServerError(CAPTURE_BUSY_MESSAGE)
        if status == "cancelled" or _cancelled(cancel):
            raise GameServerError("The capture was cancelled.")
        if status != "ok":
            raise GameServerError(f"The capture failed ({status.removeprefix('error: ')}).")
        try:
            with open(paths["txt"], "rb") as f:
                raw = f.read()
        except OSError as e:
            raise GameServerError(f"Cannot read the capture output ({e}).")
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
        peers, rx_times, tx_times = parse_pktmon_text(text, ports)
        result = {"peers": peers, "stream": stream_stats(rx_times, tick_rate),
                  "stream_tx": stream_stats(tx_times, tick_rate),
                  "started": started.isoformat(timespec="seconds"), "seconds": seconds}
        if debug:
            result["files"] = {"etl": paths["etl"], "txt": paths["txt"]}
        return result
    finally:
        keep = ("etl", "txt") if debug else ()
        for key, path in paths.items():
            if key not in keep:
                try:
                    os.remove(path)
                except OSError:
                    pass


# ---------------------------------------------------------------------------- relay scan

def scan_relays(relays, seconds=20, interval=1.0, callback=None, cancel=None):
    """Ping the first address of every relay site once per interval for `seconds`, all sites in parallel.
    Returns [{'pop', 'desc', 'ip', 'sent', 'lost', 'loss_percent', 'avg_ms', 'p95_ms', 'jitter_ms'}]
    sorted by loss, then average latency. callback(fraction) reports progress after every round."""
    targets = [(r["pop"], r["desc"], r["ips"][0]) for r in relays or [] if r.get("ips")]
    if not targets:
        return []
    interval = max(0.5, float(interval))
    rounds = max(1, int(round(seconds / interval)))
    samples = {ip: [] for _pop, _desc, ip in targets}
    timeout = min(1.0, interval)
    with ThreadPoolExecutor(max_workers=min(64, len(targets))) as pool:
        for index in range(rounds):
            if _cancelled(cancel):
                break
            tick = time.monotonic()
            futures = {pool.submit(ping_ms, ip, timeout): ip for _pop, _desc, ip in targets}
            for future, ip in futures.items():
                samples[ip].append(future.result())
            if callback:
                callback((index + 1) / rounds)
            if index + 1 < rounds:
                remaining = interval - (time.monotonic() - tick)
                while remaining > 0 and not _cancelled(cancel):
                    time.sleep(min(0.1, remaining))
                    remaining = interval - (time.monotonic() - tick)
    results = []
    for pop, desc, ip in targets:
        series = samples[ip]
        times = [ms for ms in series if ms is not None]
        stats = _series_stats(times, len(series), len(series) - len(times))
        results.append({"pop": pop, "desc": desc, "ip": ip, "sent": stats["sent"], "lost": stats["lost"],
                        "loss_percent": stats["loss_percent"], "avg_ms": stats["avg_ms"],
                        "p95_ms": stats["p95_ms"], "jitter_ms": stats["jitter_ms"]})
    results.sort(key=lambda r: (r["loss_percent"], r["avg_ms"] if r["avg_ms"] is not None else float("inf")))
    return results


# ---------------------------------------------------------------------------- ASN lookup

_asn_cache = {}
_asn_lock = threading.Lock()
_TXT_RE = re.compile(r'"([^"]*)"')


def _txt_records(name):
    try:
        result = run_command(["nslookup", "-q=TXT", name], timeout=8)
    except (OSError, subprocess.SubprocessError):
        return []
    return _TXT_RE.findall(result.stdout or "")


def lookup_asn(ip):
    """{'asn', 'owner'} of a public IPv4 address from Team Cymru's DNS service, or None
    (private/CGNAT addresses, lookup failures). Successful lookups are cached."""
    try:
        address = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return None
    if address.version != 4 or _is_private(ip):
        return None
    with _asn_lock:
        if ip in _asn_cache:
            return _asn_cache[ip]
    origin_name = ".".join(reversed(ip.split("."))) + ".origin.asn.cymru.com"
    origin = None
    for _attempt in range(2):   # one retry: parallel lookups occasionally get no answer
        origin = next((r for r in _txt_records(origin_name) if "|" in r), None)
        if origin:
            break
    if not origin:
        return None
    asn = origin.split("|")[0].split()[0].strip() if origin.split("|")[0].split() else ""
    if not asn.isdigit():
        return None
    owner = ""
    name = next((r for r in _txt_records(f"AS{asn}.asn.cymru.com") if "|" in r), None)
    if name:
        owner = name.split("|")[-1].strip()
    result = {"asn": asn, "owner": owner}
    with _asn_lock:
        _asn_cache[ip] = result
    return result


# ---------------------------------------------------------------------------- loss localization

def localize_loss(hops, target_loss_threshold=1.0, min_probes=MIN_TARGET_PROBES):
    """Where on the path the loss to the target starts.

    hops: [{'index', 'address', 'loss_percent', 'asn' (optional), 'gateway' / 'is_target' (optional)}]
    in path order; hops without an address or without probes are ignored. The target is the hop
    marked is_target, else the last responsive one.
    Returns {'zone': 'none'|'home'|'isp'|'transit'|'server'|'inconclusive', 'hop': index or None,
    'summary'}.
    Loss counts only from the earliest hop where it starts and then persists at every later
    responsive hop, so a router that merely deprioritizes ICMP does not count.
    The result is "inconclusive" when the target got fewer than min_probes probes, answered none of
    them (a relay or path that filters ICMP looks exactly like total loss), or, with loss, when no
    hop before the target answered (nothing to compare with).
    """
    def inconclusive(summary):
        return {"zone": "inconclusive", "hop": None, "summary": summary}

    responsive = [h for h in hops or [] if h.get("address") and h.get("sent", 1)]
    if not responsive:
        return inconclusive("No hop answered, so the loss cannot be located.")
    target = next((h for h in reversed(responsive) if h.get("is_target")), responsive[-1])
    sent = target.get("sent")
    if sent is not None and sent < min_probes:
        return inconclusive(f"Only {sent} probe(s) reached the measurement; at least {min_probes} are needed to "
                            "judge packet loss. Run the diagnosis longer.")
    if sent and (target.get("lost") or 0) >= sent:
        return inconclusive("The server does not answer pings, so loss cannot be located; use Detect server's "
                            "game-stream stats instead.")
    # A router that answered the trace but never answers ping (lost == sent) tells nothing
    responsive = [h for h in responsive[:responsive.index(target) + 1]
                  if h is target or not h.get("sent") or (h.get("lost") or 0) < h["sent"]]
    target_loss = target.get("loss_percent") or 0.0
    if target_loss < target_loss_threshold:
        return {"zone": "none", "hop": None,
                "summary": f"No notable packet loss to the server ({target_loss:.1f}%)."}
    if len(responsive) < 2:
        return inconclusive(f"{target_loss:.1f}% of packets to the server are lost, but no router on the way "
                            "answered pings, so the loss cannot be located.")

    level = max(target_loss_threshold, 0.5 * target_loss)
    start = target
    for i, hop in enumerate(responsive):
        if all((h.get("loss_percent") or 0.0) >= level for h in responsive[i:]):
            start = hop
            break

    first_public = next((i for i, h in enumerate(responsive) if not _is_private(h["address"])), None)
    isp_asn = responsive[first_public].get("asn") if first_public is not None else None
    target_asn = target.get("asn")
    position = responsive.index(start)
    address = start["address"]
    loss_text = f"{target_loss:.1f}% of packets to the server are lost"
    where = f"hop {start.get('index')} ({address})"
    have_asn = any(h.get("asn") for h in responsive)

    if start.get("gateway") or start.get("index") == 1 or position == 0:
        zone, summary = "home", (f"{loss_text}, starting at your router ({address}): the problem is in your home "
                                 "network (cable, Wi-Fi, network adapter or router).")
    elif start is target:
        zone, summary = "server", (f"{loss_text}, and the loss appears only at the server itself: the problem is "
                                   "at Valve's relay or on its link.")
    elif isp_asn and start.get("asn") == isp_asn and isp_asn != target_asn:
        zone, summary = "isp", (f"{loss_text}, starting at {where} inside your internet provider's network "
                                f"(AS{isp_asn}{', ' + start['owner'] if start.get('owner') else ''}).")
    elif (target_asn and start.get("asn") == target_asn) or _same_prefix(address, target["address"], 16):
        zone, summary = "server", (f"{loss_text}, starting at {where} inside Valve's network: the problem is on "
                                   "Valve's side.")
    elif _is_private(address) and (first_public is None or position < first_public):
        zone, summary = "isp", (f"{loss_text}, starting at {where}, a private address behind your router: "
                                "the problem is in your internet provider's network.")
    elif start.get("asn"):
        zone, summary = "transit", (f"{loss_text}, starting at {where} in a transit network between your provider "
                                    f"and Valve (AS{start['asn']}{', ' + start['owner'] if start.get('owner') else ''}).")
    elif have_asn:
        zone, summary = "transit", (f"{loss_text}, starting at {where} between your provider and Valve; the owner "
                                    "of that router is unknown.")
    else:
        zone, summary = "transit", (f"{loss_text}, starting at {where}. Network ownership is unknown, so it is "
                                    "probably a transit network between your provider and Valve.")
    return {"zone": zone, "hop": start.get("index"), "summary": summary}


# ---------------------------------------------------------------------------- path diagnosis

class PathDiagnosis:
    """Trace the route to target, then ping the gateway, every responding hop and the target once
    per interval for `duration` seconds (all in parallel). run() blocks; stop() ends it early.

    callback(dict) receives {'phase': 'trace', 'hops': [...]} after the trace and
    {'phase': 'probe', 'elapsed', 'hops': [...]} after every round. Set `relay` (a relay dict) to
    have it in the report.

    compare: optional comparison targets (IP strings or {'address', 'label'} dicts, e.g. another
    relay) that are pinged in the same rounds; they appear in the report but not in the verdict.
    Every round is kept (time and per-target result) for the report's loss strips; 10 minutes of
    30 hops is a few hundred kB.
    """

    def __init__(self, target, duration=120, interval=1.0, callback=None, compare=None):
        self.target = target
        self.duration = min(MAX_DIAGNOSIS_S, max(1.0, float(duration)))
        self.interval = max(0.5, float(interval))   # at most 2 probes per second per hop
        self.callback = callback or (lambda data: None)
        self.relay = None
        self.started = None
        self.ended = None
        self.probe_elapsed = 0.0
        self.hops = []           # {'index', 'address', 'gateway', 'is_target', 'trace_ms', 'asn', 'owner'}
        self._samples = {}       # hop list position -> [ms or None], one per round
        self.compare = [c if isinstance(c, dict) else {"address": c, "label": c} for c in compare or ()]
        self._compare_samples = [[] for _c in self.compare]
        self.round_times = []    # datetime of every completed round
        self.events = []         # {'time', 'end' (optional), 'tone', 'text'}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._tracer = TraceRoute()
        self.error = None

    def _event(self, text, tone="neutral", when=None):
        self.events.append({"time": (when or datetime.now()).isoformat(timespec="seconds"), "end": None,
                            "tone": tone, "text": text})

    def stop(self):
        self._stop.set()
        self._tracer.stop()

    def _gateway(self):
        try:
            from network.detector import NetworkDetector
            gateways = [g for g in NetworkDetector().get_default_gateway() if g not in ("N/A", "0.0.0.0")]
            return next((g for g in gateways if "." in g), None)
        except Exception as e:   # the diagnosis works without it
            logging.debug(f"gateway lookup failed: {e}")
            return None

    def _trace(self):
        try:
            target_ip = socket.gethostbyname(self.target)
        except (OSError, UnicodeError):
            raise GameServerError(f"Cannot resolve {self.target}.")
        self.target_ip = target_ip
        trace = []
        silent = [0]

        def on_hop(data):
            if "error" in data:
                self.error = data["error"]
                return
            ok = data.get("status") == "ok" and data.get("ip") not in (None, "*")
            trace.append({"index": data["hop"], "address": data["ip"] if ok else None,
                          "trace_ms": data.get("ms") if ok else None})
            silent[0] = 0 if ok else silent[0] + 1
            if data.get("destination") or silent[0] >= TRACE_GIVE_UP_TIMEOUTS:
                self._tracer.stop()   # reached the target, or the rest of the path is silent
        self._tracer.run_trace(target_ip, on_hop, max_hops=30)

        while trace and trace[-1]["address"] is None:
            trace.pop()   # trailing silent hops add nothing
        gateway = self._gateway()
        if gateway:
            if trace and trace[0]["index"] == 1 and trace[0]["address"] in (None, gateway):
                trace[0]["address"] = gateway
            elif not any(h["address"] == gateway for h in trace):
                trace.insert(0, {"index": 0, "address": gateway, "trace_ms": None})
        if not trace or trace[-1]["address"] != target_ip:
            last = trace[-1]["index"] if trace else 0
            trace.append({"index": last + 1, "address": target_ip, "trace_ms": None})
        for hop in trace:
            hop.update(gateway=bool(gateway) and hop["address"] == gateway,
                       is_target=hop["address"] == target_ip, asn=None, owner=None)
        return trace

    def _hop_stats(self):
        with self._lock:
            rows = []
            for position, hop in enumerate(self.hops):
                row = {k: hop.get(k) for k in ("index", "address", "asn", "owner", "gateway", "is_target")}
                series = self._samples.get(position)
                if series is None:
                    row.update(_series_stats([], 0, 0))
                else:
                    times = [ms for ms in series if ms is not None]
                    row.update(_series_stats(times, len(series), len(series) - len(times)))
                rows.append(row)
            return rows

    def _lookup(self, position, address):
        info = lookup_asn(address)
        if info:
            with self._lock:
                self.hops[position].update(asn=info["asn"], owner=info["owner"])

    def run(self):
        self.started = datetime.now()
        try:
            self.hops = self._trace()
        except GameServerError:
            self.ended = datetime.now()
            raise
        probed = [i for i, h in enumerate(self.hops) if h["address"]]
        self._samples = {i: [] for i in probed}
        if self._stop.is_set():
            # Cancelled before any round: report() says so with rounds == 0 and cancelled == True
            self.ended = datetime.now()
            self._event("Stopped during the route trace; no hop was probed.", tone="warn")
            return   # no callback after stop()
        answered = sum(1 for h in self.hops if h.get("trace_ms") is not None)
        self._event(f"Traceroute to {self.target} finished: {len(self.hops)} hops listed, "
                    f"{answered} answered the trace.")
        self.callback({"phase": "trace", "hops": self._hop_stats()})

        pool = ThreadPoolExecutor(max_workers=len(probed) + len(self.compare) + 4)
        lookups = [pool.submit(self._lookup, i, self.hops[i]["address"]) for i in probed
                   if not _is_private(self.hops[i]["address"])]
        timeout = min(1.0, self.interval)
        begin = time.monotonic()
        self._event(f"Probing started: {len(probed)} hop(s)"
                    f"{f' and {len(self.compare)} comparison target(s)' if self.compare else ''}, "
                    f"one ping each every {self.interval:g} s.")
        try:
            while not self._stop.is_set() and time.monotonic() - begin < self.duration:
                tick = time.monotonic()
                when = datetime.now()
                futures = {i: pool.submit(ping_ms, self.hops[i]["address"], timeout) for i in probed}
                extra = [pool.submit(ping_ms, c["address"], timeout) for c in self.compare]
                pending = set(futures.values()) | set(extra)
                while pending and not self._stop.is_set():
                    _done, pending = wait(pending, timeout=0.1)
                if self._stop.is_set():
                    break   # an interrupted round is not counted
                with self._lock:
                    for i, future in futures.items():
                        self._samples[i].append(future.result())
                    for series, future in zip(self._compare_samples, extra):
                        series.append(future.result())
                    self.round_times.append(when)
                self.probe_elapsed = time.monotonic() - begin
                if self._stop.is_set():
                    break   # no callback after stop()
                self.callback({"phase": "probe", "elapsed": round(self.probe_elapsed, 1), "hops": self._hop_stats()})
                self._stop.wait(max(0.0, self.interval - (time.monotonic() - tick)))
            # Owners are needed for the verdict; give outstanding lookups a few seconds
            wait(lookups, timeout=10)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            self.ended = datetime.now()
            how = "stopped by the user" if self._stop.is_set() else "planned duration reached"
            self._event(f"Probing ended after {len(self.round_times)} round(s), {how}.")

    def report(self):
        """The result: hop statistics, the verdict, every round ('round_times' and per hop 'samples',
        ms or None, aligned with round_times; hops that were not probed have no samples), comparison
        targets and the events (trace, probing start and end, loss bursts at the target).
        'rounds' is the number of completed rounds; 'cancelled' is True when stop() came before the
        first round (the GUI should treat that as a cancelled run, not as a result)."""
        hops = self._hop_stats()
        with self._lock:
            round_times = [t.isoformat(timespec="seconds") for t in self.round_times]
            for position, row in enumerate(hops):
                row["samples"] = list(self._samples.get(position, []))
            compare = []
            for target, series in zip(self.compare, self._compare_samples):
                times = [ms for ms in series if ms is not None]
                compare.append({"address": target["address"], "label": target.get("label") or target["address"],
                                **_series_stats(times, len(series), len(series) - len(times)),
                                "samples": list(series)})
        events = list(self.events)
        target = next((h for h in hops if h.get("is_target")), None)
        if target and target["samples"]:
            for burst in loss_bursts(target["samples"], round_times):
                events.append({"time": burst["start"], "end": burst["end"], "tone": "bad",
                               "text": f"Loss at the server: {burst['lost']} of {burst['sent']} pings lost."})
        events.sort(key=lambda e: e["time"])
        return {"target": self.target, "relay": self.relay, "host": socket.gethostname(),
                "started": self.started.isoformat(timespec="seconds") if self.started else None,
                "ended": self.ended.isoformat(timespec="seconds") if self.ended else None,
                "duration_s": round(self.probe_elapsed), "interval_s": self.interval,
                "hops": hops, "compare": compare, "round_times": round_times, "events": events,
                "rounds": len(round_times), "cancelled": self._stop.is_set() and not round_times,
                "verdict": localize_loss(hops)}


def loss_bursts(samples, times, merge_gap=3):
    """Runs of lost probes (None in samples): [{'start', 'end', 'sent', 'lost'}] with times taken from
    the aligned `times` list. Losses separated by fewer than merge_gap answered probes form one burst."""
    bursts, current, answered_since = [], None, 0
    for i, ms in enumerate(samples):
        if ms is None:
            if current and answered_since < merge_gap:
                current.update(end_i=i, lost=current["lost"] + 1)
            else:
                current = {"start_i": i, "end_i": i, "lost": 1}
                bursts.append(current)
            answered_since = 0
        else:
            answered_since += 1
    result = []
    for b in bursts:
        result.append({"start": times[b["start_i"]] if b["start_i"] < len(times) else None,
                       "end": times[b["end_i"]] if b["end_i"] < len(times) else None,
                       "sent": b["end_i"] - b["start_i"] + 1, "lost": b["lost"]})
    return result


# ---------------------------------------------------------------------------- reports

def report_markdown(report):
    relay = report.get("relay") or {}
    verdict = report.get("verdict") or {}
    target = report.get("target", "")
    if relay:
        target = f"{target} (Valve relay {relay.get('pop', '')}, {relay.get('desc', '')})"
    lines = ["# Game connection diagnosis", "",
             f"- Target: {target}",
             f"- Started: {report.get('started')}",
             f"- Duration: {report.get('duration_s', 0)} s (one ping per hop every "
             f"{report.get('interval_s', 1.0):g} s)",
             f"- Verdict: **{ZONE_LABELS.get(verdict.get('zone'), 'Unknown')}**: {verdict.get('summary', '')}", "",
             "## Hops", "",
             "| Hop | Address | Network | Loss | Min | Avg | p95 | Max | Jitter |",
             "|---|---|---|---|---|---|---|---|---|"]

    def ms(value):
        return "—" if value is None else f"{value:.1f} ms"
    for hop in report.get("hops", []):
        network = f"AS{hop['asn']} {hop.get('owner') or ''}".strip() if hop.get("asn") else (
            "private" if hop.get("address") and _is_private(hop["address"]) else "—")
        label = hop.get("address") or "no reply"
        if hop.get("gateway"):
            label += " (router)"
        if hop.get("is_target"):
            label += " (server)"
        loss = f"{hop['loss_percent']:.1f}% ({hop['lost']}/{hop['sent']})" if hop.get("sent") else "—"
        lines.append(f"| {hop.get('index')} | {label} | {network} | {loss} | {ms(hop.get('min_ms'))} | "
                     f"{ms(hop.get('avg_ms'))} | {ms(hop.get('p95_ms'))} | {ms(hop.get('max_ms'))} | "
                     f"{ms(hop.get('jitter_ms'))} |")
    lines += ["", "Routers often answer ping slowly or not at all because they handle it at low priority. "
              "Loss at a hop that does not continue to the later hops is not a problem; only loss that starts "
              "at a hop and persists to the server counts.", ""]
    return "\n".join(lines)


def write_report_files(report, folder, detection=None, scan=None):
    """Write the report as Markdown, JSON and a self-contained HTML page (game-connection-<stamp>.*).

    detection: the capture_game_peers() result (optionally with a 'relay' key); scan: the
    scan_relays() result. Both are optional context for the HTML page and the JSON.
    Returns {'md', 'json', 'html'} paths."""
    from network.report_html import render_game_report, unique_base

    os.makedirs(folder, exist_ok=True)
    try:
        stamp = datetime.fromisoformat(report["started"]).strftime("%Y%m%d-%H%M%S")
    except (KeyError, TypeError, ValueError):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = unique_base(folder, f"game-connection-{stamp}", (".md", ".json", ".html"))
    paths = {"md": base + ".md", "json": base + ".json", "html": base + ".html"}
    with open(paths["md"], "w", encoding="utf-8") as f:
        f.write(report_markdown(report))
    data = dict(report)
    if detection:
        data["detection"] = detection
    if scan:
        data["relay_scan"] = scan
    with open(paths["json"], "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    page = render_game_report(report, detection=detection, scan=scan,
                              files={k: os.path.basename(v) for k, v in paths.items()})
    with open(paths["html"], "w", encoding="utf-8") as f:
        f.write(page)
    return paths


def write_report(report, folder, detection=None, scan=None):
    """Write the .md, .json and .html report; returns (md_path, json_path) like before the HTML page
    existed, so existing callers keep working. write_report_files() also returns the HTML path."""
    paths = write_report_files(report, folder, detection=detection, scan=scan)
    return paths["md"], paths["json"]
