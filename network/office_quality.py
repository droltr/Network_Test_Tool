"""Office apps analysis: call-quality estimate and rule-based diagnosis of where a problem is.

Pure functions only: no network access, no GUI, no system calls. The collectors (Wi-Fi, service
checks, ping/STUN probes, health scan) build a snapshot; this module turns it into findings and a
single verdict that says WHERE the problem is: Wi-Fi, local network/router, internet provider,
company network (VPN, proxy, firewall), the service itself, or this computer.

Snapshot (the single input to diagnose() and localize()):

    {
        "time": datetime,                         # when the snapshot was taken
        "connection": "wifi" | "ethernet" | "unknown",
        "wifi": status | None,                    # Wi-Fi status dict (see below)
        "congestion": dict | None,                # {same_channel, overlapping, strong_neighbors,
                                                  #  level: "low"|"medium"|"high"}
        "wifi_events": [ {time, kind, text, details}, ... ],
                                                  # kind: roam, ssid_change, disconnect, reconnect,
                                                  # signal_weak, signal_recovered, signal_drop,
                                                  # rate_drop, band_change
        "gateway": series | None,                 # ping series to the default gateway
        "dns": {"ok", "ms", "server"} | None,     # one lookup through the system resolver
        "internet": series | None,                # ping series to a public anycast (e.g. 1.1.1.1)
        "services": [check result, ...],          # service checks (see below)
        "media": {service_id: series},            # STUN series to Teams/Zoom media relays
        "health": [health check, ...] | None,     # network.health.run_scan() results
        "targets": {service_id: {"rtt_ms", "jitter_ms", "loss_pct"}},
    }

Wi-Fi status: {available, reason, message, interface, ssid, bssid, signal_percent, rssi_dbm,
band ("2.4 GHz"/"5 GHz"/"6 GHz"), channel, frequency_mhz, radio_type, rx_rate_mbps, tx_rate_mbps,
auth, connected}.

Series (see series_from_rtts): {sent, lost, rtts: [float | None per probe, None = lost], loss_pct,
avg_ms, jitter_ms}.

Service check result: {service_id, service_name, check_id, name, kind ("dns"/"tcp"/"tls"/"https"/
"stun"/"udp"), host, port, ok (True/False/None = untested), ms, error, optimize, verified,
details: {route: {local_address, interface, is_vpn}, via_proxy, nat, status, ...}}.

Finding: {id, layer, severity, title, summary, evidence: [str], fix}; layer is one of "wifi",
"local", "isp", "corporate", "service", "device" and severity one of "ok", "info", "warn", "fail".
A finding may carry "uncertain": True when the layer is a best guess because an upstream
measurement is missing.

Thresholds are rules of thumb for office calls and web apps, not standards. The MOS value is an
estimate from network numbers only; real call quality also depends on codec, CPU and audio devices.
"""
import ipaddress
from datetime import datetime

from network.monitor import _percentile

LAYERS = ("wifi", "local", "isp", "corporate", "service", "device")
LAYER_LABELS = {"none": "No problem found", "wifi": "Wi-Fi", "local": "Local network / router",
                "isp": "Internet provider", "corporate": "Company network (VPN, proxy, firewall)",
                "service": "Service (Microsoft 365, Teams, Zoom)", "device": "This computer",
                "inconclusive": "Inconclusive"}
SEVERITY_RANK = {"ok": 0, "info": 1, "warn": 2, "fail": 3}
SERVICE_LABELS = {"m365": "Microsoft 365", "teams": "Teams", "zoom": "Zoom", "outlook": "Outlook",
                  "onedrive": "OneDrive", "sharepoint": "SharePoint"}

# Fallback call targets when the snapshot has none for a service.
# Teams: Microsoft's network requirements from client to Microsoft edge (RTT < 100 ms,
# jitter < 30 ms, loss < 1 %). Zoom: Zoom's guidance for good quality (latency <= 150 ms,
# jitter <= 40 ms, loss <= 2 %).
DEFAULT_TARGETS = {"teams": {"rtt_ms": 100, "jitter_ms": 30, "loss_pct": 1.0},
                   "zoom": {"rtt_ms": 150, "jitter_ms": 40, "loss_pct": 2.0}}
GENERIC_TARGETS = {"rtt_ms": 150, "jitter_ms": 30, "loss_pct": 1.0}

MIN_PROBES = 10               # fewer probes say nothing reliable about loss
RSSI_WARN, RSSI_FAIL = -70, -80
LINK_RATE_WARN, LINK_RATE_FAIL = 24.0, 6.5     # Mbps, the slower of rx/tx
ROAMS_WARN = 3
DISCONNECTS_FAIL = 3
GATEWAY_LOSS_WARN, GATEWAY_LOSS_FAIL = 1.0, 5.0
GATEWAY_JITTER_WARN, GATEWAY_RTT_WARN = 20.0, 30.0
# Many routers, VPN gateways and guest networks drop or ignore ICMP echo. Gateway loss at or above
# this level while the internet loses (almost) nothing is a router that does not answer ping, not a
# bad link: the user's own traffic passes through it.
GATEWAY_SILENT_LOSS = 5.0
INTERNET_LOSS_WARN, INTERNET_LOSS_FAIL = 1.0, 5.0
INTERNET_JITTER_WARN, INTERNET_RTT_WARN = 30.0, 100.0
DNS_WARN_MS, DNS_FAIL_MS = 150.0, 1000.0
WIFI_BAD_EVENTS = ("roam", "disconnect", "signal_weak", "signal_drop", "rate_drop", "band_change")
MEDIA_KINDS = ("stun", "udp")
TCP_KINDS = ("tcp", "tls", "https")
CONNECT_KINDS = ("dns", "tcp", "tls", "https")

MS_GUIDANCE = ("Microsoft's Microsoft 365 network connectivity principles say to send 'Optimize' endpoints "
               "directly to the internet: bypass the VPN (split tunnel) and skip proxies and TLS inspection "
               "for them.")
ETHERNET_ADVICE = ("For important calls, use a network cable or sit closer to the access point. A cable removes "
                   "Wi-Fi signal, interference and roaming problems completely.")


# ---------------------------------------------------------------------------- series and MOS

