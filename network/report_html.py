"""Self-contained HTML reports (Game connection diagnosis, Network health recording sessions and Office apps).

Pure rendering, no Qt: every function returns HTML text. A page is one file with inline CSS, system
font stacks, no scripts and no external requests, so it opens anywhere and can be mailed or printed.
Light and dark colours follow prefers-color-scheme (data-theme="light"/"dark" on <html> forces one).

Every dynamic value goes through esc(); markup that is already safe is wrapped in Raw.
"""
import html
import ipaddress
import math
import os
import re
import socket
from collections import deque
from datetime import datetime

MAX_STRIP_CELLS = 120

# ---------------------------------------------------------------------------- page shell

_TOKENS_LIGHT = ("--bg: #f5f6f8; --surface: #ffffff; --fg: #1b1f27; --muted: #5d6573; --line: #dde1e8; "
                 "--accent: #2f5fd0; --ok: #1f8a4c; --ok-bg: #e5f4ea; --warn: #b26a00; --warn-bg: #fdf1dc; "
                 "--bad: #c2362b; --bad-bg: #fbe5e2; --neutral: #5d6573; --neutral-bg: #eceef2;")
_TOKENS_DARK = ("--bg: #12151b; --surface: #1a1e26; --fg: #e6e9ef; --muted: #98a1b0; --line: #2b313c; "
                "--accent: #7fa2ff; --ok: #5cc98a; --ok-bg: #173022; --warn: #f0b24a; --warn-bg: #33270f; "
                "--bad: #ff7a6e; --bad-bg: #3a1a17; --neutral: #98a1b0; --neutral-bg: #222833; color-scheme: dark;")

CSS = """
:root { %(light)s
  --display: "Segoe UI Variable Display", "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
  --body: "Segoe UI", system-ui, -apple-system, Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: ui-monospace, "Cascadia Mono", Consolas, "SF Mono", Menlo, monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { %(dark)s } }
:root[data-theme="dark"] { %(dark)s }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.6 var(--body); }
.wrap { max-width: 860px; margin: 0 auto; padding: 32px 16px 64px; display: grid; gap: 28px; }
h1 { font: 700 clamp(26px, 5vw, 34px)/1.15 var(--display); margin: 0; }
h2 { font: 600 19px/1.3 var(--display); margin: 0 0 4px; }
p { margin: 0; max-width: 68ch; }
.meta { color: var(--muted); font-size: 13.5px; display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 8px; }
.mono, td.num, code { font-family: var(--mono); font-variant-numeric: tabular-nums; }
code { font-size: 0.92em; overflow-wrap: anywhere; }
.verdict { border: 1px solid var(--line); border-radius: 10px; padding: 18px 20px; display: grid; gap: 10px; }
.verdict .label { font: 600 12px/1 var(--body); letter-spacing: .08em; text-transform: uppercase; }
.verdict strong { font: 600 18px/1.4 var(--display); }
.verdict.good { background: var(--ok-bg); border-color: var(--ok); } .verdict.good .label { color: var(--ok); }
.verdict.warn { background: var(--warn-bg); border-color: var(--warn); } .verdict.warn .label { color: var(--warn); }
.verdict.bad { background: var(--bad-bg); border-color: var(--bad); } .verdict.bad .label { color: var(--bad); }
.verdict.neutral { background: var(--neutral-bg); } .verdict.neutral .label { color: var(--neutral); }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
.fact { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px;
  display: grid; gap: 2px; min-width: 0; }
.fact span { color: var(--muted); font-size: 12.5px; }
.fact b { font: 500 15px/1.4 var(--mono); overflow-wrap: anywhere; }
section { display: grid; gap: 12px; }
.tbl { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
table { border-collapse: collapse; width: 100%%; font-size: 14px; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
th, td.num, td .mono, td .pill { white-space: nowrap; }
th { font-weight: 500; color: var(--muted); font-size: 12.5px; }
th.num { text-align: right; }
tr:last-child td { border-bottom: 0; }
td.num { text-align: right; }
tr.muted td { color: var(--muted); }
.pill { display: inline-block; padding: 1px 8px; border-radius: 99px; font: 500 12.5px/1.6 var(--mono); }
.pill.ok { background: var(--ok-bg); color: var(--ok); }
.pill.warn { background: var(--warn-bg); color: var(--warn); }
.pill.bad { background: var(--bad-bg); color: var(--bad); }
.pill.neutral { background: var(--neutral-bg); color: var(--neutral); }
.na { color: var(--muted); }
.strip { display: grid; gap: 2px; }
.strip i { height: 18px; border-radius: 2px; background: var(--ok); opacity: .55; }
.strip i.warn { background: var(--warn); opacity: 1; }
.strip i.bad { background: var(--bad); opacity: 1; }
.strip i.none { background: var(--line); opacity: 1; }
.striprow { display: grid; grid-template-columns: 170px 1fr 64px; gap: 10px; align-items: center; font-size: 13px; }
.striprow > * { min-width: 0; overflow-wrap: anywhere; }
.striprow > :last-child { text-align: right; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; color: var(--muted); font-size: 12.5px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
.legend i.ok { background: var(--ok); opacity: .55; } .legend i.warn { background: var(--warn); }
.legend i.bad { background: var(--bad); }
ol.timeline { list-style: none; margin: 0; padding: 0; display: grid; border-left: 2px solid var(--line); }
ol.timeline li { position: relative; padding: 0 0 16px 18px; display: grid; gap: 4px; }
ol.timeline li::before { content: ""; position: absolute; left: -7px; top: 6px; width: 12px; height: 12px;
  border-radius: 50%%; background: var(--surface); border: 2px solid var(--muted); }
ol.timeline li.bad::before { border-color: var(--bad); background: var(--bad); }
ol.timeline li.warn::before { border-color: var(--warn); background: var(--warn); }
ol.timeline li.good::before { border-color: var(--ok); }
.time { font: 500 13px/1.4 var(--mono); color: var(--muted); }
ul.steps { margin: 0; padding-left: 20px; display: grid; gap: 6px; max-width: 70ch; }
.note { color: var(--muted); font-size: 13.5px; }
@media (max-width: 560px) {
  .striprow { grid-template-columns: 1fr 56px; }
  .striprow > :first-child { grid-column: 1 / -1; }
}
@media print {
  :root { %(light)s color-scheme: light; }
  body { background: #fff; font-size: 12px; }
  .wrap { max-width: none; padding: 0; gap: 18px; }
  section, .verdict, .facts, tr, .striprow { break-inside: avoid; }
  .tbl { overflow: visible; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
""" % {"light": _TOKENS_LIGHT, "dark": _TOKENS_DARK}


class Raw(str):
    """Markup that is already safe; esc() leaves it alone."""


def esc(value):
    """HTML-escaped text of any value (None is empty); Raw passes through."""
    if isinstance(value, Raw):
        return value
    return html.escape("" if value is None else str(value), quote=True)


def join(parts):
    return Raw("".join(esc(p) for p in parts))


