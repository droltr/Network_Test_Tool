"""Office apps: reachability probes for Microsoft 365, Teams and Zoom (and any service added to
assets/data/office_services.json).

Pieces:
- load_services() reads the service definitions. A service is a list of checks; each check names a
  probe kind (dns, tcp, tls, https, stun, udp), a host and a port. Hosts may contain "{tenant}"
  (e.g. "{tenant}.sharepoint.com"); those checks are skipped when no tenant name is given.
- Probe primitives (dns_lookup, tcp_connect, tls_handshake, https_get, stun_binding) each return a
  dict with at least ok (True/False, None = untested), ms and error. They never raise.
- route_interface() tells which local adapter the OS would use for an address, so the GUI can say
  "Optimize traffic goes through the VPN tunnel" (Microsoft asks for Optimize traffic to bypass
  proxies and VPNs).
- run_checks() runs the checks of several services in a small thread pool; stun_series() takes a
  short STUN round-trip sample (loss, latency, jitter) of the Teams media path.
- fetch_m365_endpoints() downloads Microsoft's endpoint list (endpoints.office.com) at most once a
  day and falls back to the cached copy, then to the Optimize sets bundled in the JSON file.

Politeness and safety rules (binding):
1. Every probe is one name lookup, one TCP connect, one TLS handshake, one HTTP GET of a public
   page, or one STUN Binding Request (RFC 5389, 20 bytes) per check. stun_series() sends at most one
   request per interval (default 1 s). No load generation, no bandwidth tests against these services.
2. No credentials, no sign-in, no cookies, no tenant data. A tenant name is only used to form a host
   name for a TLS handshake. HTTP requests carry no body and the response body is not read.
3. HTTPS GETs go through the system proxy (urllib reads the Windows Internet Settings and the
   *_proxy environment variables) because that is how the Office apps reach these hosts; each
   result says whether a proxy was used. Proxy addresses are reported without user names/passwords.
4. A check marked "verified": false in the JSON has no public target known to answer the probe;
   it is reported as untested (ok None) instead of failed, so it never blames the user's network.
5. Microsoft's endpoint web service is called at most once a day per machine with one random
   client request id, as its documentation asks (no polling of the endpoints method).
"""
import ipaddress
import json
import logging
import os
import queue
import re
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import Future
from datetime import datetime, timezone

import psutil

from utils.paths import resource_path, state_dir

M365_ENDPOINTS_URL = "https://endpoints.office.com/endpoints/worldwide?clientrequestid={guid}"
M365_CACHE_NAME = "m365-endpoints.json"
M365_CLIENT_ID_NAME = "m365-client-request-id.txt"
M365_FAILURE_NAME = "m365-endpoints-failure.json"
M365_RETRY_S = 3600
M365_REFRESH_S = 24 * 3600          # Microsoft publishes changes monthly; once a day is plenty
CHECK_KINDS = ("dns", "tcp", "tls", "https", "stun", "udp")
TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
USER_AGENT = "network-test-tool"

STUN_MAGIC = 0x2112A442
STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_SUCCESS = 0x0101
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020
STUN_ATTR_XOR_MAPPED_ADDRESS_OLD = 0x8020   # pre-RFC 5389 servers

WINDOWS_IF_TYPE_PPP = 23


class OfficeServicesError(Exception):
    """An error whose message can be shown to the user as is."""


def _cancelled(cancel):
    """cancel is None, a threading.Event (or anything with is_set) or a callable returning bool.
    Same convention as network.game_server._cancelled."""
    if cancel is None:
        return False
    if hasattr(cancel, "is_set"):
        return cancel.is_set()
    return bool(cancel())


def _ms(start):
    return round((time.perf_counter() - start) * 1000, 2)


def _error_text(error):
    text = str(error) or error.__class__.__name__
    return text if len(text) <= 300 else text[:297] + "..."


def _result(ok=None, ms=None, error=None, **extra):
    data = {"ok": ok, "ms": ms, "error": error}
    data.update(extra)
    return data


# ---------------------------------------------------------------------------- service definitions

def _validate_check(check, where):
    if not isinstance(check, dict):
        raise OfficeServicesError(f"{where}: a check must be an object.")
    for key in ("id", "name", "kind", "host"):
        if not isinstance(check.get(key), str) or not check[key].strip():
            raise OfficeServicesError(f"{where}: '{key}' is missing or not text.")
    if check["kind"] not in CHECK_KINDS:
        raise OfficeServicesError(f"{where}: unknown kind '{check['kind']}'.")
    port = check.get("port", 443)
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        raise OfficeServicesError(f"{where}: invalid port {port!r}.")
    normalized = dict(check)
    normalized["port"] = port
    normalized["optimize"] = bool(check.get("optimize", False))
    normalized["verified"] = bool(check.get("verified", True))
    if check["kind"] == "https":
        path = check.get("path", "/")
        if not isinstance(path, str) or not path.startswith("/"):
            raise OfficeServicesError(f"{where}: 'path' must start with '/'.")
        normalized["path"] = path
    return normalized