def series_from_rtts(rtts):
    """Build a series dict from per-probe RTTs in ms (None = lost probe).

    Jitter is the mean absolute difference between consecutive received RTTs: a simplification of
    the RFC 3550 interarrival jitter (no 1/16 smoothing, lost probes skipped), the same formula the
    connection monitor uses. Extra keys min_ms, max_ms and p95_ms are included for reports.
    """
    rtts = [None if r is None else float(r) for r in (rtts or [])]
    received = [r for r in rtts if r is not None]
    sent = len(rtts)
    lost = sent - len(received)
    jitter = (sum(abs(a - b) for a, b in zip(received, received[1:])) / (len(received) - 1)
              if len(received) > 1 else None)
    return {"sent": sent, "lost": lost, "rtts": rtts,
            "loss_pct": round(100.0 * lost / sent, 2) if sent else 0.0,
            "avg_ms": round(sum(received) / len(received), 2) if received else None,
            "jitter_ms": round(jitter, 2) if jitter is not None else None,
            "min_ms": round(min(received), 2) if received else None,
            "max_ms": round(max(received), 2) if received else None,
            "p95_ms": round(_percentile(received, 0.95), 2) if received else None}


def estimate_mos(rtt_ms, jitter_ms, loss_pct):
    """Estimated MOS (1.0 - 4.5) for a voice call, from a simplified ITU-T G.107 E-model.

    effective latency = rtt / 2 + 2 * jitter + 10 ms (one-way delay, jitter buffer, codec)
    R = 93.2 - effective / 40               if effective < 160 ms
    R = 93.2 - (effective - 120) / 10       otherwise
    R -= 2.5 * loss_pct, clamped to 0 - 100
    MOS = 1 + 0.035 R + 7e-6 R (R - 60) (100 - R)

    This is an estimate from network numbers only; codec, packet loss concealment, CPU load and
    audio devices are not modelled. Missing values count as 0.
    """
    rtt, jitter, loss = max(0.0, rtt_ms or 0.0), max(0.0, jitter_ms or 0.0), max(0.0, loss_pct or 0.0)
    effective = rtt / 2 + 2 * jitter + 10
    r = 93.2 - effective / 40 if effective < 160 else 93.2 - (effective - 120) / 10
    r = min(100.0, max(0.0, r - 2.5 * loss))
    mos = 1 + 0.035 * r + 7e-6 * r * (r - 60) * (100 - r)
    return round(min(4.5, max(1.0, mos)), 2)


def mos_label(mos):
    """'Good' (>= 4.0), 'Fair' (>= 3.6), 'Poor' (>= 3.1) or 'Bad'; 'Unknown' for None.

    The bands follow the G.107 user-satisfaction bands (R 80 / 70 / 60).
    """
    if mos is None:
        return "Unknown"
    if mos >= 4.0:
        return "Good"
    if mos >= 3.6:
        return "Fair"
    if mos >= 3.1:
        return "Poor"
    return "Bad"


def series_mos(series):
    """Estimated MOS of a series, or None without received probes."""
    if not series or not series.get("sent") or series.get("avg_ms") is None:
        return None
    return estimate_mos(series["avg_ms"], series.get("jitter_ms"), series.get("loss_pct"))


def compare_targets(series, targets):
    """Compare a series with {'rtt_ms', 'jitter_ms', 'loss_pct'} targets.

    Returns {'ok', 'failures': [{'metric', 'value', 'target'}], 'measured'}. A metric that was not
    measured (no received probes) is skipped; a series without probes returns ok False and
    measured False.
    """
    if not series or not series.get("sent"):
        return {"ok": False, "failures": [], "measured": False}
    targets = targets or GENERIC_TARGETS
    values = {"rtt_ms": series.get("avg_ms"), "jitter_ms": series.get("jitter_ms"),
              "loss_pct": series.get("loss_pct")}
    failures = [{"metric": metric, "value": values[metric], "target": targets[metric]}
                for metric in ("rtt_ms", "jitter_ms", "loss_pct")
                if targets.get(metric) is not None and values[metric] is not None
                and values[metric] > targets[metric]]
    return {"ok": not failures, "failures": failures, "measured": True}


# ---------------------------------------------------------------------------- helpers

def _finding(fid, layer, severity, title, summary, evidence=None, fix="", uncertain=False):
    finding = {"id": fid, "layer": layer, "severity": severity, "title": title, "summary": summary,
               "evidence": list(evidence or []), "fix": fix}
    if uncertain:
        finding["uncertain"] = True
    return finding


def _ms(value):
    return "n/a" if value is None else f"{value:.0f} ms" if value >= 10 else f"{value:.1f} ms"


def _series_text(name, series):
    return (f"{name}: {series.get('loss_pct', 0):.1f}% loss ({series.get('lost', 0)}/{series.get('sent', 0)} "
            f"probes), average {_ms(series.get('avg_ms'))}, jitter {_ms(series.get('jitter_ms'))}")


def _measured(series):
    return bool(series) and (series.get("sent") or 0) >= MIN_PROBES


def _grade(series, loss_warn, loss_fail, jitter_warn, rtt_warn):
    """(severity, problems) for a ping series, or (None, []) when there are too few probes."""
    if not _measured(series):
        return None, []
    loss, jitter, avg = series.get("loss_pct") or 0.0, series.get("jitter_ms"), series.get("avg_ms")
    problems, severity = [], "ok"
    if loss >= loss_fail:
        severity = "fail"
        problems.append(f"{loss:.1f}% packet loss")
    elif loss >= loss_warn:
        severity = "warn"
        problems.append(f"{loss:.1f}% packet loss")
    if jitter is not None and jitter >= jitter_warn:
        severity = "fail" if severity == "fail" else "warn"
        problems.append(f"jitter {_ms(jitter)}")
    if avg is not None and avg >= rtt_warn:
        severity = "fail" if severity == "fail" else "warn"
        problems.append(f"average latency {_ms(avg)}")
    return severity, problems