def page(title, meta, body, extra_css=""):
    """A complete HTML document: title, a meta line (list of strings) and the body blocks.
    extra_css (trusted, static text) is appended to the shared style sheet."""
    meta_html = "".join(f"<span>{esc(m)}</span>" for m in meta if m)
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<meta name=\"generator\" content=\"Network Test Tool\">\n"
            f"<title>{esc(title)}</title>\n<style>{CSS}{extra_css}</style>\n</head>\n<body>\n<div class=\"wrap\">\n"
            f"<header><h1>{esc(title)}</h1><div class=\"meta\">{meta_html}</div></header>\n"
            + "\n".join(esc(b) for b in body if b) + "\n</div>\n</body>\n</html>\n")


def section(title, *blocks, note=None):
    inner = "".join(esc(b) for b in blocks if b)
    if note:
        inner += f"<p class=\"note\">{esc(note)}</p>"
    return Raw(f"<section><h2>{esc(title)}</h2>{inner}</section>")


def verdict_box(label, headline, text=None, tone="neutral"):
    tone = tone if tone in ("good", "warn", "bad", "neutral") else "neutral"
    body = f"<p>{esc(text)}</p>" if text else ""
    return Raw(f"<div class=\"verdict {tone}\"><div class=\"label\">{esc(label)}</div>"
               f"<strong>{esc(headline)}</strong>{body}</div>")


def fact_cards(facts):
    """facts: [(label, value)]; entries with an empty value are skipped."""
    cards = "".join(f"<div class=\"fact\"><span>{esc(k)}</span><b>{esc(v)}</b></div>"
                    for k, v in facts if v not in (None, ""))
    return Raw(f"<div class=\"facts\">{cards}</div>")


def timeline(events):
    """events: [{'time': display text, 'text', 'tone': good/warn/bad/neutral}]."""
    if not events:
        return Raw("<p class=\"note\">No events.</p>")
    items = []
    for e in events:
        tone = e.get("tone") if e.get("tone") in ("good", "warn", "bad") else ""
        items.append(f"<li class=\"{tone}\"><span class=\"time\">{esc(e.get('time'))}</span>"
                     f"<span>{esc(e.get('text'))}</span></li>")
    return Raw(f"<ol class=\"timeline\">{''.join(items)}</ol>")


def pill(text, tone="neutral"):
    return Raw(f"<span class=\"pill {esc(tone)}\">{esc(text)}</span>")


def table(headers, rows, numeric=(), muted_rows=()):
    """headers: column titles; rows: lists of cell values (Raw for markup); numeric: column indexes
    aligned right; muted_rows: row indexes shown in the muted colour."""
    num = ' class="num"'
    head = "".join(f"<th{num if i in numeric else ''}>{esc(h)}</th>" for i, h in enumerate(headers))
    body = []
    for r, row in enumerate(rows):
        cells = "".join(f"<td{num if i in numeric else ''}>{esc(c)}</td>" for i, c in enumerate(row))
        muted = ' class="muted"' if r in muted_rows else ''
        body.append(f"<tr{muted}>{cells}</tr>")
    return Raw(f"<div class=\"tbl\"><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
               "</table></div>")


def known_list(items):
    """items: [(True, text)] for verified facts and [(False, text)] for unknowns."""
    if not items:
        return Raw("")
    lis = "".join(f"<li><b>{'Verified' if known else 'Unknown'}:</b> {esc(text)}</li>" for known, text in items)
    return Raw(f"<ul class=\"steps\">{lis}</ul>")


def steps(items):
    return Raw("<ul class=\"steps\">" + "".join(f"<li>{esc(t)}</li>" for t in items) + "</ul>")


def note(text):
    return Raw(f"<p class=\"note\">{esc(text)}</p>")


def unique_base(folder, name, extensions):
    """Path folder/name, or folder/name-2, -3, ... so that no file base + extension exists yet; all
    files of one report share the base. Two saves within the same second no longer overwrite."""
    base = os.path.join(folder, name)
    number = 1
    while any(os.path.exists(base + ext) for ext in extensions):
        number += 1
        base = os.path.join(folder, f"{name}-{number}")
    return base


# ---------------------------------------------------------------------------- loss strips

def bucket_ranges(count, max_cells=MAX_STRIP_CELLS):
    """Split `count` consecutive probes into at most max_cells runs of equal size (the last one may be
    shorter): [(first, last)] index pairs, inclusive. One run per probe when count <= max_cells."""
    if count <= 0:
        return []
    size = max(1, math.ceil(count / max_cells))
    return [(start, min(count, start + size) - 1) for start in range(0, count, size)]


def strip_cells(series, max_cells=MAX_STRIP_CELLS):
    """series: [(time text, answered bool)]. Returns [{'first', 'last', 'sent', 'lost', 'tone'}]:
    tone 'ok' when nothing in the cell was lost, 'bad' when everything was, 'warn' in between."""
    cells = []
    for first, last in bucket_ranges(len(series), max_cells):
        chunk = series[first:last + 1]
        lost = sum(1 for _t, ok in chunk if not ok)
        tone = "ok" if lost == 0 else ("bad" if lost == len(chunk) else "warn")
        cells.append({"first": chunk[0][0], "last": chunk[-1][0], "sent": len(chunk), "lost": lost, "tone": tone})
    return cells


def loss_tone(percent):
    if percent is None:
        return "neutral"
    if percent <= 0:
        return "ok"
    return "warn" if percent < 5 else "bad"


def strip_row(label, series, max_cells=MAX_STRIP_CELLS):
    """One labelled strip with a loss pill. series: [(time text, answered bool)]."""
    cells = strip_cells(series, max_cells)
    marks = []
    for c in cells:
        when = c["first"] if c["sent"] == 1 else f"{c['first']} – {c['last']}"
        status = ("answered" if c["lost"] == 0 else "lost") if c["sent"] == 1 else f"{c['lost']}/{c['sent']} lost"
        marks.append(f"<i class=\"{c['tone']}\" title=\"{esc(when)} · {esc(status)}\"></i>")
    sent = len(series)
    lost = sum(1 for _t, ok in series if not ok)
    percent = 100 * lost / sent if sent else None
    pill_html = pill(f"{percent:.1f}%" if percent is not None else "—", loss_tone(percent))
    columns = max(1, len(cells))
    return Raw(f"<div class=\"striprow\"><span class=\"mono\">{esc(label)}</span>"
               f"<div class=\"strip\" style=\"grid-template-columns: repeat({columns}, 1fr)\">{''.join(marks)}</div>"
               f"{pill_html}</div>")


def strip_legend(series_length, max_cells=MAX_STRIP_CELLS):
    per_cell = math.ceil(series_length / max_cells) if series_length > max_cells else 1
    unit = "Each square is one ping." if per_cell == 1 else f"Each square is {per_cell} consecutive pings."
    return Raw(f"<p class=\"note\">{esc(unit)} Hover a square for its time.</p>"
               "<div class=\"legend\"><span><i class=\"ok\"></i>all answered</span>"
               "<span><i class=\"warn\"></i>some lost</span><span><i class=\"bad\"></i>all lost</span></div>")


# ---------------------------------------------------------------------------- formatting