def validate_services(data):
    """The 'services' list of a parsed office_services.json, checked and normalized
    (port defaults to 443, optimize to False, verified to True, path to '/'). Raises
    OfficeServicesError with a readable message."""
    if not isinstance(data, dict) or not isinstance(data.get("services"), list):
        raise OfficeServicesError("The service list has an unexpected format.")
    services, seen = [], set()
    for index, service in enumerate(data["services"]):
        where = f"service #{index + 1}"
        if not isinstance(service, dict):
            raise OfficeServicesError(f"{where}: a service must be an object.")
        for key in ("id", "name"):
            if not isinstance(service.get(key), str) or not service[key].strip():
                raise OfficeServicesError(f"{where}: '{key}' is missing or not text.")
        if service["id"] in seen:
            raise OfficeServicesError(f"{where}: duplicate id '{service['id']}'.")
        seen.add(service["id"])
        checks = service.get("checks")
        if not isinstance(checks, list):
            raise OfficeServicesError(f"{where}: 'checks' must be a list.")
        normalized = dict(service)
        normalized["checks"] = [_validate_check(c, f"{service['id']} check #{i + 1}") for i, c in enumerate(checks)]
        ids = [c["id"] for c in normalized["checks"]]
        if len(ids) != len(set(ids)):
            raise OfficeServicesError(f"{where}: duplicate check ids.")
        targets = service.get("targets")
        if targets is not None:
            if not isinstance(targets, dict) or not all(
                    isinstance(targets.get(k), (int, float)) and not isinstance(targets.get(k), bool)
                    for k in targets):
                raise OfficeServicesError(f"{where}: 'targets' must map names to numbers.")
        services.append(normalized)
    return services


def _default_services_path():
    return resource_path("assets", "data", "office_services.json")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_services(path=None):
    """Service dicts from office_services.json (bundled copy by default). Raises
    OfficeServicesError when the file is missing or invalid."""
    path = path or _default_services_path()
    try:
        data = _read_json(path)
    except (OSError, ValueError) as e:
        raise OfficeServicesError(f"Cannot read the service list ({e}).") from e
    return validate_services(data)


def normalize_tenant(tenant):
    """'contoso', 'contoso.onmicrosoft.com', 'contoso.sharepoint.com' or a SharePoint URL -> 'contoso'.
    None when empty or not a valid tenant label."""
    if not tenant or not isinstance(tenant, str):
        return None
    text = tenant.strip().lower()
    if "://" in text:
        text = urllib.parse.urlsplit(text).hostname or ""
    label = text.split(".")[0]
    if label.endswith("-my"):
        label = label[:-3]
    return label if TENANT_RE.match(label) else None


def expand_host(host, tenant):
    """host with {tenant} filled in; None when the host needs a tenant and none is given."""
    if "{tenant}" not in host:
        return host
    tenant = normalize_tenant(tenant)
    return host.replace("{tenant}", tenant) if tenant else None


# ---------------------------------------------------------------------------- proxy settings

def _strip_credentials(url):
    """'http://user:pw@proxy:8080' -> 'http://proxy:8080' (reports never carry credentials)."""
    if not url:
        return url
    return re.sub(r"(^|//)[^/@\s]*@", r"\1", str(url))


def proxy_settings():
    """{'configured': bool, 'https_proxy': str|None, 'details': [str]}: the proxy urllib would use
    for HTTPS plus the system proxy settings network.health reads. Never raises."""
    details = []
    https_proxy = None
    try:
        proxies = urllib.request.getproxies()
        https_proxy = proxies.get("https") or proxies.get("all")
        for scheme in sorted(proxies):
            if scheme != "no":
                details.append(f"{scheme} proxy: {_strip_credentials(proxies[scheme])}")
    except Exception as e:  # noqa: BLE001 (registry/env oddities must not break a scan)
        logging.debug(f"Cannot read proxy settings: {e}")
    if sys.platform.startswith("win"):
        try:
            from network.health import _windows_proxy_settings
            for line in _windows_proxy_settings():
                line = _strip_credentials(line)
                if line not in details:
                    details.append(line)
        except Exception as e:  # noqa: BLE001
            logging.debug(f"Cannot read Windows proxy settings: {e}")
    return {"configured": bool(details), "https_proxy": _strip_credentials(https_proxy), "details": details}