def _silent_gateway(snapshot, gateway):
    """True when the gateway loses a lot but the traffic beyond it does not.

    Beyond = the internet series (or, without it, the best media relay series). The gateway counts as
    silent when it loses at least GATEWAY_SILENT_LOSS percent and the traffic beyond loses less than
    the internet 'fail' level and less than a quarter of the gateway loss. Matching loss on both
    (for example 10% and 8%) is a real local problem and stays a gateway finding.
    """
    if not _measured(gateway) or (gateway.get("loss_pct") or 0.0) < GATEWAY_SILENT_LOSS:
        return False
    beyond = snapshot.get("internet")
    if not _measured(beyond):
        relays = [s for s in (snapshot.get("media") or {}).values() if _measured(s) and s.get("avg_ms") is not None]
        beyond = min(relays, key=lambda s: s.get("loss_pct") or 0.0) if relays else None
    if beyond is None:
        return False
    loss = beyond.get("loss_pct") or 0.0
    return loss < INTERNET_LOSS_FAIL and loss < (gateway.get("loss_pct") or 0.0) / 4


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _clock(value):
    when = _as_datetime(value)
    return when.strftime("%H:%M:%S") if when else str(value)


def _rssi(wifi):
    """(rssi dBm, estimated) from the status; Windows only reports a percentage, so estimate from it."""
    if wifi.get("rssi_dbm") is not None:
        return wifi["rssi_dbm"], False
    if wifi.get("signal_percent") is not None:
        return round(wifi["signal_percent"] / 2 - 100), True
    return None, False


def _service_label(sid, checks=()):
    for c in checks:
        if c.get("service_id") == sid and c.get("service_name"):
            return c["service_name"]
    return SERVICE_LABELS.get(sid, sid)


def _check_text(check):
    target = f"{check.get('host')}:{check.get('port')}" if check.get("port") else str(check.get("host"))
    name = check.get("name") or check.get("check_id") or check.get("kind")
    if check.get("ok"):
        return f"{name} ({check.get('kind')} {target}): OK in {_ms(check.get('ms'))}"
    return f"{name} ({check.get('kind')} {target}): failed" + (f", {check['error']}" if check.get("error") else "")


def _is_private(address):
    try:
        return ipaddress.ip_address(str(address)).is_private
    except ValueError:
        return False


# ---------------------------------------------------------------------------- Wi-Fi rules

def _wifi_findings(snapshot, wifi):
    findings = []
    rssi, estimated = _rssi(wifi)
    band = wifi.get("band") or ""
    where = f"'{wifi.get('ssid')}'" if wifi.get("ssid") else "the access point"
    if rssi is not None:
        source = f" (estimated from {wifi.get('signal_percent')}% signal)" if estimated else ""
        evidence = [f"Signal: {rssi} dBm{source} on {band or 'unknown band'}"
                    + (f", channel {wifi['channel']}" if wifi.get("channel") else "")]
        if rssi <= RSSI_FAIL:
            findings.append(_finding("wifi_signal", "wifi", "fail", "Very weak Wi-Fi signal",
                                     f"The signal from {where} is {rssi} dBm. At {RSSI_FAIL} dBm or below, packets are "
                                     "lost and calls break up.", evidence,
                                     "Move closer to the access point or remove obstacles (walls, metal). "
                                     + ETHERNET_ADVICE))
        elif rssi <= RSSI_WARN:
            findings.append(_finding("wifi_signal", "wifi", "warn", "Weak Wi-Fi signal",
                                     f"The signal from {where} is {rssi} dBm. At {RSSI_WARN} dBm or below, video calls "
                                     "can stutter.", evidence,
                                     "Move closer to the access point, or ask IT whether this area needs another "
                                     "access point."))
        else:
            findings.append(_finding("wifi_signal", "wifi", "ok", "Wi-Fi signal",
                                     f"The signal is good ({rssi} dBm).", evidence))

    congestion = snapshot.get("congestion") or {}
    level = congestion.get("level")
    if level in ("medium", "high"):
        evidence = [f"Congestion level: {level}; {congestion.get('same_channel', 0)} network(s) on the same channel, "
                    f"{congestion.get('overlapping', 0)} overlapping, {congestion.get('strong_neighbors', 0)} strong "
                    f"neighbor(s)" + (f", channel {wifi['channel']} ({band})" if wifi.get("channel") else "")]
        if band.startswith("2.4") and level == "high":
            findings.append(_finding("wifi_congestion", "wifi", "warn", "Crowded 2.4 GHz channel",
                                     "This laptop uses the crowded 2.4 GHz band, where neighboring networks share "
                                     "the air time. Calls get jitter and short drops.", evidence,
                                     "Connect to the 5 GHz network of the same name (or ask IT to enable band "
                                     "steering). On 2.4 GHz only channels 1, 6 and 11 do not overlap."))
        else:
            findings.append(_finding("wifi_congestion", "wifi", "info", "Busy Wi-Fi channel",
                                     f"Other networks share this {band or 'Wi-Fi'} channel ({level} congestion).",
                                     evidence, "If calls stutter, try another access point or a 5 GHz network."))

    events = snapshot.get("wifi_events") or []
    roams = [e for e in events if e.get("kind") == "roam"]
    if len(roams) >= ROAMS_WARN:
        findings.append(_finding("wifi_roaming", "wifi", "warn", "Frequent roaming",
                                 f"The laptop switched access points {len(roams)} times. Every switch can drop a "
                                 "call for a moment.",
                                 [f"{_clock(e.get('time'))} {e.get('text') or 'roam'}" for e in roams[:6]],
                                 "Stay in one place during calls, or ask IT to check the access point coverage and "
                                 "roaming settings (802.11r/k/v). A cable avoids roaming entirely."))
    drops = [e for e in events if e.get("kind") == "disconnect"]
    if drops:
        findings.append(_finding("wifi_disconnects", "wifi", "fail" if len(drops) >= DISCONNECTS_FAIL else "warn",
                                 "Wi-Fi disconnects",
                                 f"Wi-Fi disconnected {len(drops)} time(s). Calls drop and apps reconnect each time.",
                                 [f"{_clock(e.get('time'))} {e.get('text') or 'disconnect'}" for e in drops[:6]],
                                 "Update the Wi-Fi driver and turn off power saving for the Wi-Fi adapter. If it "
                                 "keeps happening in one place, report the access point to IT."))

    rates = [r for r in (wifi.get("rx_rate_mbps"), wifi.get("tx_rate_mbps")) if r is not None]
    if rates:
        rate = min(rates)
        evidence = [f"Link rate: receive {wifi.get('rx_rate_mbps', 'n/a')} Mbps, transmit "
                    f"{wifi.get('tx_rate_mbps', 'n/a')} Mbps"
                    + (f" ({wifi['radio_type']})" if wifi.get("radio_type") else "")]
        rate_drops = [e for e in events if e.get("kind") == "rate_drop"]
        if rate_drops:
            evidence.append(f"{len(rate_drops)} link-rate drop(s) logged")
        if rate <= LINK_RATE_FAIL:
            findings.append(_finding("wifi_link_rate", "wifi", "fail", "Very low Wi-Fi link rate",
                                     f"The Wi-Fi link runs at only {rate:g} Mbps, the lowest rates Wi-Fi uses when "
                                     "the signal is poor.", evidence,
                                     "Move closer to the access point or switch to 5 GHz. " + ETHERNET_ADVICE))
        elif rate < LINK_RATE_WARN:
            findings.append(_finding("wifi_link_rate", "wifi", "warn", "Low Wi-Fi link rate",
                                     f"The Wi-Fi link runs at {rate:g} Mbps; screen sharing and video may suffer.",
                                     evidence, "Move closer to the access point or connect to a 5 GHz network."))
    return findings


