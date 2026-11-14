"""Office apps: one-shot quick test and a recording session for Microsoft 365, Teams and Zoom problems.

This module only orchestrates and records. The probes come from network.wifi (Wi-Fi link),
network.office_services (service checks, STUN, routes, proxy), network.health (health scan, DNS
query) and ICMP echo (network.game_server.ping_ms); network.office_quality turns the collected
snapshot into findings and a verdict.

quick_test() runs the whole set once (about probes * interval seconds) and returns a report dict.
OfficeSession records in a daemon thread: once per interval it reads the Wi-Fi status and sends one
ICMP echo to the gateway, one to the internet test host and one STUN Binding Request to each media
relay (at most one probe per second per target); every service_check_every seconds it runs the
service checks. Samples go to a live CSV log under state_dir()/office-logs/, flushed per row.

Report dict (both kinds): kind ("quick"|"session"), started, ended (datetime), label, tenant,
snapshot (the office_quality snapshot plus a few extra keys: gateway_address, internet_host,
dns_server, route, proxy, nearby), findings, verdict, errors (list of str). Sessions add samples,
events, correlations, outages, log_path (plus events_log_path, interval_s, duration_s, trimmed).

Sample: {time, gateway, internet, media: {sid: rtt|None}, rssi_dbm, signal_percent, bssid, channel,
rx_rate_mbps, skipped, gateway_address}; an RTT of None is a lost probe, a key in 'skipped' was not probed that round.
Event: {time, kind, text, layer, details}.

Nothing here raises to the caller: a failing part becomes missing data and a line in 'errors'.
"""
import csv
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from concurrent.futures import wait
from datetime import datetime, timedelta

from network import office_quality as oq
from network import office_services as svc
from network import wifi as wifi_mod
from network.office_services import _cancelled
from utils.paths import state_dir

INTERNET_HOSTS = ("1.1.1.1", "8.8.8.8")
DNS_TEST_HOST = "login.microsoftonline.com"
LOG_DIR_NAME = "office-logs"
MAX_SESSION_S = 8 * 3600         # samples kept for the report (the CSV log keeps everything)
MAX_EVENTS = 5000
MAX_WIFI_EVENTS = 5000
MAX_DNS_RESULTS = 2000
CHECK_JOIN_S = 5.0
STOP_JOIN_S = 7.0                # shared join budget; leave time to write the exit report
GATEWAY_POLL_S = 5.0
FAIL_THRESHOLD = 2               # consecutive lost probes that make an outage (like SessionRecorder)
MIN_SESSION_INTERVAL = 1.0       # at most one probe per second per target
MIN_QUICK_INTERVAL = 0.5
MIN_SERVICE_CHECK_S = 10.0
STOP_POLL = 0.1
WINDOWS_IF_TYPE_ETHERNET = 6
WINDOWS_IF_TYPE_WIFI = 71
TARGET_NAMES = {"gateway": "Router", "internet": "Internet"}
_CURRENT = object()              # default for _probe_jobs: probe self.gateway; None means "no gateway"


# ---------------------------------------------------------------------------- small helpers

def _ping(host, timeout=1.0):
    """One ICMP echo: RTT in ms or None (IcmpSendEcho on Windows, ping elsewhere)."""
    from network.game_server import ping_ms
    return ping_ms(host, timeout)


def _notify(progress, stage, percent):
    if progress is None:
        return
    try:
        progress(stage, int(percent))
    except Exception as e:  # noqa: BLE001 (a GUI callback error must not stop the test)
        logging.debug(f"office progress callback failed: {e}")


def _safe(errors, what, func, *args, default=None, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 (the contract is to never raise)
        logging.debug(f"office {what} failed: {e}")
        errors.append(f"{what} failed: {e}")
        return default


def _sleep_until(deadline, cancel=None):
    """Sleep until time.monotonic() >= deadline, waking early when cancelled."""
    while not _cancelled(cancel):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, STOP_POLL))


def target_label(target):
    """'gateway' -> 'Router', 'media:teams' -> 'Teams media relay'."""
    if target.startswith("media:"):
        return f"{oq.SERVICE_LABELS.get(target[6:], target[6:])} media relay"
    return TARGET_NAMES.get(target, target)


def default_gateway():
    """First IPv4 default gateway, or None."""
    try:
        from network.detector import NetworkDetector
        gateways = [g for g in NetworkDetector().get_default_gateway() if g not in ("N/A", "0.0.0.0") and "." in g]
        return gateways[0] if gateways else None
    except Exception as e:  # noqa: BLE001
        logging.debug(f"gateway lookup failed: {e}")
        return None


def dns_servers():
    """Configured IPv4 DNS servers of the connected adapters ([] when unknown)."""
    try:
        from network.detector import NetworkDetector
        return [d for d in NetworkDetector().get_dns_servers() if d != "N/A"]
    except Exception as e:  # noqa: BLE001
        logging.debug(f"DNS server lookup failed: {e}")
        return []


def media_targets(services):
    """{service_id: {'host', 'port', 'name'}} of the first verified STUN check of each service."""
    found = {}
    for service in services or []:
        for check in service.get("checks", []):
            if check.get("kind") in ("stun", "udp") and check.get("verified", True) and "{tenant}" not in check["host"]:
                found[service["id"]] = {"host": check["host"], "port": check.get("port", 3478), "name": check["name"]}
                break
    return found


def service_targets(services):
    """{service_id: {'rtt_ms', 'jitter_ms', 'loss_pct'}} from the services' 'targets'."""
    return {s["id"]: {k: v for k, v in s["targets"].items() if k in ("rtt_ms", "jitter_ms", "loss_pct")}
            for s in services or [] if isinstance(s.get("targets"), dict)}


def _nearby_summary(networks):
    """Nearby networks without BSSIDs (the report only needs names, signal and channel)."""
    return [{k: n.get(k) for k in ("ssid", "rssi_dbm", "signal_percent", "channel", "band")} for n in networks or []]


# ---------------------------------------------------------------------------- connection type

def _windows_adapters():
    try:
        from utils import winnet
        return winnet.adapter_addresses() or []
    except (OSError, ValueError, ImportError, AttributeError):
        return []


def _interface_kind(name):
    """'wifi' or 'ethernet' for a physical adapter name, None when unknown or virtual."""
    if not name:
        return None
    if sys.platform.startswith("win"):
        adapter = next((a for a in _windows_adapters() if a.get("name") == name), None)
        if adapter is None:
            return None
        return {WINDOWS_IF_TYPE_WIFI: "wifi", WINDOWS_IF_TYPE_ETHERNET: "ethernet"}.get(adapter.get("if_type"))
    if sys.platform.startswith("linux"):
        base = os.path.join("/sys/class/net", name)
        if os.path.isdir(os.path.join(base, "wireless")):
            return "wifi"
        if os.path.exists(os.path.join(base, "device")):
            return "ethernet"
    return None


