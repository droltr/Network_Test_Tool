"""Game connection: find the Counter-Strike 2 server you play on and where on the path lag or loss comes from.

Anti-cheat safety: this page only calls network/game_server.py. It never opens or inspects the game
process, never reads game files, and never blocks, delays or reroutes game traffic.
"""
import html
import os
import re
import sys
import threading
from datetime import datetime

from PyQt5.QtCore import Qt, QThread, QSettings, QStandardPaths, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices
from PyQt5.QtWidgets import QHBoxLayout, QComboBox, QTableWidgetItem, QProgressBar

from gui.pages.base import Page, finish_thread
from gui.styles import modern_theme
from gui.styles.modern_theme import Colors, mono_font, ui_font, rgba
from gui.widgets.common import (Card, Label, LineInput, StatusDot, PulseDot, Badge, StatStrip, section_label,
                                button, link_button, hbox, make_table, set_prop, cell_widget, fmt_ms)
from network import game_server
from network.game_server import GameServerError

ZONE_LABELS = {
    "none": "No notable packet loss",
    "home": "Your home network",
    "isp": "Your internet provider",
    "transit": "Between your provider and Valve",
    "server": "Valve server / its network",
    "inconclusive": "Inconclusive",
}
PROBLEM_ZONES = ("home", "isp", "transit", "server")
DURATIONS = [("2 min", 120), ("5 min", 300), ("10 min", 600)]
CAPTURE_SECONDS = 10
SCAN_SECONDS = 20
GAP_LIMIT_MS = 40
VAC_NOTE = ("Safe with Valve Anti-Cheat: reads only Windows network tables and passive packet headers; never "
            "touches the game process or its files.")


def zone_color(zone):
    """Colour of a verdict zone. Problems you can act on (home, provider) are critical; problems
    outside your reach (transit, Valve) are warnings. "inconclusive" and any unknown zone are neutral."""
    return {"none": Colors.GREEN, "home": Colors.RED, "isp": Colors.RED,
            "transit": Colors.YELLOW, "server": Colors.YELLOW}.get(zone, Colors.TEXT_MUTED)


def stream_status(stream):
    """(label, colour) for the inbound game stream measured during detection."""
    rate = stream.get("bursts_per_s") or 0
    expected = stream.get("expected_per_s") or 64
    gaps = stream.get("gaps_over_40ms") or 0
    max_gap = stream.get("max_gap_ms") or 0
    if not stream.get("packets"):
        return "No traffic", Colors.RED
    if rate < 0.75 * expected or max_gap > 250:
        return "Unstable", Colors.RED
    if rate < 0.95 * expected or gaps:
        return "Hiccups", Colors.YELLOW
    return "Smooth", Colors.GREEN


def asn_text(hop):
    owner = hop.get("owner") or ("Your router" if hop.get("gateway") else "")
    asn = hop.get("asn")
    if asn in (None, "", 0):
        return owner
    asn = str(asn)
    asn = asn if asn.upper().startswith("AS") else f"AS{asn}"
    return f"{owner} ({asn})" if owner else asn


_HOST_RE = re.compile(r"^[A-Za-z0-9.\-:]+$")
WORKER_SIGNALS = ("status", "progress", "update", "done", "failed", "cancelled", "finished")


def parse_address(text):
    """Host or IP from what the user typed. Strips an optional :port (CS2's console prints ip:port) and
    the brackets of [IPv6]:port. Returns None when the text cannot be an address."""
    text = (text or "").strip()
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    elif text.count(":") == 1:
        host, port = text.rsplit(":", 1)
        if not port.isdigit():
            return None
        text = host
    return text if text and _HOST_RE.match(text) else None


def disconnect_worker(thread):
    """Cut every signal of a worker from the page, so a worker that outlives the window (see
    finish_thread) never calls into deleted widgets."""
    if thread is None:
        return
    for name in WORKER_SIGNALS:
        signal = getattr(thread, name, None)
        if signal is None:
            continue
        try:
            signal.disconnect()
        except (TypeError, RuntimeError):
            pass   # nothing connected


def saved_text(paths, order):
    """'Saved in <folder>: name.html · .md · .json' — the three files of one report, compactly."""
    present = [paths[k] for k in order if paths.get(k)]
    if not present:
        return ""
    base, _ext = os.path.splitext(os.path.basename(present[0]))
    names = [os.path.basename(present[0])] + [os.path.splitext(p)[1] for p in present[1:]]
    return f"Saved in {os.path.dirname(present[0])}: " + " · ".join(names)