LOCATION_FIX = ("Turn on Settings > Privacy & security > Location > 'Let desktop apps access your location', "
                "then test again.")


def _location_finding(wifi):
    """Info finding: Windows hides part of the Wi-Fi details without the Location permission."""
    rssi, _ = _rssi(wifi)
    visible = []
    if rssi is not None:
        visible.append(f"signal {rssi} dBm")
    if wifi.get("band"):
        visible.append(wifi["band"])
    if wifi.get("channel"):
        visible.append(f"channel {wifi['channel']}")
    if wifi.get("connected") and visible:
        evidence = ["Still visible: " + ", ".join(visible)]
        summary = ("Windows hides the network name (SSID), the access point (BSSID), the link rates and the "
                   "nearby networks from desktop apps without the Location permission. Signal, band and channel "
                   "were still measured, so roaming, link-rate and channel-congestion checks are incomplete.")
    else:
        evidence = ["No Wi-Fi details were readable"]
        summary = ("Windows hides the Wi-Fi details (SSID, BSSID, signal, link rates, nearby networks) from "
                   "desktop apps without the Location permission, so the Wi-Fi link could not be checked.")
    return _finding("wifi_location_permission", "wifi", "info", "Wi-Fi details hidden by Windows", summary,
                    evidence, LOCATION_FIX)


def _wifi_suspects(snapshot, wifi):
    """Reasons why Wi-Fi could explain loss to the gateway (empty when the link looks clean)."""
    reasons = []
    if not wifi:
        return reasons
    rssi, _ = _rssi(wifi)
    if rssi is not None and rssi <= RSSI_WARN:
        reasons.append(f"signal {rssi} dBm")
    congestion = snapshot.get("congestion") or {}
    if congestion.get("level") == "high":
        reasons.append(f"high channel congestion ({wifi.get('band') or 'unknown band'})")
    rates = [r for r in (wifi.get("rx_rate_mbps"), wifi.get("tx_rate_mbps")) if r is not None]
    if rates and min(rates) < LINK_RATE_WARN:
        reasons.append(f"link rate {min(rates):g} Mbps")
    events = [e for e in snapshot.get("wifi_events") or [] if e.get("kind") in WIFI_BAD_EVENTS]
    if events:
        kinds = sorted({e["kind"].replace("_", " ") for e in events})
        reasons.append(f"{len(events)} Wi-Fi event(s): {', '.join(kinds)}")
    return reasons


# ---------------------------------------------------------------------------- service rules

def _group_services(checks):
    groups = {}
    for check in checks:
        groups.setdefault(check.get("service_id") or "?", []).append(check)
    return groups


def _service_findings(snapshot, internet_state):
    checks = [c for c in snapshot.get("services") or [] if c.get("ok") is not None]
    findings = []
    if not checks:
        return findings
    groups = _group_services(checks)
    failing = {}
    for sid, items in groups.items():
        bad = [c for c in items if c.get("kind") in CONNECT_KINDS and c.get("ok") is False]
        if bad:
            failing[sid] = bad
    working = [sid for sid, items in groups.items()
               if sid not in failing and any(c.get("ok") for c in items if c.get("kind") in CONNECT_KINDS)]

    if failing:
        evidence = [f"{_service_label(sid, checks)}: {_check_text(c)}" for sid, bad in failing.items() for c in bad[:4]]
        evidence += [f"{_service_label(sid, checks)}: reachable" for sid in working]
        names = ", ".join(_service_label(sid, checks) for sid in failing)
        all_down = {sid for sid, bad in failing.items()
                    if not any(c.get("ok") for c in groups[sid] if c.get("kind") in CONNECT_KINDS)}
        severity = "fail" if all_down else "warn"
        cert_errors = [c for bad in failing.values() for c in bad
                       if c.get("kind") in ("tls", "https") and "certif" in str(c.get("error") or "").lower()]
        if internet_state == "bad":
            findings.append(_finding("services_unreachable", "isp", "info", "Services affected by internet loss",
                                     f"{names} could not be reached, which the internet loss explains.", evidence,
                                     "Fix the internet connection first, then test again."))
        elif cert_errors:
            findings.append(_finding("tls_inspection", "corporate", "warn", "TLS inspection breaks connections",
                                     f"Connections to {names} fail with certificate errors. A company proxy or "
                                     "security product that inspects TLS traffic usually causes this.", evidence,
                                     "Ask IT to exclude Microsoft 365, Teams and Zoom endpoints from TLS inspection. "
                                     + MS_GUIDANCE))
        elif len(failing) == 1 and (working or internet_state == "ok"):
            sid = next(iter(failing))
            label = _service_label(sid, checks)
            findings.append(_finding(f"service_{sid}", "service", severity, f"{label} not reachable",
                                     f"{label} {'cannot be reached' if all_down else 'is partly unreachable'} while "
                                     f"the internet{' and other services' if working else ''} work. The problem is "
                                     f"most likely on {label}'s side.", evidence,
                                     f"Check the {label} service status page (or the Microsoft 365 admin center "
                                     "Service health). If the service is up, ask IT whether a firewall blocks it."))
        else:
            uncertain = internet_state is None and not working
            findings.append(_finding("services_blocked", "corporate", severity, "Several services blocked",
                                     f"{names} cannot be reached although "
                                     + ("the internet works. " if not uncertain else "basic connectivity was not "
                                        "measured. ")
                                     + "A company firewall, proxy or web filter is the most likely cause; an outage "
                                     "at a shared provider is also possible.", evidence,
                                     "Ask IT to allow the Microsoft 365, Teams and Zoom endpoints (TCP 443 and the "
                                     "media ports) in the firewall and proxy.", uncertain=uncertain))
    else:
        tested = [c for c in checks if c.get("kind") in CONNECT_KINDS]
        if tested:
            slowest = max((c for c in tested if c.get("ms") is not None), key=lambda c: c["ms"], default=None)
            evidence = [f"{len(tested)} connection check(s) passed"
                        + (f"; slowest: {_check_text(slowest)}" if slowest else "")]
            findings.append(_finding("services_reachable", "service", "ok", "Services reachable",
                                     "All tested service endpoints answer.", evidence))
    return findings