# ---------------------------------------------------------------------------- probes

class _ProbePool:
    """Fixed daemon workers so hung probes cannot hold up interpreter exit.

    ThreadPoolExecutor joins its workers at interpreter exit even when shut down
    with wait=False. Office workers must be safe to abandon after the exit deadline.
    """

    def __init__(self, workers, name="office-probe"):
        self.jobs = queue.Queue()
        self.threads = [threading.Thread(target=self._work, name=name, daemon=True) for _ in range(workers)]
        for thread in self.threads:
            thread.start()

    def _work(self):
        while (job := self.jobs.get()) is not None:
            future, func, args = job
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(func(*args))
                except BaseException as error:
                    future.set_exception(error)

    def submit(self, func, *args):
        future = Future()
        self.jobs.put((future, func, args))
        return future

    def shutdown(self, wait=False, cancel_futures=True):
        if cancel_futures:
            while True:
                try:
                    self.jobs.get_nowait()[0].cancel()
                except queue.Empty:
                    break
        for _ in self.threads:
            self.jobs.put(None)
        if wait:
            for thread in self.threads:
                thread.join()


DNS_LOOKUP_LIMIT = 8
_DNS_LOCK = threading.Lock()
_DNS_LOOKUPS = {}                 # (host, port, family) -> running lookup, shared by callers


def _resolve(host, port, timeout, family=socket.AF_UNSPEC, socktype=socket.SOCK_STREAM):
    """getaddrinfo with a time limit (it has none of its own): list of sockaddr tuples, IPv4 first.
    Raises OSError (socket.gaierror) or TimeoutError."""
    deadline = time.monotonic() + max(0.0, timeout)
    key = (host, port, family)
    while True:
        with _DNS_LOCK:
            # A stuck getaddrinfo keeps its slot even after its caller times out.
            for old_key, old in list(_DNS_LOOKUPS.items()):
                if not old["thread"].is_alive():
                    del _DNS_LOOKUPS[old_key]
            box = _DNS_LOOKUPS.get(key)
            if box is None:
                if len(_DNS_LOOKUPS) >= DNS_LOOKUP_LIMIT:
                    raise TimeoutError("name lookup timed out: DNS worker limit reached")
                box = {"done": threading.Event(), "socktype": socktype}

                def worker(box=box):
                    try:
                        box["value"] = socket.getaddrinfo(host, port, family, socktype)
                    except Exception as e:  # noqa: BLE001 (re-raised by each waiting caller)
                        box["error"] = e
                    finally:
                        box["done"].set()

                box["thread"] = threading.Thread(target=worker, name="office-dns", daemon=True)
                _DNS_LOOKUPS[key] = box
                try:
                    box["thread"].start()
                except BaseException:
                    del _DNS_LOOKUPS[key]
                    raise
        if not box["done"].wait(max(0.0, deadline - time.monotonic())):
            raise TimeoutError(f"name lookup timed out after {timeout:g} s")
        if box["socktype"] == socktype:
            break
        # Different socket types share the slot, but need their own result.
        box["thread"].join(max(0.0, deadline - time.monotonic()))
        if time.monotonic() >= deadline:
            raise TimeoutError(f"name lookup timed out after {timeout:g} s")
    if "error" in box:
        raise box["error"]
    infos = sorted(box.get("value") or [], key=lambda info: 0 if info[0] == socket.AF_INET else 1)
    seen, result = set(), []
    for family_, _type, _proto, _name, sockaddr in infos:
        if sockaddr[0] not in seen:
            seen.add(sockaddr[0])
            result.append((family_, sockaddr))
    if not result:
        raise OSError(f"no address found for {host}")
    return result


def dns_lookup(host, timeout=3):
    """Name lookup through the system resolver: + addresses (IPv4 first)."""
    start = time.perf_counter()
    try:
        found = _resolve(host, None, timeout)
        return _result(True, _ms(start), None, addresses=[sockaddr[0] for _f, sockaddr in found])
    except Exception as e:  # noqa: BLE001 (probes never raise)
        return _result(False, _ms(start), _error_text(e), addresses=[])


CONNECT_ATTEMPT_MIN_S = 1.0    # shortest slice one address gets before the next one is tried


