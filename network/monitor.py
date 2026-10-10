"""Connection monitor: probes gateway, DNS and the internet on a fixed interval and records
every outage with its start, end, duration and the layer that failed.

Outage layers (decided in the tick where the outage starts):
- "Local network": the gateway does not answer (cable, Wi-Fi, adapter or router).
- "Internet provider": the gateway answers but external hosts do not.
- "DNS": external hosts answer but name resolution does not.
Interface state, IP address and default gateway changes are recorded as events too.
"""
import csv
import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import psutil

from network.detector import NetworkDetector
from network.health import dns_query
from utils.paths import command_env

EXTERNAL_HOSTS = ("1.1.1.1", "8.8.8.8")


def ping_once(host, timeout=1):
    """Round-trip time in ms, or None."""
    if os.name == "nt":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, int(timeout))), host]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2, env=command_env(),
                                encoding="cp850" if os.name == "nt" else None)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"time[=<]\s*([\d.]+)\s*ms", result.stdout, re.IGNORECASE)
    return float(match.group(1)) if match else 0.0


class ConnectionMonitor:
    """Run with run() in a worker thread; stop() ends it.

    callback(kind, data) receives:
      'sample'  {'time', 'results': {target: {'ok', 'ms', 'address'}}}
      'outage'  {'target', 'layer', 'start', ...}           (outage started)
      'restore' {'target', 'layer', 'start', 'end', 'duration'}
      'change'  {'time', 'message'}
      'error'   message
    """

    def __init__(self, interval=1.0, fail_threshold=2, extra_host=None, log_dir=None, callback=None):
        self.interval = max(0.5, float(interval))
        self.fail_threshold = max(1, int(fail_threshold))
        self.extra_host = (extra_host or "").strip() or None
        self.log_dir = log_dir
        self.callback = callback or (lambda kind, data: None)
        self._stop = threading.Event()
        self.detector = NetworkDetector()
        self.started = None
        self.samples = 0
        self.stats = {}            # target -> {'sent', 'ok', 'ms_sum'}
        self.fail_streak = {}
        self.open_outages = {}     # target -> outage dict
        self.events = []
        self.sample_file = None
        self.event_file = None
        self.csv_path = None

    def stop(self):
        self._stop.set()

    # ---------------------------------------------------------------- probes
    def _targets(self):
        gateways = [g for g in self.detector.get_default_gateway() if g not in ("N/A", "0.0.0.0")]
        dns = [d for d in self.detector.get_dns_servers() if d != "N/A"]
        targets = {"gateway": gateways[0] if gateways else None,
                   "dns": dns[0] if dns else None,
                   "internet": ", ".join(EXTERNAL_HOSTS)}
        if self.extra_host:
            targets["custom"] = self.extra_host
        return targets

    def _probe(self, name, address):
        if not address:
            return {"ok": False, "ms": None, "address": "none"}
        if name == "dns":
            answered, ms, _rcode = dns_query(address, timeout=min(2.0, self.interval * 1.5))
            return {"ok": answered, "ms": ms, "address": address}
        if name == "internet":
            # Either public resolver answering counts; both down means the internet is unreachable
            for host in EXTERNAL_HOSTS:
                ms = ping_once(host)
                if ms is not None:
                    return {"ok": True, "ms": ms, "address": host}
            return {"ok": False, "ms": None, "address": address}
        ms = ping_once(address)
        return {"ok": ms is not None, "ms": ms, "address": address}

    # ---------------------------------------------------------------- state
    def _snapshot_interfaces(self):
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        state = {}
        for name, st in stats.items():
            if name == "lo" or name.lower().startswith("loopback"):
                continue
            ipv4 = sorted(a.address for a in addrs.get(name, []) if a.family == socket.AF_INET)
            state[name] = (st.isup, tuple(ipv4))
        return state

    def _diff_interfaces(self, before, after, now):
        for name in sorted(set(before) | set(after)):
            old, new = before.get(name), after.get(name)
            if old == new:
                continue
            if old is None:
                self._event(now, f"Interface {name} appeared")
            elif new is None:
                self._event(now, f"Interface {name} disappeared")
            else:
                if old[0] != new[0]:
                    self._event(now, f"Interface {name} went {'up' if new[0] else 'down'}")
                if old[1] != new[1]:
                    self._event(now, f"{name} address changed: {', '.join(old[1]) or 'none'} → "
                                     f"{', '.join(new[1]) or 'none'}")

    def _event(self, now, message):
        event = {"type": "change", "time": now.isoformat(timespec="seconds"), "message": message}
        self.events.append(event)
        self._write_event(event)
        self.callback("change", event)

    @staticmethod
    def _layer(results):
        if results.get("gateway") and not results["gateway"]["ok"]:
            return "Local network"
        if not results["internet"]["ok"]:
            return "Internet provider"
        if results.get("dns") and not results["dns"]["ok"]:
            return "DNS"
        return "Unknown"

    def _update_outages(self, results, now):
        for target, result in results.items():
            stat = self.stats.setdefault(target, {"sent": 0, "ok": 0, "ms_sum": 0.0})
            stat["sent"] += 1
            if result["ok"]:
                stat["ok"] += 1
                stat["ms_sum"] += result["ms"] or 0
                self.fail_streak[target] = 0
                outage = self.open_outages.pop(target, None)
                if outage:
                    outage["end"] = now.isoformat(timespec="seconds")
                    outage["duration"] = round((now - outage["_start"]).total_seconds(), 1)
                    outage.pop("_start")
                    self._write_event(outage)
                    self.callback("restore", dict(outage))
            else:
                self.fail_streak[target] = self.fail_streak.get(target, 0) + 1
                if self.fail_streak[target] == self.fail_threshold and target not in self.open_outages:
                    # The outage began at the first failed probe
                    start = datetime.fromtimestamp(now.timestamp() - self.interval * (self.fail_threshold - 1))
                    outage = {"type": "outage", "target": target, "layer": self._layer(results),
                              "start": start.isoformat(timespec="seconds"), "end": None, "duration": None,
                              "_start": start}
                    self.open_outages[target] = outage
                    self.events.append(outage)
                    self.callback("outage", {k: v for k, v in outage.items() if k != "_start"})

    # ---------------------------------------------------------------- files
    def _open_files(self):
        if not self.log_dir:
            return
        os.makedirs(self.log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.csv_path = os.path.join(self.log_dir, f"connection-monitor-{stamp}.csv")
        self.sample_file = open(self.csv_path, "w", newline="", encoding="utf-8")
        self.sample_writer = csv.writer(self.sample_file)
        self.sample_writer.writerow(["time", "target", "address", "ok", "ms"])
        self.event_file = open(os.path.join(self.log_dir, f"connection-monitor-{stamp}-events.csv"), "w",
                               newline="", encoding="utf-8")
        self.event_writer = csv.writer(self.event_file)
        self.event_writer.writerow(["time", "type", "target", "layer", "end", "duration_s", "message"])

    def _write_event(self, event):
        if self.event_file:
            if event["type"] == "outage":
                self.event_writer.writerow([event["start"], "outage", event["target"], event["layer"], event["end"],
                                            event["duration"], ""])
            else:
                self.event_writer.writerow([event["time"], "change", "", "", "", "", event["message"]])
            self.event_file.flush()

    def _close_files(self):
        for handle in (self.sample_file, self.event_file):
            if handle:
                handle.close()

    # ---------------------------------------------------------------- loop
    def run(self):
        self.started = datetime.now()
        try:
            self._open_files()
        except OSError as e:
            self.callback("error", f"Cannot write the log: {e}")
            self.log_dir = None
        interfaces = self._snapshot_interfaces()
        targets = self._targets()
        last_targets_refresh = time.monotonic()
        pool = ThreadPoolExecutor(max_workers=4)
        try:
            while not self._stop.is_set():
                tick = time.monotonic()
                now = datetime.now()
                if tick - last_targets_refresh > 15:
                    new_targets = self._targets()
                    if new_targets.get("gateway") != targets.get("gateway"):
                        self._event(now, f"Default gateway changed: {targets.get('gateway')} → "
                                         f"{new_targets.get('gateway')}")
                    targets, last_targets_refresh = new_targets, tick
                futures = {name: pool.submit(self._probe, name, address) for name, address in targets.items()}
                results = {name: future.result() for name, future in futures.items()}
                self.samples += 1
                current = self._snapshot_interfaces()
                self._diff_interfaces(interfaces, current, now)
                interfaces = current
                self._update_outages(results, now)
                if self.sample_file:
                    stamp = now.isoformat(timespec="seconds")
                    for name, result in results.items():
                        self.sample_writer.writerow([stamp, name, result["address"], int(result["ok"]),
                                                     "" if result["ms"] is None else round(result["ms"], 2)])
                    if self.samples % 10 == 0:
                        self.sample_file.flush()
                self.callback("sample", {"time": now, "results": results})
                self._stop.wait(max(0.0, self.interval - (time.monotonic() - tick)))
        finally:
            pool.shutdown(wait=False)
            now = datetime.now()
            for outage in self.open_outages.values():
                outage["end"] = None
                outage["duration"] = round((now - outage.pop("_start")).total_seconds(), 1)
                outage["note"] = "still down when the monitor stopped"
                self._write_event(outage)
            self._close_files()

    # ---------------------------------------------------------------- report
    def summary(self):
        duration = (datetime.now() - self.started).total_seconds() if self.started else 0
        targets = {}
        for target, stat in self.stats.items():
            loss = 100 * (stat["sent"] - stat["ok"]) / stat["sent"] if stat["sent"] else 0
            targets[target] = {"probes": stat["sent"], "loss_percent": round(loss, 2),
                               "avg_ms": round(stat["ms_sum"] / stat["ok"], 2) if stat["ok"] else None}
        events = [{k: v for k, v in e.items() if k != "_start"} for e in self.events]
        return {"started": self.started.isoformat(timespec="seconds") if self.started else None,
                "duration_s": round(duration), "interval_s": self.interval,
                "outage_threshold_probes": self.fail_threshold, "targets": targets, "events": events,
                "csv_log": self.csv_path}

    def summary_text(self):
        data = self.summary()
        lines = [f"Connection monitor: started {data['started']}, ran {data['duration_s']} s, "
                 f"probe every {data['interval_s']} s"]
        for target, stat in data["targets"].items():
            avg = f", avg {stat['avg_ms']} ms" if stat["avg_ms"] is not None else ""
            lines.append(f"  {target}: {stat['probes']} probes, {stat['loss_percent']}% lost{avg}")
        outages = [e for e in data["events"] if e["type"] == "outage"]
        lines.append(f"Outages: {len(outages)}")
        for e in data["events"]:
            if e["type"] == "outage":
                lines.append(f"  {e['start']} {e['target']} down ({e['layer']}), "
                             f"{e['duration'] if e['duration'] is not None else '?'} s")
            else:
                lines.append(f"  {e['time']} {e['message']}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------- recording sessions

def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


class SessionRecorder:
    """A user-started recording window over the monitor's samples.

    The monitor keeps running and logging on its own; a session only looks at the samples
    that arrive between start() and stop() and turns them into a report. Outages are
    detected from those samples with the monitor's threshold, so the report is exact for
    the window (an outage already in progress at start counts from the session start).
    """

    def __init__(self, label="", fail_threshold=2, interval=1.0):
        self.label = label.strip()
        self.fail_threshold = max(1, int(fail_threshold))
        self.interval = interval
        self.started = datetime.now()
        self.ended = None
        self.samples = []          # (time, results)
        self.changes = []
        self.outages = []
        self._streak = {}
        self._open = {}

    def add_sample(self, when, results):
        self.samples.append((when, {k: dict(v) for k, v in results.items()}))
        for target, result in results.items():
            if result["ok"]:
                self._streak[target] = 0
                outage = self._open.pop(target, None)
                if outage:
                    outage["end"] = when
                    self.outages.append(outage)
            else:
                self._streak[target] = self._streak.get(target, 0) + 1
                if self._streak[target] == self.fail_threshold and target not in self._open:
                    first_fail = self.samples[-self.fail_threshold][0] if len(self.samples) >= self.fail_threshold \
                        else self.started
                    self._open[target] = {"target": target, "layer": ConnectionMonitor._layer(results),
                                          "start": max(first_fail, self.started), "end": None}

    def add_change(self, event):
        self.changes.append(event)

    @property
    def outage_count(self):
        return len(self.outages) + len(self._open)

    def stop(self):
        self.ended = datetime.now()
        for outage in self._open.values():
            outage["end"] = None
            outage["ongoing"] = True
            self.outages.append(outage)
        self._open = {}
        return self.report()

    def report(self):
        end = self.ended or datetime.now()
        duration = (end - self.started).total_seconds()
        targets = {}
        names = []
        for _when, results in self.samples:
            for name in results:
                if name not in names:
                    names.append(name)
        for name in names:
            series = [r[name] for _w, r in self.samples if name in r]
            times = [r["ms"] for r in series if r["ok"] and r["ms"] is not None]
            jitter = (sum(abs(a - b) for a, b in zip(times, times[1:])) / (len(times) - 1)) if len(times) > 1 else None
            sent = len(series)
            lost = sum(1 for r in series if not r["ok"])
            target_outages = [o for o in self.outages if o["target"] == name]
            downtime = sum(((o["end"] or end) - o["start"]).total_seconds() for o in target_outages)
            longest = max((((o["end"] or end) - o["start"]).total_seconds() for o in target_outages), default=0)
            targets[name] = {
                "address": next((r.get("address") for r in reversed(series) if r.get("address")), ""),
                "probes": sent, "lost": lost, "loss_percent": round(100 * lost / sent, 2) if sent else 0,
                "min_ms": round(min(times), 2) if times else None,
                "avg_ms": round(sum(times) / len(times), 2) if times else None,
                "p95_ms": round(_percentile(times, 0.95), 2) if times else None,
                "max_ms": round(max(times), 2) if times else None,
                "jitter_ms": round(jitter, 2) if jitter is not None else None,
                "outages": len(target_outages), "downtime_s": round(downtime, 1), "longest_outage_s": round(longest, 1),
            }
        outages = [{"target": o["target"], "layer": o["layer"], "start": o["start"].isoformat(timespec="seconds"),
                    "end": o["end"].isoformat(timespec="seconds") if o["end"] else None,
                    "duration_s": round(((o["end"] or end) - o["start"]).total_seconds(), 1),
                    "ongoing": bool(o.get("ongoing"))} for o in sorted(self.outages, key=lambda o: o["start"])]
        return {"label": self.label, "started": self.started.isoformat(timespec="seconds"),
                "ended": end.isoformat(timespec="seconds"), "duration_s": round(duration),
                "interval_s": self.interval, "outage_threshold_probes": self.fail_threshold,
                "rounds": len(self.samples), "targets": targets, "outages": outages, "changes": list(self.changes),
                "verdict": self.verdict(targets, outages)}

    @staticmethod
    def verdict(targets, outages):
        if not targets:
            return "No data"
        internet = targets.get("internet", {})
        if outages:
            layers = sorted({o["layer"] for o in outages})
            return f"Unstable: {len(outages)} outage(s) ({', '.join(layers)})"
        if internet.get("loss_percent", 0) >= 1 or any(t["loss_percent"] >= 2 for t in targets.values()):
            return "Packet loss without full outages"
        if (internet.get("jitter_ms") or 0) > 30 or (internet.get("p95_ms") or 0) > 150:
            return "Stable but with high latency spikes"
        return "Stable: no outages and no notable loss"

    def summary_line(self, report=None):
        report = report or self.report()
        loss = report["targets"].get("internet", {}).get("loss_percent", 0)
        minutes = report["duration_s"] / 60
        return (f"{minutes:.1f} min · {len(report['outages'])} outage{'s' if len(report['outages']) != 1 else ''} · "
                f"{loss:.1f}% internet loss")


def session_markdown(report):
    title = f"Connection monitor session{': ' + report['label'] if report['label'] else ''}"
    lines = [f"# {title}", "",
             f"- Started: {report['started']}", f"- Ended: {report['ended']}",
             f"- Duration: {report['duration_s'] // 60} min {report['duration_s'] % 60} s "
             f"({report['rounds']} rounds, probe every {report['interval_s']:g} s, outage after "
             f"{report['outage_threshold_probes']} failed probe(s))",
             f"- Verdict: **{report['verdict']}**", "",
             "## Targets", "",
             "| Target | Address | Loss | Min | Avg | p95 | Max | Jitter | Outages | Downtime |",
             "|---|---|---|---|---|---|---|---|---|---|"]

    def ms(value):
        return "—" if value is None else f"{value:.1f} ms"
    for name, t in report["targets"].items():
        lines.append(f"| {name} | {t['address']} | {t['loss_percent']:.1f}% ({t['lost']}/{t['probes']}) | "
                     f"{ms(t['min_ms'])} | {ms(t['avg_ms'])} | {ms(t['p95_ms'])} | {ms(t['max_ms'])} | "
                     f"{ms(t['jitter_ms'])} | {t['outages']} | {t['downtime_s']:.1f} s |")
    lines += ["", "## Outages", ""]
    if report["outages"]:
        lines += ["| Start | End | Duration | Target | Layer |", "|---|---|---|---|---|"]
        for o in report["outages"]:
            lines.append(f"| {o['start']} | {o['end'] or 'still down'} | {o['duration_s']:.1f} s | {o['target']} | "
                         f"{o['layer']} |")
    else:
        lines.append("No outages in this session.")
    lines += ["", "## Interface and gateway changes", ""]
    lines += [f"- {c['time']}: {c['message']}" for c in report["changes"]] or ["None."]
    lines += ["", "Layers: *Local network* = the gateway did not answer (cable, Wi-Fi, adapter or router); "
              "*Internet provider* = the gateway answered but the internet did not; *DNS* = the internet answered "
              "but name lookups failed.", ""]
    return "\n".join(lines)


def write_session_files(recorder, report, folder):
    """Write the report (.md) and the session's samples (.csv); returns the .md path."""
    os.makedirs(folder, exist_ok=True)
    stamp = recorder.started.strftime("%Y%m%d-%H%M%S")
    base = os.path.join(folder, f"monitor-session-{stamp}")
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(session_markdown(report))
    with open(base + ".csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "target", "address", "ok", "ms"])
        for when, results in recorder.samples:
            for name, r in results.items():
                writer.writerow([when.isoformat(timespec="seconds"), name, r.get("address", ""), int(r["ok"]),
                                 "" if r["ms"] is None else round(r["ms"], 2)])
    return base + ".md"