def _udp_findings(snapshot):
    checks = [c for c in snapshot.get("services") or [] if c.get("ok") is not None]
    media = snapshot.get("media") or {}
    groups = _group_services(checks)
    blocked, open_ = [], []
    for sid in sorted(set(groups) | set(media)):
        items = groups.get(sid, [])
        udp = [c for c in items if c.get("kind") in MEDIA_KINDS]
        tcp_ok = [c for c in items if c.get("kind") in TCP_KINDS and c.get("ok")]
        series = media.get(sid)
        series_dead = _measured(series) and series.get("lost") == series.get("sent")
        udp_dead = (udp and not any(c.get("ok") for c in udp)) or (not udp and series_dead)
        label = _service_label(sid, checks)
        if udp_dead and tcp_ok:
            ev = [f"{label}: {_check_text(c)}" for c in udp[:3]]
            if series_dead:
                ev.append(f"{label}: {series['sent']} STUN probes to media relays, none answered")
            ev.append(f"{label}: {_check_text(tcp_ok[0])}")
            blocked.append((label, ev))
        elif udp and any(c.get("ok") for c in udp):
            ok_check = next(c for c in udp if c.get("ok"))
            open_.append(f"{label}: {_check_text(ok_check)}")
    if blocked:
        names = ", ".join(label for label, _ in blocked)
        return [_finding("udp_blocked", "corporate", "warn", "UDP media ports blocked",
                         f"UDP to the {names} media relays (port 3478) is blocked while HTTPS on TCP 443 works. "
                         "Calls still connect, but audio and video fall back to TCP, which adds delay and "
                         "stutters on any packet loss.", [line for _, ev in blocked for line in ev],
                         "Ask IT to allow outbound UDP 3478-3481 (Teams) and UDP 3478, 3479, 8801-8810 (Zoom) "
                         "to the service ranges.")]
    if open_:
        return [_finding("udp_open", "corporate", "ok", "UDP media ports open",
                         "Calls can use UDP for audio and video.", open_)]
    return []


def _routing_findings(snapshot):
    checks = [c for c in snapshot.get("services") or [] if c.get("optimize")]
    vpn, proxy = [], []
    for c in checks:
        details = c.get("details") or {}
        route = details.get("route") or {}
        target = f"{c.get('host')}{':' + str(c['port']) if c.get('port') else ''}"
        if route.get("is_vpn"):
            vpn.append(f"{target} goes through VPN interface '{route.get('interface') or '?'}'"
                       + (f" (local address {route['local_address']})" if route.get("local_address") else ""))
        if details.get("via_proxy"):
            proxy.append(f"{target} goes through the proxy")
    findings = []
    if vpn:
        findings.append(_finding("optimize_via_vpn", "corporate", "warn", "Teams/Microsoft 365 traffic uses the VPN",
                                 f"{len(vpn)} 'Optimize' endpoint(s) are routed through the VPN. The VPN adds delay "
                                 "and jitter to calls and often limits bandwidth.", vpn,
                                 "Ask IT to configure split tunneling for Microsoft 365 Optimize endpoints. "
                                 + MS_GUIDANCE))
    if proxy:
        findings.append(_finding("optimize_via_proxy", "corporate", "warn", "Teams/Microsoft 365 traffic uses a proxy",
                                 f"{len(proxy)} 'Optimize' endpoint(s) go through a proxy, which slows real-time "
                                 "traffic and can break Teams media.", proxy,
                                 "Ask IT to bypass the proxy for Microsoft 365 Optimize endpoints (PAC file or "
                                 "proxy bypass list). " + MS_GUIDANCE))
    if checks and not vpn and not proxy:
        findings.append(_finding("optimize_direct", "corporate", "ok", "Direct route for Microsoft 365",
                                 "Optimize endpoints go directly to the internet, as Microsoft recommends.",
                                 [f"{len(checks)} Optimize endpoint(s) checked"]))
    return findings


def _media_findings(snapshot, gateway_layer, internet_state):
    media = snapshot.get("media") or {}
    targets = snapshot.get("targets") or {}
    checks = snapshot.get("services") or []
    vpn_services = {c.get("service_id") for c in checks if ((c.get("details") or {}).get("route") or {}).get("is_vpn")}
    findings = []
    for sid, series in media.items():
        if not _measured(series) or series.get("avg_ms") is None:
            continue          # too few probes, or fully blocked (handled by the UDP rule)
        label = _service_label(sid, checks)
        target = targets.get(sid) or DEFAULT_TARGETS.get(sid) or GENERIC_TARGETS
        result = compare_targets(series, target)
        mos = series_mos(series)
        evidence = [_series_text(f"{label} media relay", series),
                    f"Estimated call quality: MOS {mos:.2f} ({mos_label(mos)})"]
        evidence += [f"{f['metric'].replace('_', ' ')} {f['value']:g} above the target {f['target']:g}"
                     for f in result["failures"]]
        if result["ok"]:
            findings.append(_finding(f"call_quality_{sid}", "service", "ok", f"{label} call quality",
                                     f"The path to the {label} media relays meets the call targets "
                                     f"(MOS {mos:.2f}, {mos_label(mos)}).", evidence))
            continue
        loss_target = target.get("loss_pct") or 1.0
        severity = "fail" if mos < 3.1 or (series.get("loss_pct") or 0) >= 3 * loss_target else "warn"
        uncertain = False
        if gateway_layer:
            layer, cause = gateway_layer, "The loss already starts between this computer and the router."
        elif internet_state == "bad":
            layer, cause = "isp", "The internet connection itself is losing packets."
        elif sid in vpn_services:
            layer, cause = "corporate", "This traffic goes through the VPN, which adds delay and jitter."
        elif internet_state == "ok":
            layer, cause = "service", ("The local network and internet look clean, so the path to the relays or "
                                       "the relays themselves are the cause.")
        else:
            layer, cause, uncertain = "service", "The internet path was not measured, so the cause is unclear.", True
        findings.append(_finding(f"call_quality_{sid}", layer, severity, f"{label} call quality below target",
                                 f"Calls on {label} will likely be {mos_label(mos).lower()} (MOS {mos:.2f}). {cause}",
                                 evidence, "Fix the layer named here first; then test again before a call.",
                                 uncertain=uncertain))
    return findings