def _connect(host, port, timeout):
    """Connected TCP socket to the first address that answers. Returns (socket, connect_ms).

    The time limit is shared between the addresses: one address that silently drops packets (a
    black-holed member of a DNS round robin, for example) must not use up the whole limit, or a
    healthy service is reported as unreachable. Each attempt gets an equal share of what is left
    (at least CONNECT_ATTEMPT_MIN_S), like a browser that falls back to the next address."""
    deadline = time.monotonic() + timeout
    last_error = None
    addresses = _resolve(host, port, timeout)
    for index, (family, sockaddr) in enumerate(addresses):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        share = max(CONNECT_ATTEMPT_MIN_S, remaining / (len(addresses) - index))
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(min(remaining, share))
        start = time.perf_counter()
        try:
            sock.connect(sockaddr)
            sock.settimeout(max(0.1, deadline - time.monotonic()))
            return sock, _ms(start)
        except OSError as e:
            last_error = e
            sock.close()
    raise last_error or TimeoutError(f"connection timed out after {timeout:g} s")


def tcp_connect(host, port, timeout=3):
    """One TCP connect (closed right away): ms is the handshake time without the name lookup.
    + address, local_address."""
    try:
        sock, connect_ms = _connect(host, port, timeout)
    except Exception as e:  # noqa: BLE001
        return _result(False, None, _error_text(e), address=None, local_address=None)
    try:
        return _result(True, connect_ms, None, address=sock.getpeername()[0], local_address=sock.getsockname()[0])
    except OSError as e:
        return _result(True, connect_ms, None, address=None, local_address=None, note=_error_text(e))
    finally:
        sock.close()


def _cert_name(cert, field):
    for rdn in (cert or {}).get(field, ()):
        for key, value in rdn:
            if key in ("organizationName", "commonName"):
                return value
    return None


def tls_handshake(host, port=443, timeout=5):
    """TCP connect + TLS handshake with certificate validation, then close.
    + version, cert_expires (ISO date), issuer, address. A validation failure is reported in
    error; it often means a proxy or security product inspects TLS."""
    extra = {"version": None, "cert_expires": None, "issuer": None, "address": None}
    try:
        sock, _connect_ms = _connect(host, port, timeout)
    except Exception as e:  # noqa: BLE001
        return _result(False, None, _error_text(e), **extra)
    try:
        extra["address"] = sock.getpeername()[0]
        context = ssl.create_default_context()
        start = time.perf_counter()
        with context.wrap_socket(sock, server_hostname=host) as tls:
            ms = _ms(start)
            cert = tls.getpeercert()
            extra["version"] = tls.version()
            extra["issuer"] = _cert_name(cert, "issuer")
            not_after = (cert or {}).get("notAfter")
            if not_after:
                expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc)
                extra["cert_expires"] = expires.date().isoformat()
        return _result(True, ms, None, **extra)
    except Exception as e:  # noqa: BLE001
        return _result(False, None, _error_text(e), **extra)
    finally:
        sock.close()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a 3xx answer already proves the service is reachable
        return None


def https_get(host, path="/", timeout=6):
    """One HTTPS GET through the system proxy; the body is not read and redirects are not followed.
    ok is True for any HTTP answer below 500. + status, via_proxy, proxy."""
    proxies = {}
    try:
        proxies = urllib.request.getproxies()
        if urllib.request.proxy_bypass(host):
            proxies = {}
    except Exception:  # noqa: BLE001
        proxies = {}
    proxy = proxies.get("https") or proxies.get("all")
    extra = {"status": None, "via_proxy": bool(proxy), "proxy": _strip_credentials(proxy)}
    url = f"https://{host}{path}"
    handlers = [urllib.request.ProxyHandler({"https": proxy} if proxy else {}), _NoRedirect()]
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    start = time.perf_counter()
    try:
        with opener.open(request, timeout=timeout) as response:
            extra["status"] = response.status
    except urllib.error.HTTPError as e:      # 3xx (no redirect), 4xx, 5xx: the server answered
        extra["status"] = e.code
        e.close()
    except Exception as e:  # noqa: BLE001
        reason = getattr(e, "reason", None)
        return _result(False, _ms(start), _error_text(reason if reason is not None else e), **extra)
    ms = _ms(start)
    if extra["status"] >= 500:
        return _result(False, ms, f"HTTP {extra['status']}", **extra)
    return _result(True, ms, None, **extra)


# ---------------------------------------------------------------------------- STUN (RFC 5389)

def stun_request(transaction_id=None):
    """A 20-byte STUN Binding Request without attributes: (message, transaction_id)."""
    transaction_id = transaction_id or os.urandom(12)
    if len(transaction_id) != 12:
        raise ValueError("a STUN transaction id has 12 bytes")
    return struct.pack("!HHI", STUN_BINDING_REQUEST, 0, STUN_MAGIC) + transaction_id, transaction_id