def open_local_file(path):
    """Open a local file or folder with the system's default app (the HTML report in the browser)."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def compare_targets(scan_results, target, limit=2):
    """Up to `limit` of the best scanned Valve relays other than the diagnosis target, pinged in the same
    rounds so the report can compare them. Only relays that answered during the scan qualify."""
    target_ip = (target or {}).get("ip")
    target_pop = ((target or {}).get("relay") or {}).get("pop")
    picked = []
    for r in scan_results or []:
        if not r.get("ip") or r.get("ip") == target_ip or (target_pop and r.get("pop") == target_pop):
            continue
        if not r.get("sent") or (r.get("loss_percent") or 0) >= 100:
            continue
        picked.append({"address": r["ip"], "label": f"Valve {r.get('desc') or r.get('pop')}"})
        if len(picked) == limit:
            break
    return picked


def relay_text(relay):
    if not relay:
        return ""
    return f"Valve {relay.get('desc') or relay.get('pop', '')}".strip()


# ---------------------------------------------------------------- workers

class ProcessThread(QThread):
    done = pyqtSignal(object, str)   # process dict or None, error text

    def run(self):
        try:
            self.done.emit(game_server.find_game_process(), "")
        except GameServerError as e:
            self.done.emit(None, str(e))
        except Exception as e:   # never crash the page on a backend failure
            self.done.emit(None, f"Could not check for the game: {e}")


class DetectThread(QThread):
    status = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, relays, parent=None):
        super().__init__(parent)
        self.relays = relays
        self.cancel = threading.Event()

    def stop(self):
        self.cancel.set()

    def run(self):
        try:
            if not sys.platform.startswith("win"):
                # Same message the capture gives, before anything else is checked
                raise GameServerError("Finding the game server needs Windows (pktmon).")
            process = game_server.find_game_process()
            if not process:
                raise GameServerError("Counter-Strike 2 is not running. Start the game and join a match first.")
            ports = process.get("udp_ports") or []
            if not ports:
                raise GameServerError("Counter-Strike 2 has no network connection open yet. Join a match first.")
            try:
                elevated = game_server.is_elevated()
            except Exception:
                elevated = False
            if elevated:
                self.status.emit(f"Watching game traffic for {CAPTURE_SECONDS} seconds…")
            else:
                self.status.emit(f"Windows asks for administrator permission now. After you allow it, the game "
                                 f"traffic is watched for {CAPTURE_SECONDS} seconds…")
            capture = game_server.capture_game_peers(ports, seconds=CAPTURE_SECONDS, cancel=self.cancel)
            if self.cancel.is_set():
                return
            # Keep the backend's order: its stream statistics belong to peers[0]
            peers = capture.get("peers") or []
            if not peers or not peers[0].get("rx"):
                raise GameServerError("No incoming game traffic was seen. Make sure you are in a match, "
                                      "not in the menu.")
            relays = self.relays
            relay = None
            if relays is None:
                try:
                    relays = game_server.fetch_relays()
                except Exception:
                    relays = None
            if self.cancel.is_set():
                return
            if relays:
                relay = game_server.find_relay(peers[0]["ip"], relays)
            self.done.emit({"process": process, "capture": capture, "server": peers[0], "relay": relay,
                            "relays": relays})
        except GameServerError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"Detection failed: {e}")


class RelayScanThread(QThread):
    progress = pyqtSignal(float)
    done = pyqtSignal(object, object)   # results, relays
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, relays, parent=None):
        super().__init__(parent)
        self.relays = relays
        self.cancel = threading.Event()

    def stop(self):
        self.cancel.set()

    def run(self):
        try:
            relays = self.relays or game_server.fetch_relays()
            if not relays:
                raise GameServerError("Valve's server list is empty.")
            results = game_server.scan_relays(relays, seconds=SCAN_SECONDS, callback=self.progress.emit,
                                              cancel=self.cancel)
            if self.cancel.is_set() or not any(r.get("sent") for r in results or []):
                self.cancelled.emit()   # an interrupted scan has unprobed rows that would read as 0 % loss
                return
            self.done.emit(results, relays)
        except GameServerError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"Scan failed: {e}")


class DiagnosisThread(QThread):
    update = pyqtSignal(object)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, target, duration, relay=None, compare=None, parent=None):
        super().__init__(parent)
        self.diagnosis = game_server.PathDiagnosis(target, duration=duration, interval=1.0,
                                                   callback=self.update.emit, compare=compare or None)
        if relay and getattr(self.diagnosis, "relay", None) is None:
            self.diagnosis.relay = relay
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True
        self.diagnosis.stop()

    def run(self):
        try:
            self.diagnosis.run()
            report = self.diagnosis.report()
            if "cancelled" in report:
                cancelled = bool(report["cancelled"])   # the backend: stopped before the first round
            else:
                cancelled = self.stop_requested and not report.get("round_times")
            if cancelled:
                # Stopped before a probe round completed (during the trace): nothing to judge or save
                self.cancelled.emit()
                return
            self.done.emit(report)
        except GameServerError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"Diagnosis failed: {e}")


# ---------------------------------------------------------------- page

class GamePage(Page):
    def __init__(self):
        super().__init__("Game connection", scroll=True)
        self.header.set_subtitle("Counter-Strike 2 · find where lag and packet loss come from")
        self.settings = QSettings("NetworkTools", "Health")   # shares the log folder with Network health
        self.process_thread = None
        self.detect_thread = None
        self.scan_thread = None
        self.diag_thread = None
        self.relays = None
        self.detection = None
        self.scan_results = []
        self.target = None          # {"ip", "relay", "source"}
        self.report = None
        self.report_text = ""
        self.diag_error = False
        self.diag_seconds = 0
        self.pending_target = None
        self.diag_target = None
        self.diag_context = None
        self.detect_succeeded = False
        self.saved = None           # {"md", "json", "html"} of the last saved report

        self.save_btn = button("Save report", "secondary", 30)
        self.save_btn.setEnabled(False)
        self.save_btn.setToolTip("Run a path diagnosis first")
        self.save_btn.clicked.connect(self.save_report)
        self.header.set_actions(self.save_btn)

        vac = Label(VAC_NOTE, 11.5, color=Colors.TEXT_MUTED)
        vac.setWordWrap(True)
        self.body.addWidget(vac)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self.build_game_card(), 1)
        top.addWidget(self.build_scan_card(), 1)
        self.body.addLayout(top)
        self.body.addWidget(self.build_diagnosis_card())
        self.body.addStretch(1)

    # ================================================================ 1. game
    def build_game_card(self):
        card = Card(margins=(16, 14, 16, 14), spacing=8)
        card.body.addWidget(section_label("1 · Your game"))
        self.process_dot = StatusDot(Colors.TEXT_FAINT, 8, "dashed")
        self.process_label = Label("Checking whether Counter-Strike 2 is running…", 12.5, color=Colors.TEXT)
        self.process_label.setWordWrap(True)
        refresh = link_button("Refresh")
        refresh.clicked.connect(self.refresh_process)
        row = hbox(self.process_dot, self.process_label, "stretch", refresh, spacing=6)
        row.setStretchFactor(self.process_label, 1)
        card.body.addLayout(row)

        self.detect_btn = button("Detect server", "primary", 34, width=150)
        self.detect_btn.clicked.connect(self.toggle_detect)
        note = Label("Needs administrator permission; Windows will ask.", 11.5, color=Colors.TEXT_MUTED)
        note.setWordWrap(True)
        card.body.addLayout(hbox(self.detect_btn, 10, note, spacing=6))
        self.detect_status = Label("Join a match, then press Detect server. It watches the game's traffic for "
                                   f"{CAPTURE_SECONDS} seconds.", 12, color=Colors.TEXT_MUTED)
        self.detect_status.setWordWrap(True)
        self.detect_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.body.addWidget(self.detect_status)

        self.server_label = Label("—", 17, 500, Colors.TEXT_FAINT, mono=True)
        self.server_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.location_label = Label("", 12.5, color=Colors.TEXT_MUTED)
        self.location_label.setWordWrap(True)
        self.stream_badge = Badge("", Colors.TEXT_MUTED)
        self.stream_badge.setVisible(False)
        server_row = hbox(self.server_label, 8, self.location_label, self.stream_badge, spacing=6)
        server_row.setStretchFactor(self.location_label, 1)
        card.body.addLayout(server_row)
        self.stream_stats = StatStrip([("rate", "Inbound / s"), ("expected", "Expected / s"),
                                       ("max_gap", "Max gap"), ("gaps", f"Gaps > {GAP_LIMIT_MS} ms")], 13)
        card.body.addWidget(self.stream_stats)
        card.body.addStretch(1)
        return card

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_process()

    def refresh_process(self):
        if self.process_thread and self.process_thread.isRunning():
            return
        self.process_thread = ProcessThread(self)
        self.process_thread.done.connect(self.on_process)
        self.process_thread.start()

    def on_process(self, process, error):
        if process:
            ports = len(process.get("udp_ports") or [])
            self.process_dot.set_state(Colors.GREEN)
            self.process_label.setText(f"Counter-Strike 2 is running · {ports} network port"
                                       f"{'s' if ports != 1 else ''} open")
            self.process_label.set_color(Colors.TEXT_STRONG)
        elif error:
            self.process_dot.set_state(Colors.TEXT_FAINT, "hollow")
            self.process_label.setText(error)
            self.process_label.set_color(Colors.TEXT_MUTED)
        else:
            self.process_dot.set_state(Colors.TEXT_FAINT, "hollow")
            self.process_label.setText("Counter-Strike 2 is not running. You can still scan Valve servers.")
            self.process_label.set_color(Colors.TEXT_MUTED)

    def toggle_detect(self):
        if self.detect_thread and self.detect_thread.isRunning():
            self.detect_thread.stop()
            self.detect_btn.setEnabled(False)
            self.detect_btn.setText("Stopping…")
            return
        self.detect_thread = DetectThread(self.relays, self)
        self.detect_thread.status.connect(lambda text: self.set_detect_status(text, Colors.BLUE))
        self.detect_thread.done.connect(self.on_detected)
        self.detect_thread.failed.connect(self.on_detect_failed)
        self.detect_thread.finished.connect(self.on_detect_finished)
        self.detect_succeeded = False
        self.detect_btn.setText("Cancel")
        set_prop(self.detect_btn, "variant", "stop")
        self.set_detect_status("Looking for the game…", Colors.BLUE)
        self.detect_thread.start()
        self.update_running()

    def set_detect_status(self, text, color):
        self.detect_status.setText(text)
        self.detect_status.set_color(color)

    def on_detected(self, result):
        self.detect_succeeded = True
        self.detection = result
        if result.get("relays"):
            self.relays = result["relays"]
            self.resolve_target_relay()
        server, relay = result["server"], result["relay"]
        stream = result["capture"].get("stream") or {}
        self.server_label.setText(f"{server['ip']}:{server.get('port', '')}")
        self.server_label.set_color(Colors.TEXT_STRONG)
        self.location_label.setText(relay_text(relay) or "Not a known Valve location")
        self.location_label.set_color(Colors.TEXT if relay else Colors.YELLOW)
        text, color = stream_status(stream)
        self.stream_badge.setText(text)
        self.stream_badge.set_tone(color)
        self.stream_badge.setVisible(True)
        rate, expected = stream.get("bursts_per_s"), stream.get("expected_per_s") or 64
        self.stream_stats.set("rate", None if rate is None else f"{rate:.1f}",
                              Colors.TEXT_STRONG if rate is None or rate >= 0.95 * expected else Colors.YELLOW)
        self.stream_stats.set("expected", f"{expected:g}")
        max_gap = stream.get("max_gap_ms")
        self.stream_stats.set("max_gap", fmt_ms(max_gap, 0) if max_gap is not None else None,
                              Colors.TEXT_STRONG if (max_gap or 0) <= GAP_LIMIT_MS else Colors.YELLOW)
        gaps = stream.get("gaps_over_40ms")
        self.stream_stats.set("gaps", None if gaps is None else str(gaps),
                              Colors.TEXT_STRONG if not gaps else Colors.YELLOW)
        packets = stream.get("packets", 0)
        running = bool(self.diag_thread and self.diag_thread.isRunning())
        self.set_detect_status(f"Found the game server from {packets} packets in "
                               f"{result['capture'].get('seconds', CAPTURE_SECONDS)} s. "
                               + ("It becomes the diagnosis target when the current run ends." if running
                                  else "It is now the diagnosis target."), Colors.GREEN)
        self.set_target(server["ip"], relay, "detected")

    def on_detect_failed(self, text):
        if self.detect_thread and self.detect_thread.cancel.is_set():
            self.set_detect_status("Cancelled.", Colors.TEXT_MUTED)
        else:
            self.set_detect_status(text, Colors.RED)

    def on_detect_finished(self):
        if self.detect_thread and self.detect_thread.cancel.is_set() and not self.detect_succeeded:
            # Cancelled after the capture or during the relay lookup: the worker ends without a signal
            self.set_detect_status("Cancelled.", Colors.TEXT_MUTED)
        self.detect_btn.setEnabled(True)
        self.detect_btn.setText("Detect server")
        set_prop(self.detect_btn, "variant", "primary")
        self.update_running()

    # ================================================================ 2. scan
    def build_scan_card(self):
        card = Card(margins=(16, 14, 16, 14), spacing=8)
        card.body.addWidget(section_label("2 · No game running? Scan Valve servers"))
        intro = Label(f"Pings every Valve location for {SCAN_SECONDS} seconds. No administrator permission needed.",
                      12, color=Colors.TEXT_MUTED)
        intro.setWordWrap(True)
        self.scan_btn = button("Scan Valve servers", "secondary", 32, width=160)
        self.scan_btn.clicked.connect(self.toggle_scan)
        row = hbox(intro, 10, self.scan_btn, spacing=6)
        row.setStretchFactor(intro, 1)
        card.body.addLayout(row)
        self.scan_bar = QProgressBar()
        self.scan_bar.setTextVisible(False)
        self.scan_bar.setRange(0, 100)
        self.scan_bar.setFixedHeight(6)
        self.scan_bar.setVisible(False)
        card.body.addWidget(self.scan_bar)
        self.scan_status = Label("", 12, color=Colors.TEXT_MUTED)
        self.scan_status.setWordWrap(True)
        self.scan_status.setVisible(False)
        card.body.addWidget(self.scan_status)
        self.scan_table = make_table(["Location", "Loss %", "Avg", "p95", ""], stretch_column=0)
        for column, width in ((1, 72), (2, 78), (3, 78), (4, 58)):
            self.scan_table.horizontalHeader().resizeSection(column, width)
        self.scan_table.setFixedHeight(30 + 5 * 32 + 4)
        card.body.addWidget(self.scan_table, 1)
        self.manual = LineInput("Server IP address, e.g. 155.133.248.34", height=30)
        self.manual.returnPressed.connect(self.use_manual)
        use = button("Use address", "secondary", 30)
        use.clicked.connect(self.use_manual)
        card.body.addLayout(hbox(Label("Or type an address", 12, color=Colors.TEXT_MUTED), self.manual, use,
                                 spacing=6))
        return card

    def toggle_scan(self):
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()
            self.scan_btn.setEnabled(False)
            self.scan_btn.setText("Stopping…")
            return
        self.scan_thread = RelayScanThread(self.relays, self)
        self.scan_thread.progress.connect(lambda f: self.scan_bar.setValue(int(max(0.0, min(1.0, f)) * 100)))
        self.scan_thread.done.connect(self.on_scan_done)
        self.scan_thread.failed.connect(self.on_scan_failed)
        self.scan_thread.cancelled.connect(self.on_scan_cancelled)
        self.scan_thread.finished.connect(self.on_scan_finished)
        self.scan_bar.setValue(0)
        self.scan_bar.setVisible(True)
        self.scan_status.setText("Loading Valve's server list and pinging every location…")
        self.scan_status.set_color(Colors.BLUE)
        self.scan_status.setVisible(True)
        self.scan_btn.setText("Stop scan")
        set_prop(self.scan_btn, "variant", "stop")
        self.scan_thread.start()
        self.update_running()

    def on_scan_done(self, results, relays):
        self.relays = relays
        self.resolve_target_relay()
        self.scan_results = sorted(results or [], key=lambda r: (
            r.get("loss_percent") if r.get("loss_percent") is not None else 100,
            r.get("avg_ms") if r.get("avg_ms") is not None else 1e9))
        self.fill_scan_table()
        if self.scan_results:
            best = self.scan_results[0]
            self.scan_status.setText(f"Best: {best.get('desc') or best.get('pop')} · "
                                     f"{fmt_ms(best.get('avg_ms'))}. Press Use on a row to diagnose that path.")
            self.scan_status.set_color(Colors.TEXT)
        else:
            self.scan_status.setText("No results.")
            self.scan_status.set_color(Colors.YELLOW)

    def fill_scan_table(self):
        table = self.scan_table
        table.setRowCount(len(self.scan_results))
        for row, result in enumerate(self.scan_results):
            loss = result.get("loss_percent") if result.get("sent") else None   # unprobed: no figure
            loss_color = Colors.TEXT if not loss else (Colors.RED if loss >= 5 else Colors.YELLOW)
            values = ((result.get("desc") or result.get("pop", ""), Colors.TEXT_STRONG, ui_font(12.5)),
                      ("—" if loss is None else f"{loss:.1f}", loss_color, mono_font(12)),
                      (fmt_ms(result.get("avg_ms")), Colors.TEXT, mono_font(12)),
                      (fmt_ms(result.get("p95_ms")), Colors.TEXT, mono_font(12)))
            for column, (text, color, font) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(color))
                item.setFont(font)
                if column == 0:
                    item.setToolTip(f"{result.get('pop', '')} · {result.get('ip', '')}")
                table.setItem(row, column, item)
            use = link_button("Use")
            use.clicked.connect(lambda _=False, r=result: self.use_scan_row(r))
            table.setCellWidget(row, 4, cell_widget(use, margins=(6, 0, 6, 0)))

    def use_scan_row(self, result):
        relay = None
        if self.relays:
            relay = next((r for r in self.relays if r.get("pop") == result.get("pop")), None)
        relay = relay or {"pop": result.get("pop"), "desc": result.get("desc")}
        self.set_target(result.get("ip"), relay, "scan")

    def use_manual(self):
        address = parse_address(self.manual.text())
        if not address:
            self.manual.set_error(True)
            return
        relay = None
        if self.relays:
            try:
                relay = game_server.find_relay(address, self.relays)
            except Exception:
                relay = None
        self.set_target(address, relay, "manual")

    def on_scan_cancelled(self):
        self.scan_status.setText("Scan cancelled.")
        self.scan_status.set_color(Colors.TEXT_MUTED)
        self.scan_status.setVisible(True)

    def on_scan_failed(self, text):
        self.scan_status.setText(text)
        self.scan_status.set_color(Colors.RED)
        self.scan_status.setVisible(True)

    def on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan again" if self.scan_results else "Scan Valve servers")
        set_prop(self.scan_btn, "variant", "secondary")
        self.scan_bar.setVisible(False)
        self.update_running()

    # ================================================================ 3. diagnosis
    def build_diagnosis_card(self):
        card = Card(margins=(16, 14, 16, 14), spacing=8)
        card.body.addWidget(section_label("3 · Path diagnosis"))
        self.target_label = Label("No target yet: detect the server, choose a scanned location or type an address.",
                                  12.5, color=Colors.TEXT_MUTED)
        self.duration_combo = QComboBox()
        self.duration_combo.addItems([text for text, _s in DURATIONS])
        self.duration_combo.setFont(ui_font(12))
        self.duration_combo.setFixedSize(90, 30)
        self.diag_btn = button("Start diagnosis", "primary", 32, width=150)
        self.diag_btn.setEnabled(False)
        self.diag_btn.clicked.connect(self.toggle_diagnosis)
        self.target_label.setWordWrap(True)
        row = hbox(Label("Target", 12, color=Colors.TEXT_MUTED), self.target_label, 12,
                   Label("Duration", 12, color=Colors.TEXT_MUTED), self.duration_combo, 8, self.diag_btn, spacing=8)
        row.setStretchFactor(self.target_label, 1)
        card.body.addLayout(row)
        self.diag_pulse = PulseDot(Colors.GREEN, 8)
        self.diag_pulse.setVisible(False)
        self.diag_status = Label("Traces the route to the server, then pings every hop once a second. Play while "
                                 "it runs so the problem can show up.", 12, color=Colors.TEXT_MUTED)
        self.diag_status.setWordWrap(True)
        status_row = hbox(self.diag_pulse, self.diag_status, spacing=6)
        status_row.setStretchFactor(self.diag_status, 1)
        card.body.addLayout(status_row)

        self.verdict = Card(margins=(14, 10, 14, 10), spacing=2)
        self.verdict_zone = Label("", 13.5, 600, Colors.TEXT_STRONG)
        self.verdict_summary = Label("", 12.5, color=Colors.TEXT)
        self.verdict_summary.setWordWrap(True)
        self.verdict_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.verdict_dot = StatusDot(Colors.GREEN, 10)
        self.verdict.body.addLayout(hbox(self.verdict_dot, self.verdict_zone, "stretch", spacing=8))
        self.verdict.body.addWidget(self.verdict_summary)
        self.verdict.setVisible(False)
        card.body.addWidget(self.verdict)

        self.hop_table = make_table(["Hop", "Address", "Owner / ASN", "Loss %", "Avg", "p95", "Jitter"],
                                    stretch_column=2)
        for column, width in ((0, 56), (1, 150), (3, 104), (4, 84), (5, 84), (6, 84)):
            self.hop_table.horizontalHeader().resizeSection(column, width)
        self.hop_table.setFixedHeight(30 + 8 * 32 + 4)
        card.body.addWidget(self.hop_table)
        hint = Label("Loss at a middle hop alone is not a problem: many routers do not answer pings when busy. "
                     "Only loss that continues to the last hop reaches your game.", 11.5, color=Colors.TEXT_MUTED)
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        self.save_status = Label("", 11.5, color=Colors.TEXT_MUTED, mono=True)
        self.save_status.setWordWrap(True)
        self.save_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.open_report = link_button("Open report")
        self.open_report.setToolTip("Open the HTML report in your browser")
        self.open_report.setVisible(False)
        self.open_report.clicked.connect(lambda: self.saved and open_local_file(self.saved["html"]))
        self.open_folder = link_button("Open report folder")
        self.open_folder.setVisible(False)
        self.open_folder.clicked.connect(
            lambda: self.saved and open_local_file(os.path.dirname(self.saved.get("html") or self.saved["md"])))
        save_row = hbox(self.save_status, self.open_report, self.open_folder, spacing=8)
        save_row.setStretchFactor(self.save_status, 1)
        card.body.addLayout(save_row)
        return card

    def set_target(self, ip, relay, source):
        if not ip:
            return
        target = {"ip": ip, "relay": relay, "source": source}
        if self.diag_thread and self.diag_thread.isRunning():
            # The label describes the running diagnosis; the new target takes over when it ends
            self.pending_target = target
            self.target_label.setToolTip(f"Next target: {ip}")
            return
        self.pending_target = None
        if self.target and self.target["ip"] != ip:
            # The verdict and hops on screen belong to the previous target; its report can still be saved
            self.verdict.setVisible(False)
            self.hop_table.setRowCount(0)
        self.target = target
        self.update_target_label()
        self.diag_btn.setEnabled(True)

    def update_target_label(self):
        target = self.target
        place = relay_text(target.get("relay"))
        origin = {"detected": "detected game server", "scan": "scanned location",
                  "manual": "typed address"}[target["source"]]
        self.target_label.setText(f'<span style="font-family: \'{modern_theme.MONO_FAMILY}\';">'
                                  f'{html.escape(target["ip"])}</span>'
                                  + (f" · {html.escape(place)}" if place else "") + f" · {origin}")
        self.target_label.setToolTip("")
        self.target_label.set_color(Colors.TEXT_STRONG)

    def resolve_target_relay(self):
        """Look up the Valve location of a target chosen before the relay list was loaded, so the
        report names it and compare_targets() never picks the same location."""
        for target in (self.target, self.pending_target):
            if not target or target.get("relay") or not self.relays:
                continue
            try:
                target["relay"] = game_server.find_relay(target["ip"], self.relays)
            except Exception:
                target["relay"] = None
            if target is self.target and target["relay"] and not (self.diag_thread and
                                                                     self.diag_thread.isRunning()):
                self.update_target_label()

    def toggle_diagnosis(self):
        if self.diag_thread and self.diag_thread.isRunning():
            self.diag_btn.setEnabled(False)
            self.diag_btn.setText("Stopping…")
            self.diag_thread.stop()
            return
        if not self.target:
            return
        seconds = DURATIONS[self.duration_combo.currentIndex()][1]
        self.resolve_target_relay()
        try:
            self.diag_thread = DiagnosisThread(self.target["ip"], seconds, self.target.get("relay"),
                                               compare_targets(self.scan_results, self.target), parent=self)
        except Exception as e:
            self.diag_status.setText(f"Could not start: {e}")
            self.diag_status.set_color(Colors.RED)
            return
        self.diag_seconds = seconds
        # What the report may say besides the diagnosis, frozen now: a later detection or scan must not
        # end up in this run's report
        self.diag_target = dict(self.target)
        self.diag_context = {"detection": self.detection_for(self.target["ip"]),
                             "scan": list(self.scan_results) or None}
        self.diag_thread.update.connect(self.on_diag_update)
        self.diag_thread.done.connect(self.on_diag_done)
        self.diag_thread.failed.connect(self.on_diag_failed)
        self.diag_thread.cancelled.connect(self.on_diag_cancelled)
        self.diag_thread.finished.connect(self.on_diag_finished)
        self.diag_error = False
        self.report, self.report_text = None, ""
        self.save_btn.setEnabled(False)
        self.save_status.setText("")
        self.open_folder.setVisible(False)
        self.open_report.setVisible(False)
        self.saved = None
        self.hop_table.setRowCount(0)
        self.verdict.setVisible(False)
        self.diag_btn.setText("Stop")
        set_prop(self.diag_btn, "variant", "stop")
        self.duration_combo.setEnabled(False)
        self.diag_pulse.setVisible(True)
        self.diag_status.setText(f"Tracing the route to {self.target['ip']}… This can take about 25 seconds "
                                 "before probing starts.")
        self.diag_status.set_color(Colors.BLUE)
        self.diag_thread.start()
        self.update_running()

    def on_diag_update(self, data):
        hops = data.get("hops") or []
        self.fill_hops(hops)
        if data.get("phase") == "probe":
            elapsed = int(data.get("elapsed") or 0)
            total = getattr(self, "diag_seconds", 0)
            self.diag_status.setText(f"Probing {len(hops)} hops · {elapsed // 60}:{elapsed % 60:02d} of "
                                     f"{total // 60}:{total % 60:02d}. Keep playing; the verdict comes at the end.")
            self.diag_status.set_color(Colors.GREEN)
        else:
            self.diag_status.setText(f"Route found: {len(hops)} hops. Starting to probe…")

    def fill_hops(self, hops, verdict_hop=None, verdict_color=None, final_zone=None):
        """final_zone is the verdict zone once the run has ended (None while it runs)."""
        table = self.hop_table
        table.setRowCount(len(hops))
        last = len(hops) - 1
        for row, hop in enumerate(hops):
            loss = hop.get("loss_percent")
            sent = hop.get("sent")
            index = hop.get("index", row + 1)
            target = hop.get("is_target") or row == last
            # Hops that never answer ping during probing are ICMP-silent (a server can be too):
            # not a problem in themselves
            silent = bool(sent) and loss is not None and loss >= 100
            if silent:
                loss_color = Colors.TEXT_FAINT
            elif not loss:
                loss_color = Colors.TEXT
            elif verdict_hop is not None and isinstance(index, int) and index >= verdict_hop:
                loss_color = verdict_color   # loss that carries on to the server
            elif target and final_zone is None:
                loss_color = Colors.YELLOW       # still measuring; the verdict decides
            elif target and final_zone == "none":
                loss_color = Colors.TEXT         # below the verdict's threshold
            else:
                # Loss at a middle hop alone is usually ICMP rate limiting; inconclusive targets stay neutral
                loss_color = Colors.TEXT_MUTED
            if silent:
                loss_text = "no ping reply"
            else:
                loss_text = "—" if loss is None or not sent else f"{loss:.1f}"
            values = ((str(index), Colors.TEXT_MUTED, mono_font(12)),
                      (hop.get("address") or "* no reply", Colors.TEXT_STRONG if hop.get("address") else Colors.TEXT_FAINT,
                       mono_font(12)),
                      (asn_text(hop), Colors.TEXT, ui_font(12.5)),
                      (loss_text, loss_color, ui_font(12) if silent else mono_font(12)),
                      (fmt_ms(hop.get("avg_ms")), Colors.TEXT, mono_font(12)),
                      (fmt_ms(hop.get("p95_ms")), Colors.TEXT, mono_font(12)),
                      (fmt_ms(hop.get("jitter_ms")), Colors.TEXT, mono_font(12)))
            for column, (text, color, font) in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFont(font)
                if verdict_hop is not None and index == verdict_hop and column in (0, 1):
                    color = verdict_color
                item.setForeground(QColor(color))
                table.setItem(row, column, item)
        table.setFixedHeight(30 + max(8, min(len(hops), 30)) * 32 + 4)

    def on_diag_done(self, report):
        self.report = report or {}
        try:
            self.report_text = game_server.report_markdown(self.report)
        except Exception as e:
            self.report_text = f"Could not format the report: {e}"
        verdict = self.report.get("verdict") or {}
        zone = verdict.get("zone")
        zone = zone if zone in ZONE_LABELS else "inconclusive"
        color = zone_color(zone)
        self.fill_hops(self.report.get("hops") or [], verdict.get("hop") if zone in PROBLEM_ZONES else None, color,
                       final_zone=zone)
        self.show_verdict(zone, verdict.get("summary", ""), verdict.get("hop"))
        self.save_btn.setEnabled(True)
        self.save_btn.setToolTip("Save the diagnosis as an HTML report, Markdown and JSON")
        self.save_status.setText("")
        self.open_folder.setVisible(False)
        self.open_report.setVisible(False)
        self.saved = None
        trace_error = getattr(self.diag_thread.diagnosis, "error", None) if self.diag_thread else None
        if trace_error:
            self.diag_error = True
            self.diag_status.setText(f"The route trace reported a problem: {trace_error}")
            self.diag_status.set_color(Colors.YELLOW)

    def show_verdict(self, zone, summary, hop=None):
        if zone not in ZONE_LABELS:
            zone = "inconclusive"   # a zone this page does not know yet gets the neutral style
        color = zone_color(zone)
        title = ZONE_LABELS[zone]
        if zone in PROBLEM_ZONES:
            title = f"Problem area: {title}" + (f" (from hop {hop})" if hop is not None else "")
        self.verdict_zone.setText(title)
        self.verdict_zone.set_color(color)
        self.verdict_dot.set_state(color)
        self.verdict_summary.setText(summary)
        self.verdict.setStyleSheet(f"QFrame[card=\"card\"] {{ background-color: {rgba(color, 0.08)}; "
                                   f"border-color: {color}; }}")
        self.verdict.setVisible(True)

    def on_diag_cancelled(self):
        self.diag_error = True   # keep this status instead of "Finished"
        self.verdict.setVisible(False)
        self.save_btn.setEnabled(False)
        self.diag_status.setText("Diagnosis cancelled.")
        self.diag_status.set_color(Colors.TEXT_MUTED)

    def on_diag_failed(self, text):
        self.diag_error = True
        self.diag_status.setText(text)
        self.diag_status.set_color(Colors.RED)

    def on_diag_finished(self):
        self.diag_btn.setEnabled(True)
        self.diag_btn.setText("Start diagnosis")
        set_prop(self.diag_btn, "variant", "primary")
        self.duration_combo.setEnabled(True)
        self.diag_pulse.setVisible(False)
        if not self.diag_error:
            target = self.diag_target or {}
            place = relay_text(target.get("relay"))
            self.diag_status.setText(f"Finished {datetime.now():%H:%M} for {target.get('ip', '')}"
                                     + (f" ({place})" if place else "") + ". Save the report to keep it.")
            self.diag_status.set_color(Colors.TEXT_MUTED)
        if self.pending_target:
            pending = self.pending_target
            self.set_target(pending["ip"], pending["relay"], pending["source"])
        self.update_running()

    # ================================================================ report
    def report_folder(self):
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
        default = os.path.join(documents, "network-test-tool")
        # The monitor may store an empty folder (log to no file); reports still need a place
        folder = (self.settings.value("log_folder", default, type=str) or "").strip() or default
        return os.path.expanduser(folder)

    def save_report(self):
        if not self.report:
            return
        folder = self.report_folder()
        try:
            os.makedirs(folder, exist_ok=True)
            context = self.diag_context or {}
            paths = game_server.write_report_files(self.report, folder, detection=context.get("detection"),
                                                   scan=context.get("scan"))
        except Exception as e:   # OSError, GameServerError or anything else: show it, never crash
            self.saved = None
            self.open_report.setVisible(False)
            self.open_folder.setVisible(False)
            self.save_status.setToolTip("")
            self.save_status.setText(f"Could not save the report: {e}")
            self.save_status.set_color(Colors.RED)
            return
        self.saved = paths
        self.save_status.setText(saved_text(paths, ("html", "md", "json")))
        self.save_status.setToolTip("\n".join(paths[k] for k in ("html", "md", "json") if k in paths))
        self.save_status.set_color(Colors.TEXT_MUTED)
        self.open_report.setVisible(bool(paths.get("html")))
        self.open_folder.setVisible(True)

    def detection_for(self, target_ip):
        """The last capture result with its Valve relay, as context for a report on target_ip. None
        without a detection or when the detected server is another address: the capture's port and
        stream statistics belong to that exact server, so the report never describes a different one."""
        if not self.detection or (self.detection.get("server") or {}).get("ip") != target_ip:
            return None
        context = dict(self.detection["capture"])
        if self.detection.get("relay"):
            context["relay"] = self.detection["relay"]
        return context

    def detection_text(self):
        if not self.detection:
            return ""
        server, relay = self.detection["server"], self.detection["relay"]
        stream = self.detection["capture"].get("stream") or {}
        lines = [f"Game server: {server['ip']}:{server.get('port', '')}"
                 + (f" ({relay_text(relay)})" if relay else " (not a known Valve location)"),
                 f"Stream: {stream_status(stream)[0]}"]
        for key, title in (("packets", "Packets"), ("bursts_per_s", "Inbound per second"),
                           ("expected_per_s", "Expected per second"), ("median_gap_ms", "Median gap (ms)"),
                           ("max_gap_ms", "Max gap (ms)"), ("gaps_over_40ms", "Gaps over 40 ms")):
            if stream.get(key) is not None:
                lines.append(f"{title}: {stream[key]}")
        return "\n".join(lines)

    def scan_text(self):
        lines = ["Location | IP | Loss % | Avg ms | p95 ms | Jitter ms"]
        for r in self.scan_results:
            lines.append(" | ".join(str(r.get(k, "")) for k in ("desc", "ip", "loss_percent", "avg_ms", "p95_ms",
                                                                "jitter_ms")))
        return "\n".join(lines)

    # ================================================================ shared
    def update_running(self):
        self.set_running(any(t is not None and t.isRunning()
                             for t in (self.detect_thread, self.scan_thread, self.diag_thread)))

    def session_logs(self):
        logs = {}
        if self.detection:
            logs["Game server detection"] = self.detection_text()
        if self.scan_results:
            logs["Valve server scan"] = self.scan_text()
        if self.report_text:
            logs["Game path diagnosis"] = self.report_text
        return logs

    def cleanup(self):
        for thread in (self.detect_thread, self.scan_thread, self.diag_thread, self.process_thread):
            disconnect_worker(thread)   # no late results into a page that is being torn down
        for thread in (self.detect_thread, self.scan_thread, self.diag_thread):
            if thread is not None and thread.isRunning():
                try:
                    thread.stop()
                except Exception:
                    pass
        for thread in (self.diag_thread, self.scan_thread, self.detect_thread, self.process_thread):
            finish_thread(thread, 8000)