# ---------------------------------------------------------------------------- health mapping

HEALTH_LAYERS = {"routes": "device", "adapters": "device", "dns": "device", "proxy": "corporate", "mtu": "local",
                 "ipv6": "device", "resolvconf": "device", "winsock": "device"}


def _merge_health(findings, health):
    by_id = {f["id"]: f for f in findings}
    for check in health or []:
        status, cid = check.get("status"), check.get("id")
        evidence = [f"Health scan: {check.get('summary')}"] + list(check.get("details") or [])[:4]
        # Merge into a finding that already covers the same thing instead of repeating it
        target = None
        if cid == "dns" and status in ("warn", "fail"):
            target = by_id.get("dns")
        elif cid == "proxy" and status == "warn":
            target = by_id.get("optimize_via_proxy")
        elif cid == "adapters" and status == "info":
            target = by_id.get("optimize_via_vpn")
        if target and target["severity"] in ("warn", "fail"):
            target["evidence"] += evidence
            continue
        if cid == "proxy" and status == "warn":
            # A configured proxy is normal in companies; it matters only if it carries Optimize traffic
            findings.append(_finding("health_proxy", "corporate", "info", check.get("title") or "Proxy settings",
                                     check.get("summary", ""), evidence, check.get("fix", "")))
        elif cid == "adapters" and status == "info":
            findings.append(_finding("health_adapters", "corporate", "info", "VPN connected",
                                     check.get("summary", ""), evidence,
                                     "If calls are poor, test once with the VPN disconnected. " + MS_GUIDANCE))
        elif status in ("warn", "fail"):
            findings.append(_finding(f"health_{cid}", HEALTH_LAYERS.get(cid, "device"), status,
                                     check.get("title") or cid, check.get("summary", ""), evidence,
                                     check.get("fix", "")))


# ---------------------------------------------------------------------------- diagnosis

def _connection(snapshot):
    connection = snapshot.get("connection") or "unknown"
    wifi = snapshot.get("wifi")
    if connection == "unknown" and wifi and wifi.get("connected"):
        return "wifi"
    return connection