def _parse_address(value, xor, transaction_id):
    if len(value) < 8:
        return None
    family, port = value[1], struct.unpack("!H", value[2:4])[0]
    if xor:
        port ^= STUN_MAGIC >> 16
    if family == 0x01:
        raw = value[4:8]
        if xor:
            raw = bytes(a ^ b for a, b in zip(raw, struct.pack("!I", STUN_MAGIC)))
    elif family == 0x02 and len(value) >= 20:
        raw = value[4:20]
        if xor:
            raw = bytes(a ^ b for a, b in zip(raw, struct.pack("!I", STUN_MAGIC) + transaction_id))
    else:
        return None
    return str(ipaddress.ip_address(raw)), port


def parse_stun_response(data, transaction_id):
    """(mapped_address, mapped_port) from a Binding Success Response to transaction_id, preferring
    XOR-MAPPED-ADDRESS. Raises ValueError for anything else (wrong type, id, length or no address)."""
    if len(data) < 20:
        raise ValueError("STUN response too short")
    msg_type, length, magic = struct.unpack("!HHI", data[:8])
    if magic != STUN_MAGIC:
        raise ValueError("not a STUN message")
    if data[8:20] != transaction_id:
        raise ValueError("STUN transaction id does not match")
    if msg_type != STUN_BINDING_SUCCESS:
        raise ValueError(f"STUN error response (type 0x{msg_type:04x})")
    body = data[20:20 + length]
    found = {}
    offset = 0
    while offset + 4 <= len(body):
        attr_type, attr_len = struct.unpack("!HH", body[offset:offset + 4])
        value = body[offset + 4:offset + 4 + attr_len]
        if len(value) < attr_len:
            break
        if attr_type in (STUN_ATTR_XOR_MAPPED_ADDRESS, STUN_ATTR_XOR_MAPPED_ADDRESS_OLD):
            found.setdefault("xor", _parse_address(value, True, transaction_id))
        elif attr_type == STUN_ATTR_MAPPED_ADDRESS:
            found.setdefault("plain", _parse_address(value, False, transaction_id))
        offset += 4 + attr_len + (-attr_len % 4)    # attributes are padded to 4 bytes
    address = found.get("xor") or found.get("plain")
    if not address:
        raise ValueError("STUN response has no mapped address")
    return address


def _stun_exchange(sock, timeout):
    """Send one Binding Request on a connected UDP socket and wait for its answer.
    Returns (rtt_ms, (mapped_address, mapped_port)). Raises TimeoutError, OSError or ValueError."""
    message, transaction_id = stun_request()
    start = time.perf_counter()
    sock.send(message)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"no STUN answer within {timeout:g} s")
        sock.settimeout(remaining)
        try:
            data = sock.recv(2048)
        except socket.timeout as e:
            raise TimeoutError(f"no STUN answer within {timeout:g} s") from e
        rtt = _ms(start)
        try:
            return rtt, parse_stun_response(data, transaction_id)
        except ValueError as e:
            if "transaction id" in str(e) or "not a STUN" in str(e):
                continue                            # a late answer to an earlier request
            raise


def _udp_socket(host, port, timeout):
    family, sockaddr = _resolve(host, port, timeout, socktype=socket.SOCK_DGRAM)[0]
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.connect(sockaddr)
    except OSError:
        sock.close()
        raise
    return sock, sockaddr


def stun_binding(host, port=3478, timeout=2):
    """One STUN Binding Request over UDP. + address, local_address, local_port, mapped_address,
    mapped_port, nat ('none' when the server sees our local address, else 'nat')."""
    extra = {"address": None, "local_address": None, "local_port": None,
             "mapped_address": None, "mapped_port": None, "nat": None}
    try:
        sock, sockaddr = _udp_socket(host, port, timeout)
    except Exception as e:  # noqa: BLE001
        return _result(False, None, _error_text(e), **extra)
    try:
        extra["address"] = sockaddr[0]
        rtt, (mapped, mapped_port) = _stun_exchange(sock, timeout)
        local = sock.getsockname()
        extra.update(local_address=local[0], local_port=local[1], mapped_address=mapped, mapped_port=mapped_port,
                     nat="none" if mapped == local[0] else "nat")
        return _result(True, rtt, None, **extra)
    except Exception as e:  # noqa: BLE001
        return _result(False, None, _error_text(e), **extra)
    finally:
        sock.close()


def _series_summary(rtts):
    sent = len(rtts)
    received = [r for r in rtts if r is not None]
    lost = sent - len(received)
    jitter = (sum(abs(a - b) for a, b in zip(received, received[1:])) / (len(received) - 1)
              if len(received) > 1 else None)
    return {"sent": sent, "lost": lost, "rtts": rtts,
            "loss_pct": round(100 * lost / sent, 2) if sent else None,
            "avg_ms": round(sum(received) / len(received), 2) if received else None,
            "jitter_ms": round(jitter, 2) if jitter is not None else None}