def _physical_uplink():
    """Kind of the lowest-metric physical adapter that has a default gateway (Windows), else None."""
    if not sys.platform.startswith("win"):
        return None
    for adapter in _windows_adapters():
        if adapter.get("up") and adapter.get("gateways"):
            kind = {WINDOWS_IF_TYPE_WIFI: "wifi", WINDOWS_IF_TYPE_ETHERNET: "ethernet"}.get(adapter.get("if_type"))
            if kind:
                return kind
    return None


def detect_connection(wifi=None, route=None):
    """'wifi', 'ethernet' or 'unknown': the kind of adapter that carries the default route.

    The route to a public address (route_interface) names the adapter; it is Wi-Fi when it is the
    connected Wi-Fi interface. Behind a VPN the tunnel carries the route, so the physical adapter
    with a default gateway is used instead. wifi (a wifi_status() dict) and route (a
    route_interface() dict) may be passed to avoid reading them twice. Never raises."""
    try:
        route = route if route is not None else svc.route_interface(INTERNET_HOSTS[0])
        status = wifi if wifi is not None else wifi_mod.wifi_status()
        iface = route.get("interface")
        wifi_up = bool(status.get("connected"))
        if iface and wifi_up and status.get("interface") and iface == status["interface"]:
            return "wifi"
        if iface and not route.get("is_vpn"):
            return _interface_kind(iface) or "unknown"
        # A VPN tunnel (or no route at all): the physical uplink carries the tunnel
        kind = _physical_uplink()
        if kind:
            return kind
        return "wifi" if wifi_up else "unknown"
    except Exception as e:  # noqa: BLE001
        logging.debug(f"detect_connection failed: {e}")
        return "unknown"


# ---------------------------------------------------------------------------- probes

def icmp_series(host, count, interval, cancel=None, timeout=1.0):
    """count ICMP echoes to host, one per interval: an office_quality series (+ 'address')."""
    rtts = []
    for index in range(max(0, int(count))):
        if _cancelled(cancel):
            break
        started = time.monotonic()
        rtts.append(_ping(host, timeout))
        if index + 1 < count:
            _sleep_until(started + interval, cancel)
    series = oq.series_from_rtts(rtts)
    series["address"] = host
    return series


def pick_internet_host(timeout=1.0):
    """The first INTERNET_HOSTS entry that answers one echo (the first one when none answers)."""
    for host in INTERNET_HOSTS:
        if _ping(host, timeout) is not None:
            return host
    return INTERNET_HOSTS[0]


def dns_timing(host=DNS_TEST_HOST, server=None):
    """Name lookup of a Microsoft host through the system resolver, plus one uncached query to the
    configured DNS server. {'ok', 'ms', 'server', 'host', 'lookup_ms', 'server_ms', 'error'}:
    ok is the system lookup (what the apps see); ms is the uncached server query when it answered
    (the system resolver usually answers from its cache), else the lookup time."""
    from network.health import dns_query
    lookup = svc.dns_lookup(host)
    result = {"ok": lookup.get("ok"), "ms": lookup.get("ms"), "server": server, "host": host,
              "lookup_ms": lookup.get("ms"), "server_ms": None, "error": lookup.get("error")}
    if server:
        answered, ms, _rcode = dns_query(server, timeout=2.0)
        if answered and ms is not None:
            result["server_ms"] = result["ms"] = round(ms, 2)
    return result


def stun_rtt(host, port=3478, timeout=1.0):
    """One STUN Binding Request: RTT in ms or None."""
    result = svc.stun_binding(host, port, timeout)
    return result.get("ms") if result.get("ok") else None


def media_series(host, port, count, interval, cancel=None):
    """stun_series() as an office_quality series (+ 'address', 'port', 'error')."""
    raw = svc.stun_series(host, port, count=count, interval=interval, cancel=cancel)
    series = oq.series_from_rtts(raw.get("rtts") or [])
    series.update(address=host, port=port, error=raw.get("error"))
    return series


def read_wifi():
    """(status, nearby summary, congestion) from the cached Wi-Fi data. Never raises."""
    status = wifi_mod.wifi_status()
    networks = wifi_mod.nearby_networks() if status.get("connected") else []
    congestion = wifi_mod.channel_congestion(status, networks) if status.get("connected") else None
    return status, _nearby_summary(networks), congestion


def _load_services(errors):
    try:
        return svc.load_services()
    except svc.OfficeServicesError as e:
        errors.append(str(e))
        return []


def _diagnose(snapshot, errors):
    try:
        findings = oq.diagnose(snapshot)
        return findings, oq.localize(snapshot, findings)
    except Exception as e:  # noqa: BLE001
        logging.exception("office diagnosis failed")
        errors.append(f"Diagnosis failed: {e}")
        return [], {"layer": "inconclusive", "headline": oq.LAYER_LABELS["inconclusive"],
                    "text": "The diagnosis could not run.", "tone": "neutral", "finding_ids": []}


# ---------------------------------------------------------------------------- Microsoft 365 address list

M365_FETCH_TIMEOUT_S = 5


def _m365_list(cancel=None):
    """(info, endpoint_sets): Microsoft's current endpoint list for the service checks. info is
    {'source', 'fetched', 'error'} (None when cancelled or unexpectedly broken). endpoint_sets is None
    when only the bundled list is available, so the bundled categories stay. Never raises; call it from
    a worker thread (it may download for up to M365_FETCH_TIMEOUT_S)."""
    if _cancelled(cancel):
        return None, None
    try:
        result = svc.fetch_m365_endpoints(timeout=M365_FETCH_TIMEOUT_S)
        info = {"source": result.get("source"), "fetched": result.get("fetched"), "error": result.get("error")}
        sets = result.get("endpoint_sets") if info["source"] in ("web", "cache") else None
        return info, sets or None
    except Exception as e:  # noqa: BLE001
        logging.debug(f"Microsoft 365 endpoint list unavailable: {e}")
        return None, None


def _quick_services(services, tenant, cancel, holder):
    """The quick test's service part: fetch the address list, then run the checks with it."""
    holder["info"], sets = _m365_list(cancel)
    return svc.run_checks(services, tenant, cancel, endpoint_sets=sets)


# ---------------------------------------------------------------------------- quick test