def diagnose(snapshot):
    """Findings for a snapshot (see the module docstring), ordered by layer and severity."""
    snapshot = snapshot or {}
    findings = []
    connection = _connection(snapshot)
    wifi = snapshot.get("wifi") if connection == "wifi" else None
    blocked = bool(wifi) and wifi.get("reason") == "location_permission"
    if blocked:
        findings.append(_location_finding(wifi))
    # Under the Location privacy block the status has available False but, while connected, still
    # carries signal, channel and band: use that partial data instead of ignoring the Wi-Fi.
    if wifi and wifi.get("connected") is not False and (wifi.get("available", True)
                                                        or (blocked and wifi.get("connected"))):
        findings += _wifi_findings(snapshot, wifi)
    else:
        wifi = None

    addresses = snapshot.get("gateway_addresses") or []
    if len(addresses) > 1:
        findings.append(_finding("gateway_changed", "local", "info", "Default gateway changed during the recording",
                                 "The default gateway changed while recording (for example a VPN was connected or "
                                 "disconnected). The router figures cover the current gateway only; probes sent to "
                                 "the earlier gateway are not included.", ["Gateways seen: " + " -> ".join(addresses)]))

    # Gateway: the first hop. Loss here is Wi-Fi when Wi-Fi shows symptoms, else the router/LAN
    gateway = snapshot.get("gateway")
    gw_severity, gw_problems = _grade(gateway, GATEWAY_LOSS_WARN, GATEWAY_LOSS_FAIL, GATEWAY_JITTER_WARN,
                                      GATEWAY_RTT_WARN)
    gateway_layer = None
    gw_silent = _silent_gateway(snapshot, gateway)
    if gw_silent:
        # Not a failure and not part of the verdict: the router just does not answer ping.
        evidence = [_series_text("Gateway", gateway), _series_text("Internet", snapshot.get("internet"))
                    if _measured(snapshot.get("internet")) else "Traffic beyond the router answers normally"]
        findings.append(_finding("gateway_silent", "local", "info", "Router does not answer ping",
                                 "The router does not answer ping (or answers only some of the pings), so the local "
                                 "link could not be measured directly. The internet beyond it answers normally, so "
                                 "traffic is passing through the router. This is common for VPN gateways, some "
                                 "routers and guest networks.", evidence))
        gw_severity = None
    elif gw_severity in ("warn", "fail"):
        suspects = _wifi_suspects(snapshot, wifi) if connection == "wifi" else []
        evidence = [_series_text("Gateway", gateway)]
        if suspects:
            gateway_layer = "wifi"
            evidence.append("Wi-Fi symptoms at the same time: " + "; ".join(suspects))
            summary = (f"The link to your router has {', '.join(gw_problems)}, and the Wi-Fi shows matching "
                       "symptoms. The Wi-Fi connection is the cause.")
            fix = "Improve the Wi-Fi link (see the Wi-Fi findings). " + ETHERNET_ADVICE
        else:
            gateway_layer = "local"
            if connection == "wifi":
                evidence.append("Wi-Fi signal, rate and events look normal")
            summary = (f"The link to your router has {', '.join(gw_problems)}. "
                       + ("The Wi-Fi looks healthy, so the router or local network is the likely cause."
                          if connection == "wifi" else "The cable, network adapter, switch or router is the "
                                                       "likely cause."))
            fix = ("Restart the router or switch, try another cable or port, and update the network adapter driver. "
                   "In an office, report it to IT with these numbers.")
        findings.append(_finding("gateway_loss", gateway_layer, gw_severity, "Unstable link to the router",
                                 summary, evidence, fix))
    elif gw_severity == "ok":
        findings.append(_finding("gateway_loss", "local", "ok", "Link to the router",
                                 "The router answers without loss.", [_series_text("Gateway", gateway)]))

    # Internet: gateway clean but loss further out is the provider
    internet = snapshot.get("internet")
    in_severity, in_problems = _grade(internet, INTERNET_LOSS_WARN, INTERNET_LOSS_FAIL, INTERNET_JITTER_WARN,
                                      INTERNET_RTT_WARN)
    internet_state = None if in_severity is None else ("ok" if in_severity == "ok" else "bad")
    if in_severity in ("warn", "fail"):
        evidence = [_series_text("Internet", internet)]
        if gw_severity in ("warn", "fail"):
            evidence.append(_series_text("Gateway", gateway))
            findings.append(_finding("internet_loss", gateway_layer, "info", "Internet loss follows the local loss",
                                     f"The internet shows {', '.join(in_problems)}, which the problem on the link "
                                     "to the router already explains.", evidence,
                                     "Fix the local link first, then test again."))
        else:
            uncertain = gw_severity is None
            if gw_severity == "ok":
                evidence.append(_series_text("Gateway", gateway) + " (clean)")
                summary = (f"The router answers cleanly, but the internet shows {', '.join(in_problems)}. The "
                           "problem is in your internet provider's network (or the company's internet line).")
            else:
                evidence.append("Gateway: does not answer ping" if gw_silent else "Gateway: not measured")
                summary = (f"The internet shows {', '.join(in_problems)}. "
                           + ("The router does not answer ping" if gw_silent else "The router was not measured")
                           + ", so the local network cannot be ruled out; the internet provider is the most "
                           "likely cause.")
            findings.append(_finding("internet_loss", "isp", in_severity, "Internet connection unstable", summary,
                                     evidence, "Restart the modem; if it continues, report the loss and the times "
                                     "to your internet provider (in an office, to IT).", uncertain=uncertain))
    elif in_severity == "ok":
        findings.append(_finding("internet_loss", "isp", "ok", "Internet connection",
                                 "The internet answers without notable loss or delay.",
                                 [_series_text("Internet", internet)]))

    # DNS
    dns = snapshot.get("dns")
    if dns:
        server = dns.get("server") or "the DNS server"
        dns_layer = "local" if _is_private(dns.get("server")) else "isp"
        evidence = [f"DNS lookup via {server}: " + (f"{_ms(dns.get('ms'))}" if dns.get("ok") else "failed")]
        if dns.get("ok") is False:
            findings.append(_finding("dns", dns_layer, "fail", "Name lookups fail",
                                     f"{server} does not answer. Apps cannot find Microsoft 365, Teams or Zoom "
                                     "servers even when the connection works.", evidence,
                                     "Flush the DNS cache (ipconfig /flushdns) and renew the IP address; if it "
                                     "continues, ask IT or the provider to check the DNS server."))
        elif dns.get("ms") is not None and dns["ms"] > DNS_WARN_MS:
            severity = "fail" if dns["ms"] >= DNS_FAIL_MS else "warn"
            findings.append(_finding("dns", dns_layer, severity, "Slow name lookups",
                                     f"A DNS lookup took {_ms(dns['ms'])} (more than {DNS_WARN_MS:.0f} ms). Every "
                                     "new connection waits this long, so apps feel slow to load.", evidence,
                                     "Flush the DNS cache; if it stays slow, ask IT or the provider to check the "
                                     "DNS server, or use a faster one."))
        elif dns.get("ok"):
            findings.append(_finding("dns", dns_layer, "ok", "Name lookups",
                                     f"DNS answers in {_ms(dns.get('ms'))}.", evidence))

    findings += _service_findings(snapshot, internet_state)
    findings += _udp_findings(snapshot)
    findings += _routing_findings(snapshot)
    findings += _media_findings(snapshot, gateway_layer, internet_state)
    _merge_health(findings, snapshot.get("health"))

    if any(f["layer"] == "wifi" and f["severity"] in ("warn", "fail") for f in findings):
        band = (wifi or {}).get("band") or ""
        tip = " If a cable is not possible, prefer a 5 GHz network over 2.4 GHz." if band.startswith("2.4") else ""
        findings.append(_finding("use_ethernet", "wifi", "info", "Use a cable for calls",
                                 "The problems found are on the Wi-Fi link, which a network cable avoids." + tip,
                                 [f"Connection: Wi-Fi ({band or 'unknown band'})"], ETHERNET_ADVICE + tip))

    findings.sort(key=lambda f: (LAYERS.index(f["layer"]) if f["layer"] in LAYERS else len(LAYERS),
                                 -SEVERITY_RANK.get(f["severity"], 0)))
    return findings


def _has_data(snapshot):
    if _measured(snapshot.get("gateway")) or _measured(snapshot.get("internet")):
        return True
    if any(c.get("ok") is not None for c in snapshot.get("services") or []):
        return True
    return any(_measured(s) for s in (snapshot.get("media") or {}).values())