def stun_series(host, port=3478, count=10, interval=1.0, cancel=None):
    """count STUN Binding Requests, one per interval, from one local port (like a media flow).
    {sent, lost, rtts: [ms|None], loss_pct, avg_ms, jitter_ms, error}; jitter is the mean absolute
    difference of consecutive received RTTs. Stops early when cancelled. Never raises."""
    rtts = []
    timeout = min(2.0, max(0.5, interval))
    try:
        sock, sockaddr = _udp_socket(host, port, timeout)
    except Exception as e:  # noqa: BLE001
        return {**_series_summary(rtts), "error": _error_text(e)}
    error = None
    try:
        for index in range(max(0, int(count))):
            if _cancelled(cancel):
                break
            started = time.monotonic()
            try:
                rtt, _mapped = _stun_exchange(sock, timeout)
                rtts.append(rtt)
            except (TimeoutError, ValueError):
                rtts.append(None)
            except OSError as e:                     # e.g. ICMP port unreachable on Windows
                rtts.append(None)
                error = _error_text(e)
            if index + 1 < count:
                wait = interval - (time.monotonic() - started)
                while wait > 0 and not _cancelled(cancel):
                    time.sleep(min(wait, 0.1))
                    wait = interval - (time.monotonic() - started)
    finally:
        sock.close()
    return {**_series_summary(rtts), "error": error}


# ---------------------------------------------------------------------------- local route

def _adapter_descriptions():
    if not sys.platform.startswith("win"):
        return {}
    try:
        from utils import winnet
        return {a["name"]: a for a in winnet.adapter_addresses() or []}
    except (OSError, ValueError, ImportError, AttributeError):
        return {}


def _is_vpn_adapter(name, description="", if_type=None):
    """Same name/description heuristics as network.health.check_virtual_adapters, plus PPP links."""
    from network.health import VPN_DESC_RE, VPN_NAME_RE
    return bool(VPN_NAME_RE.match(name or "") or VPN_DESC_RE.search(description or "")
                or if_type == WINDOWS_IF_TYPE_PPP)


def route_interface(ip):
    """{local_address, interface, description, is_vpn}: the local address and adapter the OS picks
    for packets to ip (a UDP socket is connected, nothing is sent). Fields are None when unknown."""
    result = {"local_address": None, "interface": None, "description": None, "is_vpn": None}
    try:
        address = ipaddress.ip_address(str(ip).split("%")[0])
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.connect((str(address), 9))
            local = sock.getsockname()[0]
        result["local_address"] = local
        for name, addrs in psutil.net_if_addrs().items():
            if any(a.address.split("%")[0] == local.split("%")[0] for a in addrs):
                result["interface"] = name
                break
        if result["interface"]:
            adapter = _adapter_descriptions().get(result["interface"], {})
            result["description"] = adapter.get("description") or None
            result["is_vpn"] = _is_vpn_adapter(result["interface"], adapter.get("description", ""),
                                               adapter.get("if_type"))
    except Exception as e:  # noqa: BLE001
        logging.debug(f"route_interface({ip}) failed: {e}")
    return result


# ---------------------------------------------------------------------------- running checks

def _remote_ip(kind, details):
    if kind == "dns":
        return (details.get("addresses") or [None])[0]
    return details.get("address")


def run_check(check, host):
    """Run one check against an already expanded host: the probe result dict. Never raises."""
    kind = check["kind"]
    if not check.get("verified", True):
        return _result(None, None, "untested: no public target is known to answer this probe")
    try:
        if kind == "dns":
            return dns_lookup(host)
        if kind == "tcp":
            return tcp_connect(host, check["port"])
        if kind == "tls":
            return tls_handshake(host, check["port"])
        if kind == "https":
            port = check["port"]
            return https_get(host if port == 443 else f"{host}:{port}", check.get("path", "/"))
        if kind in ("stun", "udp"):
            # A plain UDP port says nothing unless something answers; the only answer we can check
            # is a STUN Binding Response, so a verified "udp" check is a STUN check.
            return stun_binding(host, check["port"])
    except Exception as e:  # noqa: BLE001 (defensive; probes already catch everything)
        return _result(False, None, _error_text(e))
    return _result(None, None, f"unknown check kind '{kind}'")


def _make_result(service, check, host, probe):
    details = {k: v for k, v in probe.items() if k not in ("ok", "ms", "error")}
    return {"service_id": service["id"], "service_name": service["name"], "check_id": check["id"],
            "name": check["name"], "kind": check["kind"], "host": host, "port": check.get("port"),
            "ok": probe.get("ok"), "ms": probe.get("ms"), "error": probe.get("error"),
            "optimize": bool(check.get("optimize")), "verified": bool(check.get("verified", True)),
            "details": details}


