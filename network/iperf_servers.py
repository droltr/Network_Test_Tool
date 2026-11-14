"""Public iperf3 server list.

Source: "Public iPerf3 Serverlist" by R0GGER (https://github.com/R0GGER/public-iperf3-servers,
MIT License), JSON export at https://export.iperf3serverlist.net. A snapshot ships in
assets/data/iperf3-servers.json; refresh() downloads the current export into the user's
state directory. See THIRD_PARTY_NOTICES.md.
"""
import json
import os
import urllib.request
from datetime import date

from utils.paths import resource_path, state_dir

EXPORT_URL = "https://export.iperf3serverlist.net/listed_iperf3_servers.json"
SOURCE_URL = "https://github.com/R0GGER/public-iperf3-servers"
BUNDLED = resource_path("assets", "data", "iperf3-servers.json")


def _cache_path():
    return os.path.join(state_dir(), "iperf3-servers.json")


def parse_ports(text):
    """'5201' -> [5201]; '5201-5209' -> [5201, ..., 5209]."""
    text = str(text or "").strip()
    try:
        if "-" in text:
            low, high = (int(p) for p in text.split("-", 1))
            return list(range(low, high + 1)) if 0 < low <= high <= 65535 else [5201]
        return [int(text)] if text else [5201]
    except ValueError:
        return [5201]


def normalize(raw):
    """Convert the export's records into this app's format."""
    servers = []
    for entry in raw:
        host = str(entry.get("IP/HOST", "")).strip()
        if not host:
            continue
        options = [o.strip() for o in str(entry.get("OPTIONS", "")).split(",") if o.strip()]
        servers.append({
            "host": host,
            "ports": str(entry.get("PORT", "5201")).strip() or "5201",
            "reverse": "-R" in options,
            "udp": "-u" in options,
            "ipv6": "-6" in options,
            "gbps": str(entry.get("GB/S", "")).strip(),
            "continent": str(entry.get("CONTINENT", "")).strip(),
            "country": str(entry.get("COUNTRY", "")).strip(),
            "site": str(entry.get("SITE", "")).strip(),
            "provider": str(entry.get("PROVIDER", "")).strip(),
        })
    return servers


def _wrap(servers):
    return {"source": SOURCE_URL, "export": EXPORT_URL, "license": "MIT",
            "fetched": date.today().isoformat(), "servers": servers}


def load():
    """The newest available list: the downloaded copy if present, else the bundled snapshot."""
    for path in (_cache_path(), BUNDLED):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("servers"):
                return data
        except (OSError, ValueError):
            continue
    return _wrap([])


def refresh(timeout=15):
    """Download the current export; returns the new list or raises OSError/ValueError."""
    request = urllib.request.Request(EXPORT_URL, headers={"User-Agent": "network-test-tool"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = json.loads(response.read().decode("utf-8"))
    if not isinstance(raw, list):
        raise ValueError("unexpected server list format")
    data = _wrap(normalize(raw))
    if not data["servers"]:
        raise ValueError("the downloaded server list is empty")
    with open(_cache_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data