def localize(snapshot, findings=None):
    """Verdict {'layer', 'headline', 'text', 'tone', 'finding_ids'} for a snapshot.

    Picks the most upstream layer with a failing finding (wifi -> local -> isp -> corporate ->
    service -> device), considering 'fail' findings before 'warn' ones. Returns layer 'none' when
    everything measured is fine and 'inconclusive' when nothing useful was measured.
    """
    snapshot = snapshot or {}
    if findings is None:
        findings = diagnose(snapshot)
    problems = [f for f in findings if f.get("severity") in ("warn", "fail")]
    if not problems:
        if not _has_data(snapshot):
            return {"layer": "inconclusive", "headline": LAYER_LABELS["inconclusive"],
                    "text": "Not enough measurements to locate a problem. Run the test longer (at least "
                            f"{MIN_PROBES} probes) and make sure the gateway, internet and service checks ran.",
                    "tone": "neutral", "finding_ids": []}
        return {"layer": "none", "headline": LAYER_LABELS["none"],
                "text": "The Wi-Fi, local network, internet and tested services look healthy.",
                "tone": "good", "finding_ids": []}
    worst = "fail" if any(f["severity"] == "fail" for f in problems) else "warn"
    order = {layer: i for i, layer in enumerate(LAYERS)}
    candidates = [f for f in problems if f["severity"] == worst]
    layer = min((f["layer"] for f in candidates), key=lambda layer: order.get(layer, len(LAYERS)))
    in_layer = [f for f in problems if f["layer"] == layer]
    in_layer.sort(key=lambda f: -SEVERITY_RANK[f["severity"]])
    lead = in_layer[0]
    uncertain = all(f.get("uncertain") for f in in_layer)
    label = LAYER_LABELS.get(layer, layer)
    headline = f"{'Probably: ' if uncertain else 'Problem: '}{label}"
    text = f"{lead['title']}. {lead['summary']}"
    others = sorted({f["layer"] for f in problems if f["layer"] != layer}, key=lambda x: order.get(x, len(LAYERS)))
    if others:
        text += " Also check: " + ", ".join(LAYER_LABELS.get(o, o) for o in others) + "."
    tone = "warn" if uncertain or worst == "warn" else "bad"
    return {"layer": layer, "headline": headline, "text": text, "tone": tone,
            "finding_ids": [f["id"] for f in in_layer]}


# ---------------------------------------------------------------------------- correlation

EVENT_PHRASES = {"roam": "a roam to another access point", "disconnect": "a Wi-Fi disconnect",
                 "reconnect": "a Wi-Fi reconnect", "ssid_change": "a switch to another Wi-Fi network",
                 "band_change": "a Wi-Fi band change", "signal_recovered": "the signal recovering"}


def _event_phrase(event, samples):
    kind, details = event.get("kind"), event.get("details") or {}
    if kind in ("signal_weak", "signal_drop"):
        rssi = details.get("rssi_dbm")
        if rssi is None:
            when = _as_datetime(event.get("time"))
            near = [(abs((t - when).total_seconds()), d.get("rssi_dbm")) for t, d in samples
                    if when and d.get("rssi_dbm") is not None]
            rssi = min(near)[1] if near else None
        return f"signal drop to {rssi} dBm" if rssi is not None else "a signal drop"
    if kind == "rate_drop":
        rate = details.get("rate_mbps") or details.get("rx_rate_mbps") or details.get("tx_rate_mbps")
        return f"a link-rate drop to {rate:g} Mbps" if isinstance(rate, (int, float)) else "a link-rate drop"
    if kind == "roam" and details.get("bssid"):
        return f"a roam to access point {details['bssid']}"
    return EVENT_PHRASES.get(kind, event.get("text") or kind or "a Wi-Fi event")


def correlate(events, samples, window_s=5):
    """Link loss bursts in time series to Wi-Fi events.

    events: Wi-Fi events {time, kind, text, details}. samples: [(datetime, {'gateway': rtt|None,
    'internet': rtt|None, 'media': {sid: rtt|None}, 'rssi_dbm': int|None})] in time order.
    A burst is a run of consecutive lost probes on one series; bursts on different series that
    overlap or lie within window_s seconds are merged. An event links to a burst when it falls within
    window_s seconds of it. Without an event, a weak signal (<= -75 dBm) during the burst also links.
    Returns one sentence per linked burst plus a closing count of unlinked bursts.
    """
    samples = sorted(((t, d or {}) for t, d in samples or [] if _as_datetime(t)), key=lambda s: s[0])
    names = []
    for _t, data in samples:
        for key in ("gateway", "internet"):
            if key in data and key not in names:
                names.append(key)
        for sid in (data.get("media") or {}):
            if f"media:{sid}" not in names:
                names.append(f"media:{sid}")

    def value(data, name):
        if name.startswith("media:"):
            media = data.get("media") or {}
            return media.get(name[6:], 0) if name[6:] in media else 0
        return data.get(name, 0) if name in data else 0      # missing = not probed, not lost

    bursts = []
    for name in names:
        start = None
        for i, (when, data) in enumerate(samples):
            lost = value(data, name) is None
            if lost and start is None:
                start = i
            if start is not None and (not lost or i == len(samples) - 1):
                end = i if lost else i - 1
                bursts.append({"names": [name], "start": samples[start][0], "end": samples[end][0],
                               "count": end - start + 1, "first": start, "last": end})
                start = None
    bursts.sort(key=lambda b: b["start"])
    merged = []
    for burst in bursts:
        if merged and (burst["start"] - merged[-1]["end"]).total_seconds() <= window_s:
            last = merged[-1]
            last["end"] = max(last["end"], burst["end"])
            last["last"] = max(last["last"], burst["last"])
            last["first"] = min(last["first"], burst["first"])
            last["count"] = max(last["count"], burst["count"])
            last["names"] += [n for n in burst["names"] if n not in last["names"]]
        else:
            merged.append(dict(burst))

    def label(name):
        return f"{SERVICE_LABELS.get(name[6:], name[6:])} media" if name.startswith("media:") else name

    timed = [(when, e) for e in events or [] for when in [_as_datetime(e.get("time"))] if when]
    lines, unlinked = [], 0
    for burst in merged:
        what = " and ".join(label(n) for n in sorted(burst["names"], key=names.index))
        what = what[0].upper() + what[1:]
        size = f" ({burst['count']} probe{'s' if burst['count'] != 1 else ''})" if burst["count"] > 1 else ""
        head = f"{what} loss at {burst['start'].strftime('%H:%M:%S')}{size}"
        near = [e for when, e in timed
                if (burst["start"] - when).total_seconds() <= window_s
                and (when - burst["end"]).total_seconds() <= window_s]
        if near:
            phrases = []
            for event in near:
                phrase = _event_phrase(event, samples)
                if phrase not in phrases:
                    phrases.append(phrase)
            lines.append(f"{head} coincided with {' and '.join(phrases)}.")
            continue
        rssi = [d.get("rssi_dbm") for _t, d in samples[burst["first"]:burst["last"] + 1]
                if d.get("rssi_dbm") is not None]
        if rssi and min(rssi) <= -75:
            lines.append(f"{head} coincided with a weak signal of {min(rssi)} dBm (no Wi-Fi event logged).")
            continue
        unlinked += 1
    if unlinked:
        lines.append(f"{unlinked} other loss burst(s) had no Wi-Fi event or weak signal nearby, which points away "
                     "from Wi-Fi.")
    return lines