def _dt(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def clock(value):
    when = _dt(value)
    return when.strftime("%H:%M:%S") if when else (str(value) if value else "")


def time_range(start, end):
    a, b = _dt(start), _dt(end)
    if not a:
        return ""
    text = a.strftime("%d %b %Y, %H:%M")
    if b:
        text += " – " + (b.strftime("%H:%M") if b.date() == a.date() else b.strftime("%d %b %Y, %H:%M"))
    return text


def ms(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f} ms"


def loss_pill(lost, sent):
    if not sent:
        return pill("—", "neutral")
    return pill(f"{lost}/{sent}", loss_tone(100 * lost / sent))


def percent(value):
    return "—" if value is None else f"{value:.1f}%"


def short_owner(owner):
    """'AS64500 - Example Networks Ltd, TR' -> 'Example Networks Ltd, TR'."""
    owner = (owner or "").strip()
    return owner.split(" - ", 1)[1] if " - " in owner else owner


def _raw_note(files, what):
    if not files:
        return None
    names = ", ".join(v for k, v in files.items() if k != "html")
    return f"Raw data ({what}, local only): {names}" if names else None


# ---------------------------------------------------------------------------- game connection report

_GAME_STEPS = {
    "none": ["No loss reached the server during this run. If the game still stutters, run the diagnosis "
             "while it happens: loss that comes in waves only shows up when it is measured at that moment.",
             "Compare with Detect server's game-stream figures: close to 64 bursts per second and no gaps over "
             "40 ms means the game traffic itself arrived smoothly."],
    "home": ["The loss starts at your router, so it is inside your home: try a cable instead of Wi-Fi, another "
             "cable or port, and restart the router.",
             "Check whether another device is uploading or downloading heavily during the game.",
             "Run the diagnosis again after each change to see whether the loss is gone."],
    "isp": ["The loss starts inside your internet provider's network. Send this page and the raw files to the "
            "provider's support, with the times of the loss.",
            "Repeat the diagnosis at a different time of day; loss only in the evening points to congestion."],
    "transit": ["The loss starts between your provider and Valve. Your provider can sometimes route around a bad "
                "transit network; send them this page.",
                "A different Valve region may take another path: compare the relay scan and pick a region "
                "without loss in the game's matchmaking settings."],
    "server": ["The loss appears only at Valve's relay, so there is nothing to fix at home or at your provider.",
               "Try another Valve region or play later; send this page to your provider only if other relays "
               "also lose packets."],
    "inconclusive": ["Run the diagnosis for at least two minutes, while the problem is noticeable.",
                     "Use Detect server's game-stream figures: they measure the game traffic itself and do not "
                     "depend on ping answers.",
                     "If the relay ignores ping, use the relay scan to compare other Valve relays."],
}

# Loss at home or at the provider is the user's to fix or report (bad); transit and Valve are out of reach (warn)
_ZONE_TONE = {"none": "good", "inconclusive": "neutral", "home": "bad", "isp": "bad", "transit": "warn",
              "server": "warn"}


def _is_private(address):
    from network.game_server import _is_private as private
    return private(address)


def _hop_series(samples, round_times):
    return [(clock(t), ms is not None) for t, ms in zip(round_times, samples)]


def _detection_matches(report, detection):
    """True when the captured game server (top peer) is the diagnosed target."""
    peers = (detection or {}).get("peers") or []
    if not peers:
        return False
    target_hop = next((h for h in report.get("hops") or [] if h.get("is_target")), None)
    addresses = {report.get("target"), target_hop.get("address") if target_hop else None}
    return peers[0].get("ip") in addresses


def _game_knowledge(report, detection, hops, target, verdict):
    items = []
    peers = (detection or {}).get("peers") or []
    matches = _detection_matches(report, detection)
    if peers:
        top = peers[0]
        relay = (detection or {}).get("relay")
        where = f" (Valve relay {relay.get('pop')} · {relay.get('desc')})" if relay else ""
        items.append((True, f"The game exchanged packets with {top['ip']}:{top['port']}{where} during a "
                            f"{(detection or {}).get('seconds', '?')} s passive capture."))
        if not matches:
            items.append((False, f"Whether the diagnosed target {report.get('target')} carries the game: the "
                                 f"capture saw {top['ip']} instead."))
    stream = (detection or {}).get("stream") or {} if matches else {}
    if stream.get("packets"):
        items.append((True, f"Game stream from the server: {stream.get('bursts_per_s')} bursts/s (expected "
                            f"{stream.get('expected_per_s')}), longest gap {ms(stream.get('max_gap_ms'))}, "
                            f"{stream.get('gaps_over_40ms')} gap(s) over 40 ms."))
    gateway = next((h for h in hops if h.get("gateway") and h.get("sent")), None)
    if gateway:
        items.append((True, f"Home network: your router ({gateway['address']}) lost {gateway['lost']} of "
                            f"{gateway['sent']} pings ({gateway['loss_percent']:.1f}%)."))
    public = [h for h in hops if h.get("address") and not _is_private(h["address"])]
    isp_asn = public[0].get("asn") if public else None
    isp_hops = [h for h in hops if h.get("sent") and not h.get("gateway") and not h.get("is_target")
                and h.get("lost", 0) < h["sent"]
                and ((isp_asn and h.get("asn") == isp_asn) or (_is_private(h["address"]) and
                                                               (not public or hops.index(h) < hops.index(public[0]))))]
    if isp_hops:
        worst = max(h["loss_percent"] for h in isp_hops)
        items.append((True, f"Your provider's routers that answer ping ({len(isp_hops)}) lost at most "
                            f"{worst:.1f}% of pings."))
    if target and target.get("sent"):
        items.append((True, f"The server ({target['address']}) lost {target['lost']} of {target['sent']} pings "
                            f"({target['loss_percent']:.1f}%), average {ms(target.get('avg_ms'))}."))
    unknown_owner = [h["address"] for h in public if not h.get("asn")]
    if unknown_owner:
        items.append((False, f"Owner of {', '.join(unknown_owner)}: not found in the ASN database, so it is not "
                             "verified which network it belongs to."))
    mute = [h["address"] for h in hops if h.get("address") and h.get("sent") and not h.get("is_target")
            and h.get("lost", 0) >= h["sent"]]
    if mute:
        items.append((False, f"{', '.join(mute)} answered the traceroute but not ping, so their loss cannot be "
                             "measured."))
    silent = sum(1 for h in hops if not h.get("address"))
    if silent:
        items.append((False, f"{silent} hop(s) answered neither the traceroute nor ping."))
    if verdict.get("zone") == "inconclusive":
        items.append((False, verdict.get("summary", "")))
    items.append((False, "Ping loss stands in for game-traffic loss: routers and servers may handle ping at a "
                         "lower priority, so the two can differ."))
    return items


def render_game_report(report, detection=None, scan=None, files=None):
    """HTML page of a PathDiagnosis.report(). detection: capture_game_peers() result (optionally with
    'relay'); scan: scan_relays() result; files: {'md', 'json', ...} file names for the raw-data note."""
    from network.game_server import ZONE_LABELS

    hops = report.get("hops") or []
    verdict = report.get("verdict") or {}
    zone = verdict.get("zone") or "inconclusive"
    target = next((h for h in hops if h.get("is_target")), None)
    matches = _detection_matches(report, detection)
    relay = report.get("relay") or ((detection or {}).get("relay") if matches else None) or {}
    round_times = report.get("round_times") or []
    started, ended = report.get("started"), report.get("ended")

    meta = [time_range(started, ended), f"Computer: {report.get('host') or socket.gethostname()}",
            "Measured by Network Test Tool"]
    rounds = len(round_times)
    detail = (f"{rounds} round(s) over {report.get('duration_s', 0)} s, one ping per hop every "
              f"{report.get('interval_s', 1.0):g} s.")
    blocks = [verdict_box(f"Result · {ZONE_LABELS.get(zone, zone)}", verdict.get("summary", ""), detail,
                          _ZONE_TONE.get(zone, "neutral"))]

    peers = (detection or {}).get("peers") or []
    detected = f"{peers[0]['ip']}:{peers[0]['port']}" if peers else None
    public = [h for h in hops if h.get("address") and not _is_private(h["address"])]
    isp = public[0] if public and public[0].get("asn") else None
    # The capture's stream figures describe the detected server; only show them for the diagnosed one
    stream = ((detection or {}).get("stream") or {}) if matches else {}
    facts = [("Server", detected if matches else report.get("target")),
             ("Detected game server", None if matches or not detection else
              (f"{detected} (not the diagnosed target)" if detected else "none seen")),
             ("Valve location", f"{relay.get('pop')} · {relay.get('desc')}" if relay else "unknown"),
             ("Internet provider", f"{short_owner(isp.get('owner')) or 'unknown'} · AS{isp['asn']}" if isp else
              "unknown"),
             ("Server loss", f"{target['loss_percent']:.1f}% ({target['lost']}/{target['sent']})"
              if target and target.get("sent") else "not measured"),
             ("Server latency", f"{ms(target.get('avg_ms'))} avg, {ms(target.get('jitter_ms'))} jitter"
              if target and target.get("avg_ms") is not None else None),
             ("Game stream", f"{stream.get('bursts_per_s')}/{stream.get('expected_per_s')} bursts/s, max gap "
                             f"{ms(stream.get('max_gap_ms'))}" if stream.get("packets") else None)]
    blocks.append(fact_cards(facts))

    events = []
    if detection and detection.get("started"):
        text = f"Passive capture ({detection.get('seconds', '?')} s): "
        if not peers:
            text += "no game traffic was seen"
        else:
            text += f"game traffic went to {detected}"
            if not matches:
                text += f", not the diagnosed target {report.get('target')}"
            elif stream.get("packets"):
                text += (f", inbound {stream.get('bursts_per_s')} bursts/s, longest gap "
                         f"{ms(stream.get('max_gap_ms'))}")
        events.append({"time": detection["started"], "text": text + ".", "tone": "neutral"})
    for e in report.get("events") or []:
        events.append(e)
    events.sort(key=lambda e: str(e.get("time")))
    shown = []
    for e in events:
        when = clock(e.get("time")) + (f" – {clock(e['end'])}" if e.get("end") and e.get("end") != e.get("time")
                                        else "")
        shown.append({"time": when, "text": e.get("text"), "tone": e.get("tone")})
    if len(shown) > 60:
        hidden = len(shown) - 59
        shown = shown[:59] + [{"time": "", "text": f"… and {hidden} more event(s) in the JSON file.",
                               "tone": "neutral"}]
    blocks.append(section("Timeline", timeline(shown)))

    if round_times:
        rows = []
        if target and target.get("samples"):
            rows.append(strip_row(f"Server {target['address']}", _hop_series(target["samples"], round_times)))
        gateway = next((h for h in hops if h.get("gateway") and h.get("samples") and not h.get("is_target")), None)
        if gateway:
            rows.append(strip_row(f"Router {gateway['address']}", _hop_series(gateway["samples"], round_times)))
        start = next((h for h in hops if verdict.get("hop") is not None and h.get("index") == verdict["hop"]
                      and h.get("samples") and not h.get("is_target") and not h.get("gateway")), None)
        if start:
            rows.append(strip_row(f"Hop {start['index']} {start['address']}",
                                  _hop_series(start["samples"], round_times)))
        for c in report.get("compare") or []:
            if c.get("samples"):
                rows.append(strip_row(f"{c.get('label')} (comparison)", _hop_series(c["samples"], round_times)))
        if rows:
            blocks.append(section("Loss over time", strip_legend(rounds), *rows))

    table_rows, muted = [], []
    for h in hops:
        owner = (f"{short_owner(h.get('owner')) or 'unknown owner'} · AS{h['asn']}" if h.get("asn") else
                 ("private network" if h.get("address") and _is_private(h["address"]) else
                  ("not in the ASN database" if h.get("address") else "")))
        if h.get("gateway"):
            owner = "Your router"
        if h.get("is_target"):
            owner += " (game server)"
        if not h.get("address"):
            muted.append(len(table_rows))
            table_rows.append([h.get("index"), "no reply", "", Raw("<span class=\"na\">silent</span>"), "—", "—", "—"])
            continue
        if h.get("sent") and h.get("lost", 0) >= h["sent"] and not h.get("is_target"):
            muted.append(len(table_rows))
            table_rows.append([h.get("index"), Raw(f"<span class=\"mono\">{esc(h['address'])}</span>"), owner,
                               Raw("<span class=\"na\">does not answer ping</span>"), "—", "—", "—"])
            continue
        table_rows.append([h.get("index"), Raw(f"<span class=\"mono\">{esc(h['address'])}</span>"), owner,
                           loss_pill(h.get("lost", 0), h.get("sent", 0)), ms(h.get("avg_ms")),
                           ms(h.get("p95_ms")), ms(h.get("jitter_ms"))])
    for c in report.get("compare") or []:
        table_rows.append(["—", Raw(f"<span class=\"mono\">{esc(c['address'])}</span>"), f"{c.get('label')} (comparison)",
                           loss_pill(c.get("lost", 0), c.get("sent", 0)), ms(c.get("avg_ms")), ms(c.get("p95_ms")),
                           ms(c.get("jitter_ms"))])
    blocks.append(section("Path to the server",
                          table(["Hop", "Address", "Network", "Loss", "Avg", "p95", "Jitter"], table_rows,
                                numeric=(3, 4, 5, 6), muted_rows=muted),
                          note="Routers often answer ping slowly or not at all because they handle it at low "
                               "priority. Loss at one hop that does not continue to the later hops is not a "
                               "problem; only loss that starts at a hop and persists to the server counts."))

    if scan:
        current = set(relay.get("ips") or []) if relay else set()
        scan_rows = []
        for r in scan:
            name = f"{r.get('desc')} ({r.get('pop')})" + (" · current" if r.get("ip") in current else "")
            scan_rows.append([name, Raw(f"<span class=\"mono\">{esc(r.get('ip'))}</span>"),
                              loss_pill(r.get("lost", 0), r.get("sent", 0)), ms(r.get("avg_ms")),
                              ms(r.get("p95_ms")), ms(r.get("jitter_ms"))])
        blocks.append(section("Valve relay scan", table(["Relay", "Address", "Loss", "Avg", "p95", "Jitter"],
                                                         scan_rows, numeric=(2, 3, 4, 5)),
                              note="One address per Valve location, pinged in parallel. A relay that ignores "
                                   "ping shows 100% loss without being down."))

    blocks.append(section("What we know, what we don't",
                          known_list(_game_knowledge(report, detection, hops, target, verdict))))
    blocks.append(section("Next steps", steps(_GAME_STEPS.get(zone, _GAME_STEPS["inconclusive"])),
                          note=_raw_note(files, "same folder as this page")))
    return page("Game connection report", meta, blocks)


# ---------------------------------------------------------------------------- network health session report

def _session_tone(verdict):
    text = (verdict or "").lower()
    if text.startswith("stable: no"):
        return "good"
    if text.startswith("unstable"):
        return "bad"
    if text.startswith("no data"):
        return "neutral"
    return "warn"


_TARGET_NAMES = {"gateway": "Router", "dns": "DNS server", "internet": "Internet", "custom": "Custom host"}


def _session_steps(report):
    outages = report.get("outages") or []
    layers = {o.get("layer") for o in outages}
    tone = _session_tone(report.get("verdict"))
    if tone == "good":
        return ["The connection was stable while recording. If problems come back, record a session while "
                "they happen; the times in the report make them easy to match.",
                "For problems in one game only, use the Game connection page: it measures the path to the "
                "game server, which this monitor does not watch."]
    result = []
    if "Local network" in layers:
        result.append("The router stopped answering: check the cable or Wi-Fi signal, the network adapter and "
                      "the router's power; restart the router if it happens again.")
    if "Internet provider" in layers:
        result.append("The router answered but the internet did not: the problem is at or beyond your provider. "
                      "Send this page with the outage times to the provider's support.")
    if "DNS" in layers:
        result.append("Name lookups failed while the internet answered: try another DNS server (for example "
                      "1.1.1.1 or 8.8.8.8).")
    if not result:
        result.append("Some probes were lost without full outages. Record a longer session to see whether the "
                      "loss repeats at certain times.")
    result.append("Record again after any change to confirm the problem is gone.")
    return result


def render_session_report(report, recorder=None, files=None):
    """HTML page of a SessionRecorder.report(). recorder supplies the per-round samples for the loss
    strips (without it the strips are left out); files: {'md', 'csv', ...} names for the raw-data note."""
    title = "Network health report"
    meta = [time_range(report.get("started"), report.get("ended")), f"Computer: {socket.gethostname()}",
            f"Session: {report['label']}" if report.get("label") else None, "Measured by Network Test Tool"]
    targets = report.get("targets") or {}
    outages = report.get("outages") or []
    internet = targets.get("internet") or {}
    gateway = targets.get("gateway") or {}
    duration = report.get("duration_s", 0)
    detail = (f"{report.get('rounds', 0)} rounds over {duration // 60} min {duration % 60} s; an outage is counted "
              f"after {report.get('outage_threshold_probes', 2)} failed probe(s) in a row.")
    blocks = [verdict_box("Result", report.get("verdict", "No data"), detail, _session_tone(report.get("verdict")))]
    blocks.append(fact_cards([
        ("Duration", f"{duration // 60} min {duration % 60} s"),
        ("Rounds", f"{report.get('rounds', 0)} · every {report.get('interval_s', 1):g} s"),
        ("Outages", str(len(outages))),
        ("Internet loss", percent(internet.get("loss_percent")) if internet else None),
        ("Internet jitter", ms(internet.get("jitter_ms")) if internet else None),
        ("Router loss", percent(gateway.get("loss_percent")) if gateway else None),
    ]))

    events = [{"time": report.get("started"), "text": "Recording started.", "tone": "neutral"}]
    for o in outages:
        name = _TARGET_NAMES.get(o.get("target"), o.get("target"))
        state = "still down when the recording ended" if o.get("ongoing") else f"down for {o.get('duration_s')} s"
        events.append({"time": o.get("start"), "end": o.get("end"), "tone": "bad",
                       "text": f"{name} {state} (layer: {o.get('layer')})."})
    for c in report.get("changes") or []:
        events.append({"time": c.get("time"), "text": c.get("message"), "tone": "warn"})
    if not outages:
        events.append({"time": report.get("started"), "end": report.get("ended"), "tone": "good",
                       "text": f"No outages in {report.get('rounds', 0)} rounds."})
    events.append({"time": report.get("ended"), "text": "Recording ended.", "tone": "neutral"})
    events.sort(key=lambda e: str(e.get("time")))
    blocks.append(section("Timeline", timeline([
        {"time": clock(e.get("time")) + (f" – {clock(e['end'])}" if e.get("end") else ""), "text": e.get("text"),
         "tone": e.get("tone")} for e in events])))

    samples = getattr(recorder, "samples", None) or []
    if samples:
        rows = []
        for name in targets:
            series = [(clock(when), bool(results[name]["ok"])) for when, results in samples if name in results]
            label = f"{_TARGET_NAMES.get(name, name)} {targets[name].get('address', '')}".strip()
            rows.append(strip_row(label, series))
        blocks.append(section("Loss over time", strip_legend(len(samples)), *rows))

    table_rows = []
    for name, t in targets.items():
        table_rows.append([_TARGET_NAMES.get(name, name), Raw(f"<span class=\"mono\">{esc(t.get('address'))}</span>"),
                           loss_pill(t.get("lost", 0), t.get("probes", 0)), ms(t.get("min_ms")), ms(t.get("avg_ms")),
                           ms(t.get("p95_ms")), ms(t.get("max_ms")), ms(t.get("jitter_ms")), t.get("outages", 0),
                           f"{t.get('downtime_s', 0):.1f} s"])
    blocks.append(section("Targets", table(["Target", "Address", "Loss", "Min", "Avg", "p95", "Max", "Jitter",
                                            "Outages", "Downtime"], table_rows, numeric=tuple(range(2, 10))),
                          note="Layers: Local network = the router did not answer (cable, Wi-Fi, adapter or "
                               "router); Internet provider = the router answered but the internet did not; DNS = "
                               "the internet answered but name lookups failed."))

    known = []
    for name, t in targets.items():
        known.append((True, f"{_TARGET_NAMES.get(name, name)} ({t.get('address')}): {t.get('lost', 0)} of "
                            f"{t.get('probes', 0)} probes lost ({t.get('loss_percent', 0):.1f}%), "
                            f"{t.get('outages', 0)} outage(s)."))
    if any(o.get("ongoing") for o in outages):
        known.append((False, "How long the outage that was still running at the end lasted."))
    if any(o.get("layer") == "Internet provider" for o in outages):
        known.append((False, "Where inside the provider's network the outages happened: the monitor only sees "
                             "that the router answered and the internet did not."))
    known.append((False, "Game servers and other paths: the monitor probes the router, DNS and internet test "
                         "hosts only."))
    blocks.append(section("What we know, what we don't", known_list(known)))
    blocks.append(section("Next steps", steps(_session_steps(report)),
                          note=_raw_note(files, "same folder as this page")))
    return page(title, meta, blocks)


# ---------------------------------------------------------------------------- privacy masking

class _Masker:
    """Stable placeholders across one report: the same MAC or public IP gets the same MAC_n /
    PUBLIC_IP_n everywhere. Same rules as network.ai_handoff.redact (whose patterns and list of
    well-known public resolvers it reuses); the computer name becomes HOSTNAME."""

    def __init__(self, hostname=None):
        from network.ai_handoff import IPV4_RE, KEEP_PUBLIC, MAC_RE
        self.mac_re, self.ip_re, self.keep = MAC_RE, IPV4_RE, KEEP_PUBLIC
        self.host_re = (re.compile(r"(?<![\w-])" + re.escape(hostname) + r"(?![\w-])", re.IGNORECASE)
                        if hostname and len(hostname) > 1 else None)
        self.macs, self.ips = {}, {}

    def _mac(self, match):
        value = match.group(0).lower().replace("-", ":")
        if value in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
            return match.group(0)
        return self.macs.setdefault(value, f"MAC_{len(self.macs) + 1}")

    def _ip(self, match):
        value = match.group(0)
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return value
        if not address.is_global or value in self.keep:
            return value
        return self.ips.setdefault(value, f"PUBLIC_IP_{len(self.ips) + 1}")

    def text(self, value):
        if self.host_re is not None:
            value = self.host_re.sub("HOSTNAME", value)
        return self.ip_re.sub(self._ip, self.mac_re.sub(self._mac, value))

    def walk(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {k: self.walk(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, deque)):
            return [self.walk(v) for v in value]
        return value


def mask_private(data, hostname=None):
    """Deep copy of data (dicts, lists, strings) with public IPv4 addresses, MAC addresses (BSSIDs)
    and the computer name replaced by stable placeholders. Datetimes and numbers pass through.
    hostname defaults to this computer's name."""
    return _Masker(socket.gethostname() if hostname is None else hostname).walk(data)


# ---------------------------------------------------------------------------- office apps report

_OFFICE_CSS = """
.findings { display: grid; gap: 10px; }
h3 { font: 600 15.5px/1.3 var(--display); margin: 8px 0 0; color: var(--muted); }
.finding { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px;
  display: grid; gap: 6px; min-width: 0; }
.finding .head { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; }
.finding .head b { font: 600 15px/1.4 var(--display); }
.finding ul { margin: 0; padding-left: 20px; font-size: 13.5px; color: var(--muted); overflow-wrap: anywhere; }
.finding .fix { font-size: 13.5px; }
@media print { .finding { break-inside: avoid; } }
"""

_SEVERITY_TONE = {"fail": "bad", "warn": "warn", "info": "neutral", "ok": "ok"}
_SEVERITY_TEXT = {"fail": "problem", "warn": "warning", "info": "information", "ok": "ok"}
SILENT_ROUTER_TEXT = "does not answer ping (normal for many routers); the path beyond it is fine"
_EVENT_TONE = {"outage": "bad", "service_failed": "bad", "dns_failed": "bad", "disconnect": "bad",
               "signal_weak": "warn", "signal_drop": "warn", "rate_drop": "warn", "roam": "warn",
               "band_change": "warn", "ssid_change": "warn", "gateway_change": "warn",
               "restore": "good", "service_restored": "good", "dns_restored": "good", "reconnect": "good",
               "signal_recovered": "good"}
_CONNECTION_TEXT = {"wifi": "Wi-Fi", "ethernet": "Ethernet (cable)"}


def _series_fact(series):
    if not series or not series.get("sent"):
        return "not measured"
    text = f"{series.get('loss_pct', 0):.1f}% loss · {ms(series.get('avg_ms'))} avg"
    if series.get("jitter_ms") is not None:
        text += f" · {ms(series.get('jitter_ms'))} jitter"
    return text


def _gateway_notes(report):
    """(silent, addresses): the router answers no ping (finding gateway_silent) and the default gateways
    seen during the recording when it changed (empty list when it did not)."""
    ids = {f.get("id") for f in report.get("findings") or []}
    snap = report.get("snapshot") or {}
    addresses = [str(a) for a in snap.get("gateway_addresses") or []]
    changed = "gateway_changed" in ids or snap.get("gateway_changed") or len(addresses) > 1
    return "gateway_silent" in ids, (addresses if changed else [])


def _finding_card(f):
    tone = _SEVERITY_TONE.get(f.get("severity"), "neutral")
    head = (f"<div class=\"head\">{pill(_SEVERITY_TEXT.get(f.get('severity'), f.get('severity')), tone)}"
            f"<b>{esc(f.get('title'))}</b>"
            + (f"{pill('uncertain', 'neutral')}" if f.get("uncertain") else "") + "</div>")
    body = f"<p>{esc(f.get('summary'))}</p>"
    if f.get("evidence"):
        body += "<ul>" + "".join(f"<li>{esc(e)}</li>" for e in f["evidence"]) + "</ul>"
    if f.get("fix") and f.get("severity") != "ok":
        body += f"<p class=\"fix\"><b>Fix:</b> {esc(f['fix'])}</p>"
    return f"<div class=\"finding\">{head}{body}</div>"


def _office_findings(findings):
    from network.office_quality import LAYER_LABELS, LAYERS
    if not findings:
        return Raw("<p class=\"note\">No findings: nothing was measured that the rules could judge.</p>")
    parts = []
    layers = list(LAYERS) + sorted({str(f.get("layer")) for f in findings if f.get("layer") not in LAYERS})
    for layer in layers:
        items = [f for f in findings if str(f.get("layer")) == layer]
        if items:
            parts.append(f"<h3>{esc(LAYER_LABELS.get(layer, layer))}</h3>")
            parts.append("".join(_finding_card(f) for f in items))
    return Raw(f"<div class=\"findings\">{''.join(parts)}</div>")


def m365_list_text(info):
    """Short text on where the Microsoft 365 address list of an Office report came from, e.g.
    'downloaded 2026-11-14', 'cached copy from 2026-11-13' or 'bundled copy (download failed: timed out)';
    None when the report has no such information."""
    if not isinstance(info, dict) or not info.get("source"):
        return None
    day = str(info.get("fetched") or "")[:10]
    error = f" (download failed: {info['error']})" if info.get("error") else ""
    if info["source"] == "web":
        return "downloaded" + (f" {day}" if day else "")
    if info["source"] == "cache":
        return "cached copy" + (f" from {day}" if day else "") + error
    return "bundled copy" + error


def _office_facts(report, snap):
    from network.office_quality import SERVICE_LABELS, mos_label, series_mos
    route = snap.get("route") or {}
    connection = _CONNECTION_TEXT.get(snap.get("connection"), "Unknown")
    if route.get("is_vpn"):
        connection += " · VPN"
    facts = [("Connection", connection)]
    wifi = snap.get("wifi") or {}
    if snap.get("connection") == "wifi" or wifi.get("connected"):
        blocked = wifi.get("reason") == "location_permission"
        facts.append(("Wi-Fi network", wifi.get("ssid") or ("hidden by Windows (Location permission)" if blocked
                                                             else "unknown")))
        if wifi.get("rssi_dbm") is not None:
            facts.append(("Wi-Fi signal", f"{wifi['rssi_dbm']} dBm"
                          + (f" ({wifi['signal_percent']}%)" if wifi.get("signal_percent") is not None else "")))
        if wifi.get("band") or wifi.get("channel"):
            facts.append(("Band · channel", f"{wifi.get('band') or '?'} · channel {wifi.get('channel') or '?'}"))
        rates = (wifi.get("rx_rate_mbps"), wifi.get("tx_rate_mbps"))
        if any(r is not None for r in rates):
            facts.append(("Link rate", f"{rates[0] if rates[0] is not None else '—'} / "
                                       f"{rates[1] if rates[1] is not None else '—'} Mbps"))
        congestion = snap.get("congestion") or {}
        if congestion.get("level") and snap.get("nearby"):
            facts.append(("Channel congestion", f"{congestion['level']} ({congestion.get('same_channel', 0)} on the "
                                                f"same channel)"))
    silent, gateways = _gateway_notes(report)
    router = _series_fact(snap.get("gateway"))
    if silent and (snap.get("gateway") or {}).get("sent"):
        router = f"{router.split(' · ')[0]}, {SILENT_ROUTER_TEXT}"
    facts.append(("Router", router))
    if gateways:
        facts.append(("Default gateway", "changed during the recording: " + " -> ".join(gateways)
                      if len(gateways) > 1 else "changed during the recording"))
    facts.append(("Internet", _series_fact(snap.get("internet"))))
    dns = snap.get("dns")
    if dns:
        facts.append(("DNS lookup", ms(dns.get("ms")) if dns.get("ok") else "failed"))
    media = snap.get("media") or {}
    for sid, series in media.items():
        mos = series_mos(series)
        facts.append((f"{SERVICE_LABELS.get(sid, sid)} call quality",
                      f"MOS {mos:.2f} ({mos_label(mos)})" if mos is not None else
                      ("no answer from the relay" if series.get("sent") else "not measured")))
    checked = {c.get("service_id") for c in snap.get("services") or []}
    for sid in sorted(str(s) for s in checked - set(media)):
        facts.append((f"{SERVICE_LABELS.get(sid, sid)} call quality", "not measurable"))
    proxy = snap.get("proxy")
    if proxy is not None:
        facts.append(("Proxy", "configured" if proxy.get("configured") else "none"))
    listing = m365_list_text(snap.get("m365_endpoints"))
    if listing:
        facts.append(("Microsoft 365 address list", listing))
    if report.get("kind") == "session":
        duration = report.get("duration_s") or 0
        facts.append(("Recorded", f"{duration // 60} min {duration % 60} s · {len(report.get('samples') or [])} rounds"))
        facts.append(("Outages", str(len(report.get("outages") or []))))
    return fact_cards(facts)


def _office_measurements(snap, silent=False):
    from network.office_quality import SERVICE_LABELS, mos_label, series_mos
    rows, muted = [], []
    entries = [("Router", snap.get("gateway"), False), ("Internet", snap.get("internet"), False)]
    entries += [(f"{SERVICE_LABELS.get(sid, sid)} media relay (STUN)", s, True)
                for sid, s in (snap.get("media") or {}).items()]
    for name, series, is_media in entries:
        if not series or not series.get("sent"):
            muted.append(len(rows))
            rows.append([name, "—", Raw("<span class=\"na\">not measured</span>"), "—", "—", "—", "—"])
            continue
        mos = series_mos(series) if is_media else None
        rows.append([name, Raw(f"<span class=\"mono\">{esc(series.get('address') or '—')}</span>"),
                     (pill(f"{series.get('lost', 0)}/{series.get('sent', 0)} (no ping reply)", "neutral")
                      if silent and name == "Router" else loss_pill(series.get("lost", 0), series.get("sent", 0))),
                     ms(series.get("avg_ms")),
                     ms(series.get("p95_ms")), ms(series.get("jitter_ms")),
                     f"{mos:.2f} ({mos_label(mos)})" if mos is not None else "—"])
    return table(["Target", "Address", "Loss", "Avg", "p95", "Jitter", "Est. MOS"], rows, numeric=(2, 3, 4, 5),
                 muted_rows=muted)


def _office_checks(checks):
    from network.office_quality import SERVICE_LABELS
    rows, muted = [], []
    for c in checks:
        if c.get("ok") is None:
            result = pill("untested", "neutral")
            muted.append(len(rows))
        elif c.get("ok"):
            result = pill("ok", "ok")
        else:
            result = pill("failed", "bad")
        details = c.get("details") or {}
        notes = []
        if c.get("error"):
            notes.append(str(c["error"]))
        if (details.get("route") or {}).get("is_vpn"):
            notes.append("through the VPN")
        if details.get("via_proxy"):
            notes.append("through the proxy")
        if c.get("optimize"):
            notes.append("Optimize endpoint")
        target = f"{c.get('host')}:{c.get('port')}" if c.get("port") else str(c.get("host"))
        rows.append([SERVICE_LABELS.get(c.get("service_id"), c.get("service_name")), c.get("name"), c.get("kind"),
                     Raw(f"<span class=\"mono\">{esc(target)}</span>"), result, ms(c.get("ms")), "; ".join(notes)])
    return table(["Service", "Check", "Kind", "Target", "Result", "Time", "Note"], rows, numeric=(5,),
                 muted_rows=muted)


def _office_knowledge(report, snap):
    from network.office_quality import SERVICE_LABELS
    items = []
    silent, gateways = _gateway_notes(report)
    for name, key in (("Router", "gateway"), ("Internet", "internet")):
        series = snap.get(key)
        if silent and key == "gateway" and series and series.get("sent"):
            items.append((True, f"Router ({series.get('address') or '?'}): {series.get('lost', 0)} of "
                                f"{series.get('sent')} pings lost; the router {SILENT_ROUTER_TEXT}."))
        elif series and series.get("sent"):
            items.append((True, f"{name} ({series.get('address') or '?'}): {series.get('lost', 0)} of "
                                f"{series.get('sent')} pings lost ({series.get('loss_pct', 0):.1f}%)."))
        else:
            items.append((False, f"{name}: not measured."))
    if gateways:
        items.append((True, "The default gateway changed during the recording"
                            + (f" ({' -> '.join(gateways)})" if len(gateways) > 1 else "")
                            + "; the router figures cover the current gateway only."))
    for sid, series in (snap.get("media") or {}).items():
        if series.get("sent"):
            items.append((True, f"{SERVICE_LABELS.get(sid, sid)} media relay:{series.get('lost', 0)} of "
                                f"{series.get('sent')} STUN probes on UDP {series.get('port') or 3478} lost."))
    checks = snap.get("services") or []
    tested = [c for c in checks if c.get("ok") is not None]
    if tested:
        failed = [c for c in tested if not c.get("ok")]
        items.append((True, f"{len(tested)} service check(s) ran, {len(failed)} failed."))
    for c in checks:
        if not c.get("verified", True):
            items.append((False, f"{SERVICE_LABELS.get(c.get('service_id'), c.get('service_name'))} "
                                 f"{c.get('name')}: not verifiable, no public server is known to answer this probe."))
    checked = {str(c.get("service_id")) for c in checks}
    for sid in sorted(checked - set(snap.get("media") or {})):
        if not any(c.get("service_id") == sid and not c.get("verified", True) and c.get("kind") in ("udp", "stun")
                   for c in checks):
            items.append((False, f"{SERVICE_LABELS.get(sid, sid)} call quality: no media relay to probe."))
    wifi = snap.get("wifi") or {}
    if wifi.get("reason") == "location_permission":
        items.append((False, "Wi-Fi details hidden by the Windows Location permission: network name (SSID), access "
                             "point (BSSID), link rates and nearby networks. Roaming and channel congestion could not "
                             "be checked."))
    if not report.get("tenant"):
        items.append((False, "Your own SharePoint and OneDrive sites: not tested (no tenant name given)."))
    items.append((False, "The MOS value is an estimate from network numbers only (simplified ITU-T G.107 E-model); "
                         "codec, CPU load and audio devices also affect calls."))
    items.append((False, "Real calls may use other relays and ports than the probed ones; the probes show the "
                         "path quality at the time of the test only."))
    return items


def _office_steps(findings):
    fixes = []
    for f in findings:
        if f.get("severity") in ("warn", "fail") and f.get("fix") and f["fix"] not in fixes:
            fixes.append(f["fix"])
    if not fixes:
        return ["Nothing to fix from these measurements. If calls or apps still misbehave, record a session while "
                "the problem happens; the times in the report then match the problem.",
                "Run the quick test again on another network (for example a phone hotspot) to compare."]
    return fixes[:6] + ["Test again after each change to confirm the problem is gone."]


def _office_timeline(report):
    events = [{"time": report.get("started"), "text": "Recording started.", "tone": "neutral"}]
    for e in report.get("events") or []:
        events.append({"time": e.get("time"), "text": e.get("text"),
                       "tone": _EVENT_TONE.get(e.get("kind"), "neutral")})
    events.append({"time": report.get("ended"), "text": "Recording ended.", "tone": "neutral"})
    events.sort(key=lambda e: _dt(e.get("time")) or datetime.min)
    shown = [{"time": clock(e.get("time")), "text": e.get("text"), "tone": e.get("tone")} for e in events]
    if len(shown) > 60:
        hidden = len(shown) - 59
        shown = shown[:58] + [{"time": "", "text": f"… and {hidden} more event(s) in the JSON file.",
                               "tone": "neutral"}, shown[-1]]
    return timeline(shown)


def _office_strips(report, snap):
    from network.office_quality import SERVICE_LABELS
    samples = report.get("samples") or []
    if not samples:
        return None
    rows = []
    gateway = [(clock(s.get("time")), s.get("gateway") is not None) for s in samples
               if "gateway" not in (s.get("skipped") or ())]
    if gateway:
        rows.append(strip_row(f"Router {snap.get('gateway_address') or ''}".strip(), gateway))
    rows.append(strip_row(f"Internet {snap.get('internet_host') or ''}".strip(),
                          [(clock(s.get("time")), s.get("internet") is not None) for s in samples]))
    sids = []
    for s in samples:
        sids += [sid for sid in (s.get("media") or {}) if sid not in sids]
    for sid in sids:
        series = [(clock(s.get("time")), (s.get("media") or {}).get(sid) is not None) for s in samples
                  if sid in (s.get("media") or {})]
        rows.append(strip_row(f"{SERVICE_LABELS.get(sid, sid)} media", series))
    return section("Loss over time", strip_legend(len(samples)), *rows)


def render_office_report(report, files=None):
    """HTML page of an Office apps quick test or recording session (network.office_session report).
    Public IPs, MAC addresses (BSSIDs) and the computer name are masked; SSIDs are shown.
    files: {'md', 'json', ...} file names for the raw-data note."""
    from network.office_quality import LAYER_LABELS
    report = mask_private(report or {})
    snap = report.get("snapshot") or {}
    verdict = report.get("verdict") or {}
    findings = report.get("findings") or []
    session = report.get("kind") == "session"
    title = "Office apps recording" if session else "Office apps quick test"
    meta = [time_range(report.get("started"), report.get("ended")),
            f"Session: {report['label']}" if report.get("label") else None,
            f"Tenant: {report['tenant']}" if report.get("tenant") else None,
            "Measured by Network Test Tool"]
    layer = verdict.get("layer") or "inconclusive"
    if session:
        duration = report.get("duration_s") or 0
        detail = (f"{len(report.get('samples') or [])} rounds over {duration // 60} min {duration % 60} s, one probe "
                  f"per target every {report.get('interval_s', 1):g} s; service checks every "
                  f"{report.get('service_check_every_s', 60):g} s.")
    else:
        detail = (f"{report.get('probes', '?')} probes per target, one every {report.get('interval_s', 0.5):g} s, "
                  "plus one pass of the service checks.")
    text = f"{verdict.get('text', '')} {detail}".strip()
    blocks = [verdict_box(f"Result · {LAYER_LABELS.get(layer, layer)}", verdict.get("headline") or "No result",
                          text, verdict.get("tone") or "neutral"),
              _office_facts(report, snap)]
    if session:
        blocks.append(section("Timeline", _office_timeline(report)))
        strips = _office_strips(report, snap)
        if strips:
            blocks.append(strips)
        correlations = report.get("correlations") or []
        blocks.append(section("Loss and Wi-Fi events",
                              steps(correlations) if correlations else note("No loss bursts were recorded."),
                              note="A loss burst is linked to a Wi-Fi event or a weak signal within 5 seconds of it."))
    blocks.append(section("Findings", _office_findings(findings)))
    blocks.append(section("Measurements", _office_measurements(snap, _gateway_notes(report)[0]),
                          note="Router and internet: ICMP echo. Media relays: STUN Binding Requests over UDP, the "
                               "way Teams checks its media path. Est. MOS is a 1-4.5 call-quality estimate."))
    if session and report.get("outages"):
        rows = []
        for o in report["outages"]:
            rows.append([clock(o.get("start")), "still down at the end" if o.get("ongoing") else clock(o.get("end")),
                         f"{o.get('duration_s') or 0:g} s", o.get("name") or o.get("target"),
                         LAYER_LABELS.get(o.get("layer"), o.get("layer"))])
        blocks.append(section("Outages", table(["Start", "End", "Duration", "Target", "Likely layer"], rows,
                                               numeric=(2,)),
                              note="An outage is two or more lost probes in a row."))
    checks = snap.get("services") or []
    if checks:
        blocks.append(section("Service checks", _office_checks(checks),
                              note="Each check is one name lookup, TCP connect, TLS handshake, HTTPS request or STUN "
                                   "request; no sign-in and no user data. In a recording, a check that failed at "
                                   "least once shows its last failure."))
    if report.get("errors"):
        blocks.append(section("Not measured", steps(report["errors"])))
    blocks.append(section("What we know, what we don't", known_list(_office_knowledge(report, snap))))
    raw = _raw_note(files, "same folder as this page")
    if session and report.get("log_path"):
        live = os.path.basename(str(report["log_path"]))
        raw = (raw + "; " if raw else "") + f"live log: {live} (in the app's office-logs folder)"
    blocks.append(section("Next steps", steps(_office_steps(findings)), note=raw))
    return page(title, meta, blocks, extra_css=_OFFICE_CSS)