def _live_category(values, endpoint_sets, protocol=None, port=None):
    """Highest Microsoft category of the host names / addresses in values, or None when none is listed."""
    best = None
    for value in values:
        if not value:
            continue
        category = classify_endpoint(value, endpoint_sets, protocol, port)
        if _CATEGORY_RANK.get(category, 0) > _CATEGORY_RANK.get(best, 0):
            best = category
    return best


def run_checks(services, tenant=None, cancel=None, callback=None, workers=8, endpoint_sets=None):
    """Run every check of services (load_services() output) in a thread pool.

    Checks whose host needs {tenant} are left out when no valid tenant is given. Results come back
    in definition order; callback(result) is called from worker threads as each check finishes.
    Checks not started before cancel is set are returned with ok None and error 'cancelled'.
    Optimize checks get details['route'] = route_interface(remote address).

    endpoint_sets: Microsoft's current endpoint list (fetch_m365_endpoints()['endpoint_sets']). When
    given, the highest category it lists for a check's host or connected address replaces the
    bundled 'optimize' flag (result['category'] and result['category_source'] = 'm365'); a check it
    does not list keeps the bundled flag (category_source 'bundled')."""
    jobs = []
    for service in services or []:
        for check in service.get("checks", []):
            host = expand_host(check["host"], tenant)
            if host is not None:
                jobs.append((service, check, host))
    if not jobs:
        return []

    def job(item):
        service, check, host = item
        if _cancelled(cancel):
            result = _make_result(service, check, host, _result(None, None, "cancelled"))
        else:
            probe = run_check(check, host)
            result = _make_result(service, check, host, probe)
            ip = _remote_ip(check["kind"], result["details"])
            if endpoint_sets:
                protocol = "udp" if check["kind"] in ("stun", "udp") else "tcp"
                category = _live_category((host, ip), endpoint_sets, protocol, check.get("port", 443))
                result["category"] = category
                result["category_source"] = "m365" if category else "bundled"
                if category:
                    result["optimize"] = category == "Optimize"
            if result["optimize"] and probe.get("ok") is not None and ip:
                result["details"]["route"] = route_interface(ip)
        if callback is not None:
            try:
                callback(result)
            except Exception as e:  # noqa: BLE001 (a GUI callback error must not stop the scan)
                logging.debug(f"office check callback failed: {e}")
        return result

    pool = _ProbePool(max(1, min(int(workers), len(jobs))), name="office-check")
    try:
        futures = [pool.submit(job, item) for item in jobs]
        return [future.result() for future in futures]
    finally:
        pool.shutdown(wait=False)


# ---------------------------------------------------------------------------- M365 endpoint list

def _m365_cache_path():
    return os.path.join(state_dir(), M365_CACHE_NAME)