def quick_test(tenant=None, probes=20, interval=0.5, cancel=None, progress=None, services=None):
    """Run every check once and return the report dict (kind 'quick'); see the module docstring.

    probes and interval set the ping and STUN series (default 20 probes, one every 0.5 s, so
    about 10 s; up to about 30 s when a target never answers, because each ping then waits for its 1 s timeout). Independent parts run in parallel. progress(stage, percent) is called from worker
    threads. cancel: threading.Event or callable; on cancel the parts still running are abandoned
    and the report holds what finished ('cancelled': True). services: load_services() output
    (default: the bundled list). Never raises."""
    started = datetime.now()
    errors = []
    count = max(1, int(probes or 1))
    interval = max(MIN_QUICK_INTERVAL, float(interval or MIN_QUICK_INTERVAL))
    tenant = svc.normalize_tenant(tenant) if tenant else None
    _notify(progress, "Reading the Wi-Fi and connection type", 0)

    if services is None:
        services = _load_services(errors)
    media = media_targets(services)
    status, nearby, congestion = _safe(errors, "Wi-Fi status", read_wifi, default=(None, [], None))
    route = _safe(errors, "Route lookup", svc.route_interface, INTERNET_HOSTS[0], default={}) or {}
    connection = detect_connection(status or {}, route)
    gateway = default_gateway()
    if not gateway:
        errors.append("No default gateway found; the router was not measured.")
    servers = dns_servers()
    server = servers[0] if servers else None

    m365 = {}
    parts = {}
    if gateway:
        parts["gateway"] = ("Pinging the router", icmp_series, (gateway, count, interval, cancel))
    parts["internet"] = ("Pinging the internet", _internet_series, (count, interval, cancel))
    parts["dns"] = ("Timing name lookups", dns_timing, (DNS_TEST_HOST, server))
    parts["health"] = ("Running the network health scan", _health_scan, ())
    parts["services"] = ("Checking Microsoft 365, Teams and Zoom", _quick_services, (services, tenant, cancel, m365))
    parts["proxy"] = ("Reading the proxy settings", svc.proxy_settings, ())
    for sid, target in media.items():
        parts[f"media:{sid}"] = (f"Probing the {oq.SERVICE_LABELS.get(sid, sid)} media relay", media_series,
                                 (target["host"], target["port"], count, interval, cancel))
    total = len(parts) + 1
    done = [1]
    lock = threading.Lock()
    _notify(progress, "Measuring", int(100 / total))

    def run(name, stage, func, args):
        with lock:
            percent = min(99, int(100 * done[0] / total))
        _notify(progress, stage, percent)
        value = _safe(errors, stage, func, *args)
        with lock:
            done[0] += 1
            percent = min(99, int(100 * done[0] / total))
        _notify(progress, f"{stage}: done", percent)
        return value

    results = {}
    cancelled = False
    pool = svc._ProbePool(len(parts), name="office-quick")
    try:
        futures = {pool.submit(run, name, *spec): name for name, spec in parts.items()}
        pending = set(futures)
        while pending:
            if _cancelled(cancel):
                cancelled = True
                break
            _done, pending = wait(pending, timeout=STOP_POLL)
        for future, name in futures.items():
            if future.done() and not future.cancelled():
                results[name] = future.result()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    cancelled = cancelled or _cancelled(cancel)
    # Abandoned workers may still append to the shared list: report from a copy taken here.
    final_errors = list(errors)
    if cancelled:
        final_errors.append("Cancelled by the user; parts that had not finished are missing.")

    internet = results.get("internet")
    snapshot = {"time": started, "connection": connection, "wifi": status, "congestion": congestion,
                "wifi_events": [], "gateway": results.get("gateway"), "dns": results.get("dns"),
                "internet": internet, "services": results.get("services") or [],
                "media": {sid: results[f"media:{sid}"] for sid in media if results.get(f"media:{sid}")},
                "health": results.get("health"), "targets": service_targets(services),
                "gateway_address": gateway, "internet_host": (internet or {}).get("address"),
                "dns_server": server, "route": route, "proxy": results.get("proxy"), "nearby": nearby,
                "m365_endpoints": m365.get("info")}
    findings, verdict = _diagnose(snapshot, final_errors)
    _notify(progress, "Done", 100)
    return {"kind": "quick", "started": started, "ended": datetime.now(), "label": "", "tenant": tenant,
            "snapshot": snapshot, "findings": findings, "verdict": verdict, "errors": final_errors,
            "cancelled": cancelled, "probes": count, "interval_s": interval}


def _internet_series(count, interval, cancel=None):
    return icmp_series(pick_internet_host(), count, interval, cancel)


def _health_scan():
    from network.health import run_scan
    return run_scan()


# ---------------------------------------------------------------------------- recording session

class OfficeSession:
    """Records the Wi-Fi link, the router, the internet and the media relays once per interval, and
    the service checks every service_check_every seconds, in a daemon thread.

    start() returns at once; stop() ends the recording and returns the report (see the module
    docstring). on_sample(sample) and on_event(event) are called from worker threads; the GUI must
    marshal them to its own thread. The report covers at most the last MAX_SESSION_S seconds of
    samples ('trimmed' True when older ones were dropped); the CSV logs keep everything.
    """

    def __init__(self, tenant=None, label="", interval=1.0, service_check_every=60, on_sample=None,
                 on_event=None, services=None, log_dir=None):
        self.tenant = svc.normalize_tenant(tenant) if tenant else None
        self.label = (label or "").strip()
        self.interval = max(MIN_SESSION_INTERVAL, float(interval or MIN_SESSION_INTERVAL))
        self.service_check_every = max(MIN_SERVICE_CHECK_S, float(service_check_every or 60))
        self.on_sample = on_sample
        self.on_event = on_event
        self.services = services
        self.log_dir = log_dir
        self.samples = deque(maxlen=int(MAX_SESSION_S / self.interval) + 1)
        self.events = []
        self.wifi_events = []
        self.errors = []
        self.outages = []
        self.trimmed = False
        self.started = None
        self.ended = None
        self.connection = "unknown"
        self.gateway = None
        self._gw_answered = False       # the current gateway has answered at least one ping
        self.internet_host = INTERNET_HOSTS[0]
        self.dns_server = None
        self.route = {}
        self.media = {}                 # sid -> {'host', 'port', 'name', 'address'}
        self.wifi = None                # last Wi-Fi status
        self.congestion = None
        self.nearby = []
        self.health = None
        self._health_period = None
        self.proxy = None
        self.dns_results = []
        self.check_passes = 0
        self.m365_endpoints = None      # {'source', 'fetched', 'error'} of the address list (first pass)
        self._m365_sets = None
        self._m365_done = False
        self.log_path = None
        self.events_log_path = None
        self.tracker = wifi_mod.WifiTracker()
        self._checks = {}               # (service_id, check_id) -> {'last', 'failure', 'failed', 'runs'}
        self._streak = {}
        self._first_fail = {}
        self._open = {}
        self._latest = None
        self._report = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._stop_lock = threading.RLock()     # serialises stop(); never held by probe threads
        self._gateway_lock = threading.Lock()  # serialises reads in the two worker threads
        self._thread = None
        self._check_thread = None
        self._next_check = None
        self._next_gateway_poll = None
        self._sample_file = self._sample_writer = None
        self._event_file = self._event_writer = None
        self._sample_columns = []

    # ---------------------------------------------------------------- public API
    def start(self):
        """Start recording in a daemon thread (no-op when already running)."""
        if self.is_running():
            return
        self._stop.clear()
        self._report = None
        self.started = datetime.now()
        self._thread = threading.Thread(target=self._run, name="office-session", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop recording and return the report (the same report on repeated calls)."""
        if self._report is not None and not self.is_running():
            return self._report
        self._stop.set()                     # at once, before waiting for another stop() call
        deadline = time.monotonic() + STOP_JOIN_S
        if not self._stop_lock.acquire(timeout=STOP_JOIN_S):
            raise TimeoutError("Office recording stop is still running after the shutdown deadline")
        try:
            if self._report is not None and not self.is_running():
                return self._report          # another caller finished while we waited
            try:
                current = threading.current_thread()
                thread = self._thread
                if thread is not None and thread is not current:
                    thread.join(timeout=max(0.0, min(CHECK_JOIN_S, deadline - time.monotonic())))
                check = self._check_thread
                if check is not None and check is not current:
                    check.join(timeout=max(0.0, deadline - time.monotonic()))
                if any(t is not None and t is not current and t.is_alive() for t in (thread, check)):
                    self.errors.append("A recording worker did not stop in time; the report contains collected data.")
                    logging.warning(self.errors[-1])
                self._finish(datetime.now())     # closes the logs
                self._report = self.report()
            except BaseException:
                self._finish_quietly()
                raise
            return self._report
        finally:
            self._stop_lock.release()

    def _finish_quietly(self):
        """Make sure the logs are closed even when stop() failed half way."""
        try:
            with self._lock:
                self._close_logs()
        except Exception:  # noqa: BLE001
            logging.debug("office session cleanup failed", exc_info=True)

    def is_running(self):
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def latest(self):
        """The last sample dict (a copy), or None before the first round."""
        with self._lock:
            return None if self._latest is None else {**self._latest, "media": dict(self._latest["media"])}

    # ---------------------------------------------------------------- loop
    def _run(self):
        pool = None
        try:
            self._prepare(self.started)
            if self._stop.is_set():
                return
            pool = svc._ProbePool(3 + len(self.media))
            while not self._stop.is_set():
                tick = time.monotonic()
                now = datetime.now()
                self._poll_gateway(now)
                if self._next_check is None or now >= self._next_check:
                    self._start_service_pass(now)
                self._tick(now, pool)
                deadline = tick + self.interval
                while not self._stop.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._stop.wait(min(remaining, max(0.0, self._next_gateway_poll - time.monotonic())))
                    self._poll_gateway(datetime.now())
        except Exception as e:  # noqa: BLE001 (the recording ends but the report still works)
            logging.exception("office session loop failed")
            self.errors.append(f"Recording stopped by an error: {e}")
        finally:
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)

    def _prepare(self, now):
        """Load services, find the targets, read the connection and open the CSV logs."""
        if self.services is None:
            self.services = _load_services(self.errors)
        status = wifi_mod.wifi_status()
        self.route = _safe(self.errors, "Route lookup", svc.route_interface, INTERNET_HOSTS[0], default={}) or {}
        self.connection = detect_connection(status, self.route)
        self.wifi = status
        self.gateway = default_gateway()
        self._next_gateway_poll = time.monotonic() + GATEWAY_POLL_S
        if not self.gateway:
            self.errors.append("No default gateway found; the router is not probed.")
        servers = dns_servers()
        self.dns_server = servers[0] if servers else None
        self.internet_host = pick_internet_host()
        for sid, target in media_targets(self.services).items():
            lookup = svc.dns_lookup(target["host"])
            address = (lookup.get("addresses") or [None])[0] if lookup.get("ok") else None
            # Probe one resolved relay address for the whole session: stable path, no lookup per probe
            self.media[sid] = {**target, "address": address or target["host"]}
        with self._lock:
            if not self._stop.is_set():
                self._open_logs(now)

    def _start_service_pass(self, now):
        self._next_check = datetime.fromtimestamp(now.timestamp() + self.service_check_every)
        if self._check_thread is not None and self._check_thread.is_alive():
            return              # the previous pass is still running; skip this one
        self._check_thread = threading.Thread(target=self._service_pass, args=(now,), name="office-checks",
                                              daemon=True)
        self._check_thread.start()

    def _probe_jobs(self, gateway=_CURRENT):
        """The probes of one round. `gateway` is the address to probe; None means no gateway.
        Without an argument the current self.gateway is probed."""
        timeout = min(1.0, self.interval)
        if gateway is _CURRENT:
            gateway = self.gateway
        jobs = {"wifi": (wifi_mod.wifi_status, ())}
        if gateway:
            jobs["gateway"] = (_ping, (gateway, timeout))
        jobs["internet"] = (_ping, (self.internet_host, timeout))
        for sid, target in self.media.items():
            jobs[f"media:{sid}"] = (stun_rtt, (target["address"], target["port"], timeout))
        return jobs

    def _tick(self, now, pool=None):
        """One round: run the probes (in pool, or inline without one) and record the sample."""
        probed_gateway = self.gateway     # the address this round probes; the gateway may change meanwhile
        jobs = self._probe_jobs(probed_gateway)
        results = {"gateway_address": probed_gateway}
        if pool is None:
            for name, (func, args) in jobs.items():
                results[name] = _safe(self.errors, f"Probe {name}", func, *args)
        else:
            futures = {name: pool.submit(func, *args) for name, (func, args) in jobs.items()}
            pending = set(futures.values())
            while pending and not self._stop.is_set():
                _done, pending = wait(pending, timeout=STOP_POLL)
                self._poll_gateway(datetime.now())
            if self._stop.is_set():
                return None          # an interrupted round is not recorded
            for name, future in futures.items():
                try:
                    results[name] = future.result()
                except Exception as e:  # noqa: BLE001
                    results[name] = None
                    logging.debug(f"office probe {name} failed: {e}")
        skipped = [name for name in ("gateway",) if name not in jobs]
        return self.record(now, results, skipped)

    def record(self, now, results, skipped=()):
        """Record one round of probe results: {'wifi': status, 'gateway': rtt|None, 'internet': rtt|None,
        'media:<sid>': rtt|None}. Returns the sample. Used by the loop; tests call it directly."""
        status = results.get("wifi") or {}
        sample = {"time": now, "gateway": results.get("gateway"), "internet": results.get("internet"),
                  "media": {sid: results.get(f"media:{sid}") for sid in self.media},
                  "rssi_dbm": status.get("rssi_dbm"), "signal_percent": status.get("signal_percent"),
                  "bssid": status.get("bssid"), "channel": status.get("channel"),
                  "rx_rate_mbps": status.get("rx_rate_mbps"), "skipped": list(skipped),
                  "gateway_address": self.gateway}
        with self._lock:
            if self.ended is not None and self._stop.is_set():
                return None          # a late probe must not change a finalized recording
            # Tag the sample with the gateway that was really probed. A reply from a gateway that is no
            # longer the default one (changed while the round was in flight) must not count for the new one.
            outage_view = sample
            if "gateway_address" in results:
                sample["gateway_address"] = results["gateway_address"]
                if "gateway" not in sample["skipped"] and results["gateway_address"] != self.gateway:
                    outage_view = dict(sample, skipped=sample["skipped"] + ["gateway"])
            if "gateway" not in outage_view["skipped"] and sample["gateway"] is not None:
                self._gw_answered = True
            if status:
                self.wifi = status
            if self.samples.maxlen and len(self.samples) == self.samples.maxlen:
                self.trimmed = True
            self.samples.append(sample)
            self._latest = sample
            if status and (self.connection == "wifi" or (self.connection == "unknown" and status.get("connected"))):
                for event in self.tracker.update(status, now):
                    self.wifi_events.append(event)
                    if len(self.wifi_events) > MAX_WIFI_EVENTS:
                        del self.wifi_events[:len(self.wifi_events) - MAX_WIFI_EVENTS]
                    self._event(now, event["kind"], event["text"], "wifi", event.get("details"))
            self._update_outages(now, outage_view)
            self._write_sample(sample)
        self._callback(self.on_sample, sample)
        return sample

    # ---------------------------------------------------------------- outages and events
    def _layer_for(self, target, sample):
        local = "wifi" if self.connection == "wifi" else "local"
        if target == "gateway":
            return local
        gateway_down = "gateway" not in sample["skipped"] and sample.get("gateway") is None
        if target == "internet":
            return local if gateway_down else "isp"
        if gateway_down:
            return local
        return "isp" if sample.get("internet") is None else "service"

    def _update_outages(self, now, sample):
        values = {} if "gateway" in sample["skipped"] else {"gateway": sample["gateway"]}
        values["internet"] = sample["internet"]
        values.update({f"media:{sid}": rtt for sid, rtt in sample["media"].items()})
        for target, rtt in values.items():
            if target == "gateway" and rtt is None and not self._gw_answered:
                # A router that never answered ping since it became the default gateway is silent, not
                # down (VPN gateways, some routers): no outage for it.
                self._streak[target] = self._streak.get(target, 0) + 1
                continue
            if rtt is not None:
                self._streak[target] = 0
                self._first_fail.pop(target, None)
                outage = self._open.pop(target, None)
                if outage:
                    outage["end"] = now
                    outage["duration_s"] = round((now - outage["start"]).total_seconds(), 1)
                    self.outages.append(outage)
                    self._event(now, "restore", f"{target_label(target)} answers again after "
                                                f"{outage['duration_s']:g} s", outage["layer"],
                                {"target": target, "duration_s": outage["duration_s"]})
                continue
            self._streak[target] = self._streak.get(target, 0) + 1
            self._first_fail.setdefault(target, now)
            if self._streak[target] == FAIL_THRESHOLD and target not in self._open:
                layer = self._layer_for(target, sample)
                start = self._first_fail[target]
                self._open[target] = {"target": target, "name": target_label(target), "layer": layer,
                                      "start": start, "end": None, "duration_s": None, "ongoing": False}
                self._event(start, "outage", f"{target_label(target)} stopped answering", layer, {"target": target})

    def _close_gateway_outage(self, now):
        """The old gateway is no longer the default gateway: end its open outage and start counting anew."""
        self._streak["gateway"] = 0
        self._first_fail.pop("gateway", None)
        outage = self._open.pop("gateway", None)
        if outage:
            outage["end"] = now
            outage["duration_s"] = round((now - outage["start"]).total_seconds(), 1)
            outage["gateway_changed"] = True
            self.outages.append(outage)

    def _event(self, when, kind, text, layer, details=None):
        event = {"time": when, "kind": kind, "text": text, "layer": layer, "details": dict(details or {})}
        with self._lock:
            if len(self.events) >= MAX_EVENTS:
                del self.events[:len(self.events) - MAX_EVENTS + 1]
                self.trimmed = True
            self.events.append(event)
            self._write_event(event)
        self._callback(self.on_event, event)
        return event

    @staticmethod
    def _callback(func, data):
        if func is None:
            return
        try:
            func(data)
        except Exception as e:  # noqa: BLE001 (a GUI callback error must not stop the recording)
            logging.debug(f"office session callback failed: {e}")

    # ---------------------------------------------------------------- service checks
    def _poll_gateway(self, now):
        tick = time.monotonic()
        if not self._stop.is_set() and (self._next_gateway_poll is None or tick >= self._next_gateway_poll):
            self._next_gateway_poll = tick + GATEWAY_POLL_S
            self._refresh_gateway(now)

    def _refresh_gateway(self, now):
        """Read the gateway in a worker; apply each change once under the recording lock."""
        with self._gateway_lock:
            gateway = default_gateway()
            with self._lock:
                if self._stop.is_set() or not gateway or gateway == self.gateway:
                    return
                if self.gateway:
                    self._event(now, "gateway_change", f"Default gateway changed from {self.gateway} to {gateway}",
                                "local", {"old": self.gateway, "new": gateway})
                    self._close_gateway_outage(now)
                self.gateway = gateway
                self._gw_answered = False

    def _service_pass(self, now=None):
        """Run the service checks, DNS timing and (first pass only) the health scan and proxy settings;
        failures and recoveries become events. Runs in its own thread; tests call it directly."""
        now = now or datetime.now()
        started = time.monotonic()
        errors = []
        if not self._m365_done and not self._stop.is_set():
            info, sets = _m365_list(self._stop)
            if info is not None:
                self.m365_endpoints, self._m365_sets, self._m365_done = info, sets, True
        results = _safe(errors, "Service checks", svc.run_checks, self.services, self.tenant, self._stop,
                        endpoint_sets=self._m365_sets, default=[]) or []
        dns = _safe(errors, "DNS timing", dns_timing, DNS_TEST_HOST, self.dns_server)
        first = self.check_passes == 0
        health = _safe(errors, "Health scan", _health_scan) if first else None
        proxy = _safe(errors, "Proxy settings", svc.proxy_settings) if first else None
        wifi = _safe(errors, "Wi-Fi status", read_wifi, default=None)
        ended = now + timedelta(seconds=max(0.0, time.monotonic() - started))
        self._refresh_gateway(ended)         # fallback; the probe loop normally notices first
        if self._stop.is_set():
            return              # results that arrive after stop() are not part of the report
        with self._lock:
            if self._stop.is_set():
                return          # stop() won the race; the report and the logs are already final
            self.errors.extend(errors)
            self.check_passes += 1
            if first:
                self.health, self.proxy = health, proxy
                self._health_period = (now, ended)
            if wifi and wifi[0].get("connected"):
                self.nearby, self.congestion = wifi[1], wifi[2]
            if dns:
                dns = dict(dns, time=now, ended=ended)
                previous = self.dns_results[-1] if self.dns_results else None
                self.dns_results.append(dns)
                if len(self.dns_results) > MAX_DNS_RESULTS:
                    del self.dns_results[:len(self.dns_results) - MAX_DNS_RESULTS]
                if dns.get("ok") is False and (previous is None or previous.get("ok") is not False):
                    self._event(now, "dns_failed", f"Name lookup of {dns.get('host')} failed",
                                "local" if oq._is_private(dns.get("server")) else "isp", {"error": dns.get("error")})
                elif dns.get("ok") and previous is not None and previous.get("ok") is False:
                    self._event(now, "dns_restored", "Name lookups work again", "local", {})
            internet_down = "internet" in self._open
            for result in results:
                self._merge_check(now, result, internet_down, ended=ended)

    def _merge_check(self, now, result, internet_down, ended=None):
        if result.get("ok") is None:
            return              # untested or cancelled
        key = (result.get("service_id"), result.get("check_id"))
        result = dict(result, time=now, ended=ended or now)
        state = self._checks.setdefault(key, {"last": None, "failure": None, "failed": 0, "runs": 0,
                                              "history": deque(maxlen=MAX_DNS_RESULTS)})
        state["history"].append(result)
        previous = state["last"]
        state["runs"] += 1
        state["last"] = result
        label = oq.SERVICE_LABELS.get(result.get("service_id"), result.get("service_name") or "?")
        what = f"{label} {str(result.get('kind')).upper()}"
        if result["ok"] is False:
            state["failed"] += 1
            state["failure"] = result
            if previous is None or previous.get("ok") is not False:
                error = str(result.get("error") or "")
                layer = ("isp" if internet_down else
                         "corporate" if result.get("kind") in ("tls", "https") and "certif" in error.lower()
                         else "service")
                self._event(now, "service_failed", f"{what} failed ({result.get('name')})"
                            + (f": {error}" if error else ""), layer,
                            {"service_id": result.get("service_id"), "check_id": result.get("check_id"),
                             "host": result.get("host"), "port": result.get("port"), "error": error})
        elif previous is not None and previous.get("ok") is False:
            self._event(now, "service_restored", f"{what} works again ({result.get('name')})", "service",
                        {"service_id": result.get("service_id"), "check_id": result.get("check_id")})

    # ---------------------------------------------------------------- report
    def _finish(self, now):
        with self._lock:
            self.ended = now
            if self.started is None:
                self.started = now
            for outage in self._open.values():
                outage["ongoing"] = True
                outage["duration_s"] = round((now - outage["start"]).total_seconds(), 1)
                self.outages.append(outage)
            self._open = {}
            self._close_logs()

    def _merged_checks(self, changes=None):
        """One result per check: the last failure (with a count) when it ever failed, else the last."""
        merged = []
        for state in self._checks.values():
            if changes is not None:
                history = [c for c in state["history"]
                           if not oq.during_network_change(c["time"], changes, c["ended"])]
                if not history:
                    continue
                failed = [c for c in history if c.get("ok") is False]
                state = {"last": history[-1], "failure": failed[-1] if failed else None,
                         "runs": len(history), "failed": len(failed)}
            if state["failed"]:
                result = {**state["failure"], "details": dict(state["failure"].get("details") or {})}
                if state["runs"] > 1:
                    note = f"failed in {state['failed']} of {state['runs']} checks"
                    result["error"] = f"{result.get('error')} ({note})" if result.get("error") else note
                result["failed_runs"], result["runs"] = state["failed"], state["runs"]
                merged.append(result)
            else:
                merged.append({**state["last"], "runs": state["runs"], "failed_runs": 0})
        return merged

    def _worst_dns(self, changes=None):
        results = [d for d in self.dns_results if changes is None or not oq.during_network_change(
            d.get("time"), changes, d.get("ended"))]
        if not results:
            return None
        failed = [d for d in results if d.get("ok") is False]
        if failed:
            return failed[-1]
        timed = [d for d in results if d.get("ms") is not None]
        return max(timed, key=lambda d: d["ms"]) if timed else results[-1]

    def snapshot(self, samples=None):
        """The office_quality snapshot of the recorded window."""
        with self._lock:
            samples = list(self.samples) if samples is None else samples

            addresses = []
            for s in samples:
                address = s.get("gateway_address")
                if address and address not in addresses and "gateway" not in s.get("skipped", ()):
                    addresses.append(address)

            def series(key, address=None, data=None):
                # Router figures cover the current gateway only: probes sent to an earlier gateway
                # (before a gateway change) are not mixed into the statistic.
                values = [s[key] for s in (samples if data is None else data) if key not in s.get("skipped", ())
                          and (key != "gateway" or s.get("gateway_address") in (None, address))]
                if not values:
                    return None
                result = oq.series_from_rtts(values)
                result["address"] = address
                return result

            def media_series(data):
                media = {}
                for sid, target in self.media.items():
                    values = [s["media"].get(sid) for s in data if sid in s.get("media", {})]
                    if values:
                        media[sid] = {**oq.series_from_rtts(values), "address": target["address"], "port": target["port"]}
                return media

            change_data = {}
            changes = [e for e in self.events if e["kind"] == "gateway_change"]
            if changes:
                affected = [s for s in samples if oq.during_network_change(s["time"], changes)]
                stable = [s for s in samples if not oq.during_network_change(s["time"], changes)]
                lost = sum(sum(s.get(k) is None for k in ("gateway", "internet") if k not in s.get("skipped", ()))
                           + sum(v is None for v in s.get("media", {}).values()) for s in affected)
                failed = sum(c.get("ok") is False and oq.during_network_change(c["time"], changes, c["ended"])
                             for state in self._checks.values() for c in state["history"])
                change_data = {"network_change": {"lost_probes": lost, "failed_checks": failed,
                               "evidence": [f"{e['time'].isoformat(timespec='seconds')}: {e['text']}" for e in changes]},
                               "assessment": {"gateway": series("gateway", self.gateway, stable),
                                              "internet": series("internet", self.internet_host, stable),
                                              "media": media_series(stable), "services": self._merged_checks(changes),
                                              "dns": self._worst_dns(changes),
                                              "health": (None if self._health_period and oq.during_network_change(
                                                  self._health_period[0], changes, self._health_period[1])
                                                  else self.health)}}
            wifi_status = self.wifi
            return {"time": self.started or datetime.now(), "connection": self.connection, "wifi": wifi_status,
                    "congestion": self.congestion, "wifi_events": list(self.wifi_events),
                    "gateway": series("gateway", self.gateway), "dns": self._worst_dns(),
                    "internet": series("internet", self.internet_host), "services": self._merged_checks(),
                    "media": media_series(samples), "health": self.health, "targets": service_targets(self.services),
                    "gateway_address": self.gateway, "gateway_addresses": addresses,
                    "gateway_changed": len(addresses) > 1, "internet_host": self.internet_host,
                    "dns_server": self.dns_server, "route": self.route, "proxy": self.proxy, "nearby": self.nearby,
                    "m365_endpoints": self.m365_endpoints, **change_data}

    def report(self):
        """The session report (works while running too: the window so far)."""
        with self._lock:
            samples = list(self.samples)
            events = list(self.events)
            errors = list(self.errors)
            snapshot = self.snapshot(samples)
            outages = sorted(self.outages + [dict(o, ongoing=True) for o in self._open.values()],
                             key=lambda o: o["start"])
        findings, verdict = _diagnose(snapshot, errors)
        timeline = []
        for s in samples:
            data = {"media": dict(s["media"]), "rssi_dbm": s.get("rssi_dbm"), "internet": s.get("internet")}
            if "gateway" not in s.get("skipped", ()):
                data["gateway"] = s.get("gateway")
            timeline.append((s["time"], data))
        try:
            correlations = oq.correlate(snapshot["wifi_events"], timeline)
        except Exception as e:  # noqa: BLE001
            errors.append(f"Correlation failed: {e}")
            correlations = []
        end = self.ended or datetime.now()
        start = self.started or end
        return {"kind": "session", "started": start, "ended": end, "label": self.label, "tenant": self.tenant,
                "snapshot": snapshot, "findings": findings, "verdict": verdict, "errors": errors,
                "samples": samples, "events": events, "correlations": correlations,
                "outages": [{k: v for k, v in o.items()} for o in outages], "log_path": self.log_path,
                "events_log_path": self.events_log_path, "interval_s": self.interval,
                "duration_s": round((end - start).total_seconds()), "service_check_every_s": self.service_check_every,
                "check_passes": self.check_passes, "trimmed": self.trimmed}

    # ---------------------------------------------------------------- CSV logs
    def _open_logs(self, now):
        try:
            folder = self.log_dir or os.path.join(state_dir(), LOG_DIR_NAME)
            os.makedirs(folder, exist_ok=True)
            from network.report_html import unique_base
            base = unique_base(folder, f"office-{now.strftime('%Y%m%d-%H%M%S')}", (".csv", "-events.csv"))
            self._sample_columns = list(self.media)
            self._sample_file = open(base + ".csv", "w", newline="", encoding="utf-8")
            self._sample_writer = csv.writer(self._sample_file)
            self._sample_writer.writerow(["time", "gateway_ms", "internet_ms"]
                                         + [f"{sid}_media_ms" for sid in self._sample_columns]
                                         + ["rssi_dbm", "signal_percent", "bssid", "channel", "rx_rate_mbps"])
            self._sample_file.flush()
            self.log_path = base + ".csv"
            self._event_file = open(base + "-events.csv", "w", newline="", encoding="utf-8")
            self._event_writer = csv.writer(self._event_file)
            self._event_writer.writerow(["time", "kind", "layer", "text"])
            self._event_file.flush()
            self.events_log_path = base + "-events.csv"
        except OSError as e:
            self.errors.append(f"Cannot write the log: {e}")
            self._close_logs()

    @staticmethod
    def _cell(value, skipped=False):
        if skipped:
            return ""
        return "lost" if value is None else round(value, 2)

    def _write_sample(self, sample):
        if not self._sample_writer:
            return
        try:
            self._sample_writer.writerow(
                [sample["time"].isoformat(timespec="seconds"),
                 self._cell(sample["gateway"], "gateway" in sample["skipped"]), self._cell(sample["internet"])]
                + [self._cell(sample["media"].get(sid)) for sid in self._sample_columns]
                + ["" if sample.get(k) is None else sample[k]
                   for k in ("rssi_dbm", "signal_percent", "bssid", "channel", "rx_rate_mbps")])
            self._sample_file.flush()
        except (OSError, ValueError) as e:
            logging.debug(f"office sample log write failed: {e}")

    def _write_event(self, event):
        if not self._event_writer:
            return
        try:
            self._event_writer.writerow([event["time"].isoformat(timespec="seconds"), event["kind"], event["layer"],
                                         event["text"]])
            self._event_file.flush()
        except (OSError, ValueError) as e:
            logging.debug(f"office event log write failed: {e}")

    def _close_logs(self):
        for handle in (self._sample_file, self._event_file):
            if handle:
                try:
                    handle.close()
                except OSError:
                    pass
        self._sample_file = self._sample_writer = self._event_file = self._event_writer = None


# ---------------------------------------------------------------------------- report files

def _iso(value):
    return value.isoformat(timespec="seconds") if isinstance(value, datetime) else value


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, (set, frozenset, tuple, deque)):
        return list(value)
    return str(value)


def report_json(report):
    """The report as JSON text (datetimes as ISO strings)."""
    return json.dumps(report, ensure_ascii=False, indent=1, default=_json_default)


def _fmt_ms(value):
    return "—" if value is None else f"{value:.1f} ms"


def _series_row(name, series):
    if not series or not series.get("sent"):
        return f"| {name} | — | not measured | — | — | — | — |"
    mos = oq.series_mos(series)
    return (f"| {name} | {series.get('address') or '—'} | {series.get('loss_pct', 0):.1f}% "
            f"({series.get('lost', 0)}/{series.get('sent', 0)}) | {_fmt_ms(series.get('avg_ms'))} | "
            f"{_fmt_ms(series.get('jitter_ms'))} | {_fmt_ms(series.get('p95_ms'))} | "
            f"{f'{mos:.2f} ({oq.mos_label(mos)})' if mos is not None else '—'} |")


def wifi_text(wifi, connection=None):
    """One-line description of a Wi-Fi status for reports."""
    if not wifi:
        return "not read"
    if not wifi.get("connected"):
        return wifi.get("message") or wifi.get("reason") or "not connected"
    parts = [f"'{wifi['ssid']}'" if wifi.get("ssid") else "network name hidden"]
    if wifi.get("rssi_dbm") is not None:
        parts.append(f"{wifi['rssi_dbm']} dBm" + (f" ({wifi['signal_percent']}%)"
                                                   if wifi.get("signal_percent") is not None else ""))
    if wifi.get("band"):
        parts.append(wifi["band"] + (f" channel {wifi['channel']}" if wifi.get("channel") else ""))
    rates = [r for r in (wifi.get("rx_rate_mbps"), wifi.get("tx_rate_mbps")) if r is not None]
    if rates:
        parts.append(f"link {wifi.get('rx_rate_mbps') or '—'}/{wifi.get('tx_rate_mbps') or '—'} Mbps")
    if wifi.get("radio_type"):
        parts.append(wifi["radio_type"])
    return ", ".join(parts)


def report_markdown(report):
    """Markdown summary of a quick-test or session report (public IPs, MAC addresses/BSSIDs and the
    computer name masked like the AI package; SSIDs stay readable)."""
    from network.report_html import m365_list_text, mask_private
    r = mask_private(report)
    snap = r.get("snapshot") or {}
    verdict = r.get("verdict") or {}
    session = r.get("kind") == "session"
    title = f"Office apps {'recording' if session else 'quick test'}" + (f": {r['label']}" if r.get("label") else "")
    connection = {"wifi": "Wi-Fi", "ethernet": "Ethernet (cable)"}.get(snap.get("connection"), "Unknown")
    lines = [f"# {title}", "", f"- Started: {_iso(r.get('started'))}", f"- Ended: {_iso(r.get('ended'))}"]
    if session:
        lines.append(f"- Duration: {r.get('duration_s', 0)} s, one probe per target every {r.get('interval_s', 1):g} s, "
                     f"{len(r.get('samples') or [])} rounds, {r.get('check_passes', 0)} service check pass(es)")
    if r.get("tenant"):
        lines.append(f"- Tenant: {r['tenant']}")
    route = snap.get("route") or {}
    lines += [f"- Connection: {connection}" + (" through a VPN" if route.get("is_vpn") else ""),
              f"- Wi-Fi: {wifi_text(snap.get('wifi'))}" if snap.get("connection") == "wifi" else None,
              f"- Verdict: **{verdict.get('headline', '?')}**: {verdict.get('text', '')}", ""]
    listing = m365_list_text(snap.get("m365_endpoints"))
    if listing:
        lines.insert(len(lines) - 1, f"- Microsoft 365 address list: {listing}")
    lines = [line for line in lines if line is not None]
    ids = {f.get("id") for f in r.get("findings") or []}
    silent = "gateway_silent" in ids
    addresses = [str(a) for a in snap.get("gateway_addresses") or []]
    changed = "gateway_changed" in ids or bool(snap.get("gateway_changed")) or len(addresses) > 1
    router_row = _series_row("Router", snap.get("gateway"))
    if silent and (snap.get("gateway") or {}).get("sent"):
        router_row = router_row.replace("| Router |", "| Router (does not answer ping) |", 1)
    lines += ["## Measurements", "", "| Target | Address | Loss | Avg | Jitter | p95 | Est. MOS |",
              "|---|---|---|---|---|---|---|", router_row, _series_row("Internet", snap.get("internet"))]
    for sid, series in (snap.get("media") or {}).items():
        lines.append(_series_row(f"{oq.SERVICE_LABELS.get(sid, sid)} media relay (STUN)", series))
    if silent:
        lines += ["", "Router note: the router does not answer ping (normal for many routers); the path beyond it is "
                      "fine, so this is information, not a problem."]
    if changed:
        lines += ["", "Gateway note: the default gateway changed during the recording"
                  + (f" ({' -> '.join(addresses)})" if len(addresses) > 1 else "")
                  + "; the router row covers the current gateway only."]
    dns = snap.get("dns")
    if dns:
        lines += ["", f"DNS: lookup of {dns.get('host')} " + ("OK" if dns.get("ok") else "FAILED")
                  + f", {_fmt_ms(dns.get('ms'))} (server {dns.get('server') or 'unknown'})"]
    lines += ["", "## Findings", ""]
    findings = r.get("findings") or []
    for layer in oq.LAYERS:
        items = [f for f in findings if f.get("layer") == layer]
        if not items:
            continue
        lines += [f"### {oq.LAYER_LABELS.get(layer, layer)}", ""]
        for f in items:
            lines.append(f"- [{f.get('severity', '').upper()}] **{f.get('title')}**: {f.get('summary')}"
                         + (" (uncertain)" if f.get("uncertain") else ""))
            lines += [f"  - {e}" for e in f.get("evidence") or []]
            if f.get("fix") and f.get("severity") != "ok":
                lines.append(f"  - Fix: {f['fix']}")
        lines.append("")
    if not findings:
        lines += ["No findings.", ""]
    checks = snap.get("services") or []
    if checks:
        lines += ["## Service checks", "", "| Service | Check | Kind | Target | Result | Time |", "|---|---|---|---|---|---|"]
        for c in checks:
            result = ("untested" if c.get("ok") is None else "OK" if c.get("ok") else "FAILED")
            if c.get("error"):
                result += f" ({c['error']})"
            target = f"{c.get('host')}:{c.get('port')}" if c.get("port") else str(c.get("host"))
            lines.append(f"| {oq.SERVICE_LABELS.get(c.get('service_id'), c.get('service_name'))} | {c.get('name')} | "
                         f"{c.get('kind')} | {target} | {result} | {_fmt_ms(c.get('ms'))} |")
        lines.append("")
    if session:
        lines += ["## Outages", ""]
        if r.get("outages"):
            lines += ["| Start | End | Duration | Target | Layer |", "|---|---|---|---|---|"]
            for o in r["outages"]:
                end = "still down at the end" if o.get("ongoing") else _iso(o.get("end"))
                lines.append(f"| {_iso(o.get('start'))} | {end} | {o.get('duration_s')} s | {o.get('name')} | "
                             f"{oq.LAYER_LABELS.get(o.get('layer'), o.get('layer'))} |")
        else:
            lines.append("No outages (an outage is 2 or more lost probes in a row).")
        lines += ["", "## Events", ""]
        events = r.get("events") or []
        lines += [f"- {_iso(e.get('time'))} [{e.get('layer')}] {e.get('text')}" for e in events[:100]] or ["None."]
        if len(events) > 100:
            lines.append(f"- … and {len(events) - 100} more in the JSON file.")
        lines += ["", "## Loss and Wi-Fi correlation", ""]
        lines += [f"- {c}" for c in r.get("correlations") or []] or ["No loss bursts."]
        lines.append("")
    if r.get("errors"):
        lines += ["## Errors", ""] + [f"- {e}" for e in r["errors"]] + [""]
    lines += ["The MOS value is an estimate from network numbers only (simplified ITU-T G.107 E-model); codec, CPU "
              "and audio devices are not modelled.", ""]
    return "\n".join(lines)


def write_report_files(report, folder):
    """Write office-<kind>-<stamp>.html, .md and .json into folder; returns {'html', 'md', 'json'}."""
    from network.report_html import render_office_report, unique_base
    os.makedirs(folder, exist_ok=True)
    started = report.get("started")
    stamp = (started if isinstance(started, datetime) else datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = unique_base(folder, f"office-{report.get('kind') or 'report'}-{stamp}", (".html", ".md", ".json"))
    paths = {"html": base + ".html", "md": base + ".md", "json": base + ".json"}
    with open(paths["md"], "w", encoding="utf-8") as f:
        f.write(report_markdown(report))
    with open(paths["json"], "w", encoding="utf-8") as f:
        f.write(report_json(report))
    with open(paths["html"], "w", encoding="utf-8") as f:
        f.write(render_office_report(report, files={k: os.path.basename(v) for k, v in paths.items()}))
    return paths