def _client_request_id():
    """One random GUID per machine, reused for every call (the web service asks for this)."""
    path = os.path.join(state_dir(), M365_CLIENT_ID_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            return str(uuid.UUID(f.read().strip()))
    except (OSError, ValueError):
        pass
    value = str(uuid.uuid4())
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(value)
    except OSError as e:
        logging.debug(f"Cannot save the M365 client request id: {e}")
    return value


def parse_m365_endpoints(data):
    """Endpoint sets from the web service answer: list of dicts with id, serviceArea, category,
    urls, ips, tcpPorts, udpPorts, required. Raises OfficeServicesError on an unexpected format."""
    if not isinstance(data, list) or not data:
        raise OfficeServicesError("The Microsoft 365 endpoint list has an unexpected format.")
    sets = []
    for item in data:
        if not isinstance(item, dict) or "id" not in item or item.get("category") not in ("Optimize", "Allow",
                                                                                            "Default"):
            raise OfficeServicesError("The Microsoft 365 endpoint list has an unexpected format.")
        sets.append({"id": item["id"], "serviceArea": item.get("serviceArea"), "category": item["category"],
                     "required": bool(item.get("required")), "urls": list(item.get("urls") or []),
                     "ips": list(item.get("ips") or []), "tcpPorts": item.get("tcpPorts", ""),
                     "udpPorts": item.get("udpPorts", "")})
    return sets


def _read_cache():
    try:
        cache = _read_json(_m365_cache_path())
        return float(cache["fetched"]), parse_m365_endpoints(cache["endpoint_sets"])
    except (OSError, ValueError, KeyError, TypeError, OfficeServicesError):
        return None


def _bundled_endpoints(path=None):
    try:
        data = _read_json(path or _default_services_path())
        return parse_m365_endpoints(data["m365_fallback"]["endpoint_sets"])
    except (OSError, ValueError, KeyError, TypeError, OfficeServicesError):
        return []


def _download_endpoints(timeout):
    url = M365_ENDPOINTS_URL.format(guid=_client_request_id())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_m365_endpoints(json.loads(response.read().decode("utf-8")))


def _iso(epoch):
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds") if epoch else None


def fetch_m365_endpoints(timeout=10, force=False, now=None):
    """Microsoft 365 endpoint sets: {'source': 'cache'|'web'|'bundled', 'fetched': ISO time or None,
    'endpoint_sets': [...], 'error': str|None}.

    A cache younger than a day is used without a download (unless force). Otherwise the web service
    is asked; when that fails the cache of any age is used, then the Optimize sets bundled in
    office_services.json. Failed downloads are retried after one hour unless force is set.
    Never raises."""
    now = time.time() if now is None else now
    cached = _read_cache()
    if cached and not force and 0 <= now - cached[0] < M365_REFRESH_S:
        return {"source": "cache", "fetched": _iso(cached[0]), "endpoint_sets": cached[1], "error": None}
    failure_path = os.path.join(state_dir(), M365_FAILURE_NAME)
    try:
        failure = _read_json(failure_path)
        retry_later = 0 <= now - float(failure["failed"]) < M365_RETRY_S
        error = failure["error"]
        if not isinstance(error, str):
            retry_later = False
    except (OSError, ValueError, KeyError, TypeError):
        retry_later = False
    if retry_later and not force:
        if cached:
            return {"source": "cache", "fetched": _iso(cached[0]), "endpoint_sets": cached[1], "error": error}
        return {"source": "bundled", "fetched": None, "endpoint_sets": _bundled_endpoints(), "error": error}
    try:
        sets = _download_endpoints(timeout)
        try:
            os.remove(failure_path)
        except OSError:
            pass
        try:
            with open(_m365_cache_path(), "w", encoding="utf-8") as f:
                json.dump({"fetched": now, "endpoint_sets": sets}, f)
        except OSError as e:
            logging.debug(f"Cannot cache the Microsoft 365 endpoint list: {e}")
        return {"source": "web", "fetched": _iso(now), "endpoint_sets": sets, "error": None}
    except Exception as e:  # noqa: BLE001
        error = _error_text(getattr(e, "reason", None) or e)
        logging.info(f"Microsoft 365 endpoint list download failed: {error}")
        try:
            with open(failure_path, "w", encoding="utf-8") as f:
                json.dump({"failed": now, "error": error}, f)
        except OSError as save_error:
            logging.debug(f"Cannot save the M365 download failure: {save_error}")
    if cached:
        return {"source": "cache", "fetched": _iso(cached[0]), "endpoint_sets": cached[1], "error": error}
    return {"source": "bundled", "fetched": None, "endpoint_sets": _bundled_endpoints(), "error": error}


_CATEGORY_RANK = {"Optimize": 3, "Allow": 2, "Default": 1}


def _host_matches(host, pattern):
    host, pattern = host.lower().rstrip("."), pattern.lower().rstrip(".")
    if pattern.startswith("*."):
        return host.endswith(pattern[1:])
    if "*" in pattern:
        return re.fullmatch(re.escape(pattern).replace(r"\*", "[^.]*"), host) is not None
    return host == pattern


def _port_matches(ports, port):
    for part in str(ports or "").split(","):
        try:
            bounds = part.strip().split("-")
            if len(bounds) == 1 and int(bounds[0]) == port:
                return True
            if len(bounds) == 2 and int(bounds[0]) <= port <= int(bounds[1]):
                return True
        except (ValueError, TypeError):
            continue
    return False


def classify_endpoint(value, endpoint_sets, protocol=None, port=None):
    """Highest Microsoft category ('Optimize' > 'Allow' > 'Default') of a host name or IP address in
    the endpoint sets, or None when it is not listed (Microsoft: follow the highest category).
    When protocol and port are supplied, only sets listing that transport and port count."""
    best = None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        address = None
    for item in endpoint_sets or []:
        if protocol is not None and port is not None:
            if protocol not in ("tcp", "udp") or not _port_matches(item.get(protocol + "Ports"), port):
                continue
        if address is not None:
            hit = False
            for network in item.get("ips", []):
                try:
                    if address in ipaddress.ip_network(network, strict=False):
                        hit = True
                        break
                except ValueError:
                    continue
        else:
            hit = any(_host_matches(value, pattern) for pattern in item.get("urls", []))
        if hit and _CATEGORY_RANK.get(item["category"], 0) > _CATEGORY_RANK.get(best, 0):
            best = item["category"]
    return best
