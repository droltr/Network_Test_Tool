"""Office apps: find where Microsoft 365, Teams and Zoom problems come from (Wi-Fi, router, internet
provider, company network or the service), with a quick check and a meeting recorder.

All measuring is done by network/office_session.py; this page only starts it, shows the results and
saves the report. Callbacks from the backend arrive on worker threads and reach the widgets only
through Qt signals.
"""
import html
import logging
import os
import threading
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QObject, QThread, QSettings, QStandardPaths, QTimer, QUrl, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QDesktopServices, QPainter, QPen, QPainterPath, QFontMetricsF
from PyQt5.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QVBoxLayout, QProgressBar, QSizePolicy,
                             QTableWidgetItem, QWidget)

from gui.pages.base import Page, finish_thread
from gui.styles.modern_theme import Colors, mono_font, ui_font, rgba
from gui.widgets.charts import LatencyChart, nice_ceiling, axis_label, _dashed_pen
from gui.widgets.common import (Card, Label, LineInput, StatusDot, PulseDot, Badge, StatStrip, EmptyPane,
                                section_label, button, hbox, make_table, set_prop,
                                fmt_ms)
from network import office_quality
from network.report_html import m365_list_text
from network.office_quality import LAYER_LABELS, SERVICE_LABELS, mos_label, series_mos

try:
    from network import office_session
except Exception:   # the backend is optional at import time; the page explains it is missing
    office_session = None

try:
    from network.office_services import normalize_tenant
except Exception:
    normalize_tenant = None

SEVERITY_COLORS = {"ok": "GREEN", "info": "BLUE", "warn": "YELLOW", "fail": "RED"}
SEVERITY_LABELS = {"ok": "OK", "info": "Info", "warn": "Check", "fail": "Problem"}
SEVERITY_RANK = {"ok": 0, "info": 1, "warn": 2, "fail": 3}
TONE_COLORS = {"good": "GREEN", "warn": "YELLOW", "bad": "RED", "neutral": "TEXT_MUTED"}
SERVICE_ORDER = ("m365", "teams", "zoom")
CHECK_KINDS = {"dns": "DNS", "tcp": "TCP", "tls": "TLS", "https": "HTTPS", "stun": "UDP", "udp": "UDP"}
EVENT_BAD = ("disconnect", "outage", "service_failed", "dns_failed", "signal_weak")
EVENT_WARN = ("roam", "signal_drop", "rate_drop", "band_change", "ssid_change", "gateway_change")
EVENT_GOOD = ("reconnect", "signal_recovered", "restore", "service_restored", "dns_restored")
LOCATION_SETTINGS = "ms-settings:privacy-location"
CHART_CAPACITY = 300
WORKER_SIGNALS = ("progress", "done", "failed", "sample", "event", "finished")


def color(name):
    """A theme token by name, read when it is needed (tokens are set before widgets are built)."""
    return getattr(Colors, name)


def severity_color(severity):
    return color(SEVERITY_COLORS[severity]) if severity in SEVERITY_COLORS else Colors.TEXT_FAINT


def worst(severities):
    """The most severe of a list of severities, or None when the list is empty."""
    found = [s for s in severities if s in SEVERITY_RANK]
    return max(found, key=SEVERITY_RANK.get) if found else None


def clock(value):
    """'14:05:09' for a datetime or ISO string; the text itself for anything else."""
    if isinstance(value, datetime):
        return value.strftime("%H:%M:%S")
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).strftime("%H:%M:%S")
        except ValueError:
            return value
    return "" if value is None else str(value)


def fmt_elapsed(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


def fmt_pct(value):
    return "—" if value is None else f"{value:.1f}%"


def service_label(sid, checks=()):
    """Short card title for a service: the known label, else the name from the service list."""
    if sid in SERVICE_LABELS:
        return SERVICE_LABELS[sid]
    for check in checks:
        if check.get("service_id") == sid and check.get("service_name"):
            return check["service_name"]
    return sid


def open_local_file(path):
    """Open a local file or folder with the system's default app (the HTML report in the browser)."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def open_location_settings():
    """Windows Settings > Privacy & security > Location, where desktop apps get Wi-Fi details back."""
    QDesktopServices.openUrl(QUrl(LOCATION_SETTINGS))


def clear_now(layout):
    """Empty a layout and hide its widgets at once. clear_layout() only schedules the deletion, so the old
    rows would still be painted (and grabbed) until the event loop gets to it."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_now(item.layout())


def disconnect_signals(obj):
    if obj is None:
        return
    for name in WORKER_SIGNALS:
        signal = getattr(obj, name, None)
        if signal is None or not hasattr(signal, "disconnect"):
            continue   # e.g. QObject.event, a method on objects without an "event" signal
        try:
            signal.disconnect()
        except (TypeError, RuntimeError):
            pass   # nothing connected


# ---------------------------------------------------------------- workers

class ConnectionThread(QThread):
    done = pyqtSignal(str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend

    def run(self):
        try:
            self.done.emit(str(self.backend.detect_connection() or "unknown"))
        except Exception:
            self.done.emit("unknown")


class QuickThread(QThread):
    progress = pyqtSignal(str, int)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, backend, tenant, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.tenant = tenant
        self.cancel = threading.Event()

    def stop(self):
        self.cancel.set()

    def report_progress(self, stage, percent):
        # Called from the backend's worker threads: never let a bad value break the measurement
        try:
            self.progress.emit(str(stage or ""), int(percent or 0))
        except Exception:
            pass

    def run(self):
        try:
            report = self.backend.quick_test(tenant=self.tenant, cancel=self.cancel, progress=self.report_progress)
        except Exception as e:   # the backend should never raise; show it if it does
            self.failed.emit(f"The check failed: {e}")
            return
        self.done.emit(report or {})


LIVE_EVENT_ROWS_MAX = 200   # newest events kept in the live table while recording
CLEANUP_WAIT_MS = 8000      # total time cleanup() may block the GUI thread


class StopSessionThread(QThread):
    """OfficeSession.stop() joins the probes and builds the report: keep it off the GUI thread."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session

    def run(self):
        try:
            self.done.emit(self.session.stop() or {})
        except Exception as e:
            self.failed.emit(f"Could not finish the recording: {e}")


class SaveOnExitThread(QThread):
    """Stops a running recording and writes its report files when the page closes (off the GUI thread)."""

    def __init__(self, session, backend, folder, parent=None):
        super().__init__(parent)
        self.session, self.backend, self.folder = session, backend, folder

    def run(self):
        try:
            report = self.session.stop()
            if report:
                os.makedirs(self.folder, exist_ok=True)
                self.backend.write_report_files(report, self.folder)
        except Exception:
            logging.exception("Could not save the Office apps recording on exit")


def chart_values(sample):
    """({series: ms or None}, {series: title}) for one session sample."""
    values, titles = {}, {}
    if "gateway" not in (sample.get("skipped") or ()):
        values["gateway"], titles["gateway"] = sample.get("gateway"), "Router"
    values["internet"], titles["internet"] = sample.get("internet"), "Internet"
    for sid, rtt in (sample.get("media") or {}).items():
        values[f"media:{sid}"] = rtt
        titles[f"media:{sid}"] = f"{service_label(sid)} relay"
    return values, titles


class SessionBridge(QObject):
    """Receives the session callbacks on its worker thread and re-emits them as queued signals."""
    sample = pyqtSignal(object)
    event = pyqtSignal(object)


# ---------------------------------------------------------------- live chart

class LiveLatencyChart(LatencyChart):
    """The latency chart with several series (gateway, internet, media relays) over the last samples.
    Lost probes are red dashed marks; each series has its own colour and a legend at the top."""

    def __init__(self, capacity=CHART_CAPACITY, parent=None):
        super().__init__(parent)
        self.capacity = capacity
        self.samples = []        # [{name: ms or None}]
        self.order = []          # series names in first-seen order
        self.titles = {}
        self.colors = {}
        self.setMinimumHeight(190)

    def series_color(self, name):
        if name == "gateway":
            return Colors.SERIES_DOWN
        if name == "internet":
            return Colors.SERIES_UP
        second = Colors.YELLOW_FILL if QColor(Colors.YELLOW_FILL) != QColor(Colors.SERIES_UP) else Colors.TEXT_MUTED
        palette = (Colors.PURPLE, second, Colors.TEXT_MUTED)
        media = [n for n in self.order if n not in ("gateway", "internet")]
        return palette[media.index(name) % len(palette)] if name in media else Colors.TEXT

    def reset(self, expected=None):
        self.samples, self.order, self.titles = [], [], {}
        self.update()

    def add_sample(self, values, titles=None):
        for name in values:
            if name not in self.order:
                self.order.append(name)
        self.titles.update(titles or {})
        self.samples.append(dict(values))
        del self.samples[:-self.capacity]
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left, right, top, bottom = 38, 14, 28, 8
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)
        values = [v for s in self.samples for v in s.values() if v is not None]
        peak = max(values) if values else 0
        step = nice_ceiling(max(peak * 1.15, 0.3) / 3) if peak else 10
        y_max = step * 3

        p.setFont(mono_font(11))
        metrics = QFontMetricsF(p.font())
        for i in range(4):
            value = step * i
            y = plot.bottom() - plot.height() * value / y_max
            p.setPen(QPen(QColor(Colors.BORDER), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            if i:
                p.setPen(QColor(Colors.TEXT_MUTED))
                p.drawText(QPointF(4, y + metrics.ascent() / 2 - 1), axis_label(value))

        # Legend
        x = plot.left()
        p.setFont(ui_font(11.5))
        legend = QFontMetricsF(p.font())
        for name in self.order:
            title = self.titles.get(name, name)
            p.setPen(QPen(QColor(self.series_color(name)), 2.4))
            p.drawLine(QPointF(x, 11), QPointF(x + 14, 11))
            p.setPen(QColor(Colors.TEXT_MUTED))
            p.drawText(QPointF(x + 19, 11 + legend.ascent() / 2 - 1), title)
            x += 19 + legend.horizontalAdvance(title) + 16

        if not self.samples:
            p.setPen(QColor(Colors.TEXT_MUTED))
            p.setFont(ui_font(12))
            p.drawText(plot, Qt.AlignCenter, "Waiting for the first samples…")
            return

        count = max(self.capacity, 2)
        offset = self.capacity - len(self.samples)

        def x_of(i):
            return plot.left() + plot.width() * (offset + i) / (count - 1)

        def y_of(ms):
            return plot.bottom() - plot.height() * min(ms, y_max) / y_max

        p.setPen(_dashed_pen(Colors.RED, 1.0, (3, 3)))
        for i, sample in enumerate(self.samples):
            if any(sample.get(k, 0) is None for k in ("gateway", "internet")):
                xi = x_of(i)
                p.drawLine(QPointF(xi, plot.top()), QPointF(xi, plot.bottom()))

        for name in self.order:
            path = QPainterPath()
            started = False
            points = 0
            for i, sample in enumerate(self.samples):
                ms = sample.get(name)
                if ms is None:
                    started = False
                    continue
                point = QPointF(x_of(i), y_of(ms))
                if started:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                    started = True
                points += 1
            pen = QPen(QColor(self.series_color(name)), 1.8)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            if points == 1:
                p.setBrush(QColor(self.series_color(name)))
                p.drawEllipse(path.currentPosition(), 2.5, 2.5)


# ---------------------------------------------------------------- result widgets

class LayerCard(Card):
    """One measured part of the path: status light, title, status badge, key numbers and check rows."""

    def __init__(self, key, title):
        super().__init__(margins=(14, 11, 14, 12), spacing=6)
        self.key = key
        self.dot = StatusDot(Colors.TEXT_FAINT, 8)
        self.title = Label(title, 13, 600, Colors.TEXT_STRONG)
        self.badge = Badge("", Colors.TEXT_MUTED)
        self.body.addLayout(hbox(self.dot, self.title, "stretch", self.badge, spacing=6))
        self.rows = QGridLayout()
        self.rows.setHorizontalSpacing(10)
        self.rows.setVerticalSpacing(3)
        self.rows.setColumnStretch(1, 1)
        self.body.addLayout(self.rows)
        self.note = Label("", 11.5, color=Colors.TEXT_MUTED)
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        self.body.addWidget(self.note)
        self.body.addStretch(1)
        self.severity = None

    def set_status(self, severity, text=None):
        self.severity = severity
        tone = severity_color(severity)
        self.dot.set_state(tone, "filled" if severity else "hollow")
        self.badge.setText(text or SEVERITY_LABELS.get(severity, "Not measured"))
        self.badge.set_tone(tone if severity else Colors.TEXT_MUTED)

    def set_rows(self, rows):
        """rows: [(label, value, colour or None, tooltip or '')]; colour None = normal text."""
        clear_now(self.rows)
        for index, row in enumerate(rows):
            label, value, tone = row[0], row[1], row[2] if len(row) > 2 else None
            tooltip = row[3] if len(row) > 3 else ""
            name = Label(label, 11.5, color=Colors.TEXT_MUTED)
            name.setWordWrap(True)
            text = Label(value, 12, 500, tone or Colors.TEXT_STRONG, mono=True)
            text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if tooltip:
                name.setToolTip(tooltip)
                text.setToolTip(tooltip)
            self.rows.addWidget(name, index, 0, 1, 2)
            self.rows.addWidget(text, index, 2)

    def set_note(self, text, tone=None):
        self.note.setText(text or "")
        self.note.set_color(tone or Colors.TEXT_MUTED)
        self.note.setVisible(bool(text))


class FindingRow(Card):
    def __init__(self, finding):
        super().__init__(margins=(14, 10, 14, 10), spacing=4)
        severity = finding.get("severity")
        tone = severity_color(severity)
        top = hbox(StatusDot(tone, 8), Label(finding.get("title") or "", 13, 600, Colors.TEXT_STRONG), spacing=8)
        top.addStretch(1)
        if finding.get("uncertain"):
            guess = Badge("Best guess", Colors.TEXT_MUTED)
            guess.setToolTip("An upstream measurement is missing, so this layer is the most likely one, not a "
                             "certain one.")
            top.addWidget(guess)
        top.addWidget(Badge(SEVERITY_LABELS.get(severity, severity or ""), tone))
        self.body.addLayout(top)
        if severity in ("warn", "fail"):
            self.setStyleSheet(f"QFrame[card=\"card\"] {{ border-color: {tone}; }}")
        summary = Label(finding.get("summary") or "", 12.5, color=Colors.TEXT)
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.addWidget(summary)
        for line in (finding.get("evidence") or [])[:6]:
            evidence = Label(str(line), 11.5, color=Colors.TEXT_MUTED, mono=True)
            evidence.setWordWrap(True)
            evidence.setTextInteractionFlags(Qt.TextSelectableByMouse)
            evidence.setContentsMargins(20, 0, 0, 0)
            self.body.addWidget(evidence)
        if finding.get("fix"):
            fix = Label(f"<b>Fix:</b> {html.escape(finding['fix'])}", 12, color=Colors.TEXT_STRONG)
            fix.setTextFormat(Qt.RichText)
            fix.setWordWrap(True)
            fix.setTextInteractionFlags(Qt.TextSelectableByMouse)
            fix.setContentsMargins(0, 2, 0, 0)
            self.body.addWidget(fix)


# ---------------------------------------------------------------- page

class OfficePage(Page):
    def __init__(self, backend=None):
        super().__init__("Office apps", scroll=True)
        self.header.set_subtitle("Microsoft 365, Teams and Zoom · find where call and app problems come from")
        self.backend = backend if backend is not None else office_session
        self.settings = QSettings("NetworkTools", "Office")
        self.health_settings = QSettings("NetworkTools", "Health")   # shares the report folder with other pages
        self.connection_thread = None
        self.connection_checked = False
        self.quick_thread = None
        self.stop_thread = None
        self.session = None
        self.bridge = None
        self.record_started = None
        self.event_count = 0
        self.outage_count = 0
        self.sample_count = 0
        self.report = None
        self.report_text = ""
        self.saved = None
        self.copy_reset = QTimer(self)
        self.copy_reset.setSingleShot(True)
        self.copy_reset.timeout.connect(lambda: self.copy_btn.setText("Copy summary"))
        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self.update_elapsed)

        self.body.addWidget(self.build_setup())
        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addWidget(self.build_quick_card(), 1)
        actions.addWidget(self.build_record_card(), 1)
        self.body.addLayout(actions)
        live = self.build_live()
        self.empty = EmptyPane("No check yet", "Run a quick check now, or record your next meeting to catch "
                                               "problems while they happen.")
        self.empty.setMinimumHeight(150)
        self.body.addWidget(self.empty)
        # While recording only the live view shows; afterwards the verdict and findings come first
        self.body.addWidget(self.build_results())
        self.body.addWidget(live)
        self.body.addStretch(1)
        self.update_availability()

    # ================================================================ setup
    def build_setup(self):
        card = Card(margins=(16, 12, 16, 12), spacing=8)
        intro = Label("Checks each part of the path an office app uses: your Wi-Fi, the router, the internet "
                      "connection and the Microsoft 365, Teams and Zoom servers. It tells you where a problem is and "
                      "what to do about it. Nothing is changed on your computer.", 12.5, color=Colors.TEXT)
        intro.setWordWrap(True)
        card.body.addWidget(intro)
        self.tenant = LineInput("optional, e.g. contoso", height=30)
        self.tenant.setFixedWidth(330)
        self.tenant.setText(self.settings.value("tenant", "", type=str) or "")
        self.tenant.editingFinished.connect(self.save_tenant)
        hint = Label("Adds your company's SharePoint and OneDrive addresses to the checks. Leave it empty if you "
                     "do not know it.", 11.5, color=Colors.TEXT_MUTED)
        hint.setWordWrap(True)
        row = hbox(Label("Organization domain", 12, color=Colors.TEXT_MUTED), self.tenant, 8, hint, spacing=8)
        row.setStretchFactor(hint, 1)
        card.body.addLayout(row)
        self.connection_dot = StatusDot(Colors.TEXT_FAINT, 8, "dashed")
        self.connection_label = Label("Connection: checking…", 12, color=Colors.TEXT_MUTED)
        card.body.addLayout(hbox(self.connection_dot, self.connection_label, "stretch", spacing=6))
        return card

    def tenant_value(self):
        """(tenant or None, error text). The raw text is normalized the way the service checks do it."""
        text = self.tenant.text().strip()
        if not text:
            return None, ""
        value = normalize_tenant(text) if normalize_tenant else text
        if not value:
            return None, "The organization domain is not valid. Use a name like contoso or contoso.sharepoint.com."
        return value, ""

    def save_tenant(self):
        self.settings.setValue("tenant", self.tenant.text().strip())

    def showEvent(self, event):
        super().showEvent(event)
        if not self.connection_checked:
            self.refresh_connection()

    def refresh_connection(self):
        if self.backend is None or not hasattr(self.backend, "detect_connection"):
            self.on_connection("unknown")
            return
        if self.connection_thread and self.connection_thread.isRunning():
            return
        self.connection_checked = True
        self.connection_thread = ConnectionThread(self.backend, self)
        self.connection_thread.done.connect(self.on_connection)
        self.connection_thread.start()

    def on_connection(self, kind):
        text = {"wifi": "Wi-Fi", "ethernet": "Ethernet (cable)"}.get(kind, "unknown")
        self.connection_dot.set_state(Colors.GREEN if kind in ("wifi", "ethernet") else Colors.TEXT_FAINT,
                                      "filled" if kind in ("wifi", "ethernet") else "hollow")
        self.connection_label.setText(f"Connection: {text}"
                                      + (" · Wi-Fi is checked too" if kind == "wifi" else ""))
        self.connection_label.set_color(Colors.TEXT if kind in ("wifi", "ethernet") else Colors.TEXT_MUTED)

    # ================================================================ quick check
    def build_quick_card(self):
        card = Card(margins=(16, 14, 16, 14), spacing=8)
        card.body.addWidget(section_label("Quick check"))
        text = Label("About 10 to 30 seconds (longer when the router does not answer ping). Measures the Wi-Fi, "
                     "router and internet, and tests every Microsoft 365, Teams and Zoom address once.", 12, color=Colors.TEXT_MUTED)
        text.setWordWrap(True)
        card.body.addWidget(text)
        self.quick_btn = button("Run quick check", "primary", 34, width=170)
        self.quick_btn.clicked.connect(self.toggle_quick)
        self.quick_bar = QProgressBar()
        self.quick_bar.setTextVisible(False)
        self.quick_bar.setRange(0, 100)
        self.quick_bar.setFixedHeight(6)
        self.quick_bar.setVisible(False)
        card.body.addLayout(hbox(self.quick_btn, "stretch"))
        card.body.addWidget(self.quick_bar)
        self.quick_status = Label("", 12, color=Colors.TEXT_MUTED)
        self.quick_status.setWordWrap(True)
        card.body.addWidget(self.quick_status)
        card.body.addStretch(1)
        return card

    def toggle_quick(self):
        if self.quick_thread and self.quick_thread.isRunning():
            self.quick_thread.stop()
            self.quick_btn.setEnabled(False)
            self.quick_btn.setText("Stopping…")
            return
        if self.busy():
            return
        tenant, error = self.tenant_value()
        if error:
            self.tenant.set_error(True)
            self.set_quick_status(error, Colors.RED)
            return
        self.save_tenant()
        self.quick_thread = QuickThread(self.backend, tenant, self)
        self.quick_thread.progress.connect(self.on_quick_progress)
        self.quick_thread.done.connect(self.on_quick_done)
        self.quick_thread.failed.connect(lambda text: self.set_quick_status(text, Colors.RED))
        self.quick_thread.finished.connect(self.on_quick_finished)
        self.quick_btn.setText("Stop")
        set_prop(self.quick_btn, "variant", "stop")
        self.quick_bar.setValue(0)
        self.quick_bar.setVisible(True)
        self.set_quick_status("Starting…", Colors.BLUE)
        self.quick_thread.start()
        self.update_running()

    def set_quick_status(self, text, tone):
        self.quick_status.setText(text)
        self.quick_status.set_color(tone)

    def on_quick_progress(self, stage, percent):
        self.quick_bar.setValue(max(0, min(100, percent)))
        if stage:
            self.set_quick_status(stage, Colors.BLUE)

    def on_quick_done(self, report):
        stopped = bool(self.quick_thread and self.quick_thread.cancel.is_set())
        self.show_report(report)
        if stopped:
            self.set_quick_status("Stopped early. The results below are partial.", Colors.YELLOW)
        else:
            self.set_quick_status(f"Finished {datetime.now():%H:%M}.", Colors.TEXT_MUTED)

    def on_quick_finished(self):
        self.quick_btn.setEnabled(True)
        self.quick_btn.setText("Run quick check")
        set_prop(self.quick_btn, "variant", "primary")
        self.quick_bar.setVisible(False)
        self.update_running()
        self.update_availability()

    # ================================================================ recording
    def build_record_card(self):
        card = Card(margins=(16, 14, 16, 14), spacing=8)
        card.body.addWidget(section_label("Record a meeting"))
        text = Label("Start before a call and stop after it. Logs Wi-Fi drops, roams, outages and service failures "
                     "with their times.", 12, color=Colors.TEXT_MUTED)
        text.setWordWrap(True)
        card.body.addWidget(text)
        self.session_label = LineInput("Label (optional), e.g. weekly team call", height=30, mono=False)
        self.record_btn = button("Start recording", "secondary", 34, width=150)
        self.record_btn.clicked.connect(self.toggle_recording)
        row = hbox(self.session_label, self.record_btn, spacing=8)
        row.setStretchFactor(self.session_label, 1)
        card.body.addLayout(row)
        self.record_dot = PulseDot(Colors.RED, 9)
        self.record_dot.setVisible(False)
        self.record_status = Label("", 12, color=Colors.TEXT_MUTED)
        self.record_status.setWordWrap(True)
        status = hbox(self.record_dot, self.record_status, spacing=6)
        status.setStretchFactor(self.record_status, 1)
        card.body.addLayout(status)
        card.body.addStretch(1)
        return card

    def toggle_recording(self):
        if self.session is not None:
            self.stop_recording()
            return
        if self.busy():
            return
        tenant, error = self.tenant_value()
        if error:
            self.tenant.set_error(True)
            self.set_record_status(error, Colors.RED)
            return
        self.save_tenant()
        bridge = SessionBridge(self)
        bridge.sample.connect(self.on_sample)
        bridge.event.connect(self.on_event)
        try:
            session = self.backend.OfficeSession(tenant=tenant, label=self.session_label.text().strip(),
                                                 on_sample=bridge.sample.emit, on_event=bridge.event.emit)
            session.start()
        except Exception as e:
            disconnect_signals(bridge)
            bridge.deleteLater()
            self.set_record_status(f"Could not start recording: {e}", Colors.RED)
            return
        self.session, self.bridge = session, bridge
        self.record_started = time.monotonic()
        self.event_count = self.outage_count = self.sample_count = 0
        self.chart.reset()
        self.events_table.setRowCount(0)
        self.live_stats.reset()
        self.live_stats.set("outages", "0")
        self.events_table.setFixedHeight(30 + 6 * 32 + 4)
        self.results.setVisible(False)   # the previous result would push the live view down
        self.empty.setVisible(False)
        self.live_card.setVisible(True)
        self.live_title.setText("Live · recording")
        self.record_btn.setText("Stop recording")
        set_prop(self.record_btn, "variant", "stop")
        self.session_label.setEnabled(False)
        self.tenant.setEnabled(False)
        self.record_dot.setVisible(True)
        self.record_timer.start(1000)
        self.update_elapsed()
        self.update_running()
        self.update_availability()

    def set_record_status(self, text, tone):
        self.record_status.setText(text)
        self.record_status.set_color(tone)

    def update_elapsed(self):
        if self.session is None or self.record_started is None:
            return
        elapsed = fmt_elapsed(time.monotonic() - self.record_started)
        self.set_record_status(f"Recording {elapsed} · {self.event_count} event{'s' if self.event_count != 1 else ''}"
                               f" · {self.outage_count} outage{'s' if self.outage_count != 1 else ''}",
                               Colors.TEXT_STRONG)

    def stop_recording(self):
        if self.session is None or (self.stop_thread and self.stop_thread.isRunning()):
            return
        self.record_btn.setEnabled(False)
        self.record_btn.setText("Stopping…")
        self.record_timer.stop()
        self.set_record_status("Finishing the recording and building the report…", Colors.BLUE)
        self.stop_thread = StopSessionThread(self.session, self)
        self.stop_thread.done.connect(self.on_session_stopped)
        self.stop_thread.failed.connect(self.on_session_failed)
        self.stop_thread.finished.connect(self.on_stop_finished)
        self.stop_thread.start()

    def on_session_stopped(self, report):
        elapsed = fmt_elapsed(time.monotonic() - self.record_started) if self.record_started else ""
        self.end_session()
        self.show_report(report)
        outages = len(report.get("outages") or [])
        self.set_record_status(f"Recorded {elapsed} · {len(report.get('events') or [])} event(s) · {outages} "
                               f"outage(s).", Colors.RED if outages else Colors.TEXT_MUTED)

    def on_session_failed(self, text):
        self.end_session()
        self.set_record_status(text, Colors.RED)

    def on_stop_finished(self):
        self.update_running()
        self.update_availability()

    def end_session(self):
        disconnect_signals(self.bridge)
        if self.bridge is not None:
            self.bridge.deleteLater()
        self.session, self.bridge = None, None
        self.record_timer.stop()
        self.record_btn.setEnabled(True)
        self.record_btn.setText("Start recording")
        set_prop(self.record_btn, "variant", "secondary")
        self.session_label.setEnabled(True)
        self.tenant.setEnabled(True)
        self.record_dot.setVisible(False)
        self.live_title.setText("Live · last recording")

    # ================================================================ live view
    def build_live(self):
        card = Card(margins=(16, 12, 16, 12), spacing=10)
        self.live_card = card
        self.live_title = section_label("Live · recording")
        card.body.addWidget(self.live_title)
        self.live_stats = StatStrip([("signal", "Wi-Fi signal"), ("gateway", "Router"), ("internet", "Internet"),
                                     ("media", "Call relays"), ("outages", "Outages")], 14)
        card.body.addWidget(self.live_stats)
        self.chart = LiveLatencyChart()
        self.chart.setMinimumHeight(200)
        card.body.addWidget(self.chart)
        card.body.addWidget(section_label("Events"))
        self.events_table = make_table(["Time", "Event", "Layer"], stretch_column=1)
        self.events_table.horizontalHeader().resizeSection(0, 96)
        self.events_table.horizontalHeader().resizeSection(2, 200)
        self.events_table.setFixedHeight(30 + 6 * 32 + 4)
        card.body.addWidget(self.events_table)
        card.setVisible(False)
        return card

    def on_sample(self, sample):
        if self.session is None or not isinstance(sample, dict):
            return
        self.sample_count += 1
        self.chart.add_sample(*chart_values(sample))
        media = sample.get("media") or {}
        rssi, percent = sample.get("rssi_dbm"), sample.get("signal_percent")
        if rssi is not None or percent is not None:
            text = " · ".join(t for t in ((f"{rssi} dBm" if rssi is not None else ""),
                                           (f"{percent}%" if percent is not None else "")) if t)
            tone = Colors.RED if rssi is not None and rssi <= office_quality.RSSI_FAIL else \
                Colors.YELLOW if rssi is not None and rssi <= office_quality.RSSI_WARN else Colors.TEXT_STRONG
            self.live_stats.set("signal", text, tone)
        else:
            self.live_stats.set("signal", None)
        for key in ("gateway", "internet"):
            rtt = sample.get(key)
            if key == "gateway" and "gateway" in (sample.get("skipped") or ()):
                self.live_stats.set("gateway", "not probed", Colors.TEXT_MUTED)
            elif key in sample:
                self.live_stats.set(key, "lost" if rtt is None else fmt_ms(rtt), Colors.RED if rtt is None
                                    else Colors.TEXT_STRONG)
        if media:
            parts = [("lost" if rtt is None else f"{rtt:.0f}") for rtt in media.values()]
            lost = any(rtt is None for rtt in media.values())
            self.live_stats.set("media", " / ".join(parts) + ("" if all(r is None for r in media.values())
                                                               else " ms"), Colors.RED if lost else Colors.TEXT_STRONG)

    def on_event(self, event):
        if self.session is None or not isinstance(event, dict):
            return
        self.event_count += 1
        if event.get("kind") == "outage":
            self.outage_count += 1
            self.live_stats.set("outages", str(self.outage_count), Colors.RED)
        self.add_event_row(event, top=True)
        while self.events_table.rowCount() > LIVE_EVENT_ROWS_MAX:   # the full list comes from the report
            self.events_table.removeRow(self.events_table.rowCount() - 1)
        self.update_elapsed()

    def add_event_row(self, event, top=False):
        table = self.events_table
        row = 0 if top else table.rowCount()
        table.insertRow(row)
        kind = event.get("kind") or ""
        tone = (Colors.RED if kind in EVENT_BAD else Colors.YELLOW if kind in EVENT_WARN
                else Colors.GREEN if kind in EVENT_GOOD else Colors.TEXT)
        layer = event.get("layer")
        values = ((clock(event.get("time")), Colors.TEXT_MUTED, mono_font(12)),
                  (event.get("text") or kind.replace("_", " "), tone, ui_font(12.5)),
                  (LAYER_LABELS.get(layer, layer or ""), Colors.TEXT, ui_font(12)))
        for column, (text, tint, font) in enumerate(values):
            item = QTableWidgetItem(str(text))
            item.setForeground(QColor(tint))
            item.setFont(font)
            if column == 1 and event.get("details"):
                item.setToolTip(str(event["details"]))
            table.setItem(row, column, item)

    # ================================================================ results
    def build_results(self):
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.results = holder

        self.verdict = Card(margins=(16, 12, 16, 12), spacing=4)
        self.verdict_kicker = Label("", 11.5, color=Colors.TEXT_MUTED)
        self.verdict_dot = StatusDot(Colors.GREEN, 10)
        self.verdict_title = Label("", 15, 600, Colors.TEXT_STRONG)
        self.verdict_title.setWordWrap(True)
        self.verdict.body.addWidget(self.verdict_kicker)
        title_row = hbox(self.verdict_dot, self.verdict_title, spacing=8)
        title_row.setStretchFactor(self.verdict_title, 1)
        self.verdict.body.addLayout(title_row)
        self.verdict_text = Label("", 12.5, color=Colors.TEXT)
        self.verdict_text.setWordWrap(True)
        self.verdict_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.verdict.body.addWidget(self.verdict_text)
        self.open_report_btn = button("Open report", "primary", 30)
        self.open_report_btn.setToolTip("Save the report (HTML, Markdown, JSON) and open it in your browser")
        self.open_report_btn.clicked.connect(self.open_report)
        self.open_folder_btn = button("Open log folder", "secondary", 30)
        self.open_folder_btn.clicked.connect(self.open_log_folder)
        self.copy_btn = button("Copy summary", "secondary", 30)
        self.copy_btn.setToolTip("Copy the report as Markdown, e.g. for a ticket to IT")
        self.copy_btn.clicked.connect(self.copy_summary)
        self.save_status = Label("", 11, color=Colors.TEXT_MUTED, mono=True)
        self.save_status.setWordWrap(True)
        self.save_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.save_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        actions = hbox(self.open_report_btn, self.open_folder_btn, self.copy_btn, 8, self.save_status, spacing=8)
        actions.setStretchFactor(self.save_status, 1)
        self.verdict.body.addSpacing(6)
        self.verdict.body.addLayout(actions)
        layout.addWidget(self.verdict)

        self.location_notice = Card("note", margins=(14, 10, 14, 10), spacing=6)
        notice_text = Label("Windows is hiding Wi-Fi details (network name, access point, link rate) from this app because "
                            "location access is off for desktop apps. Turn on “Let desktop apps access your "
                            "location”, then run the check again.", 12.5, color=Colors.TEXT)
        notice_text.setWordWrap(True)
        self.location_btn = button("Open location settings", "ghost", 30)
        self.location_btn.clicked.connect(lambda: open_location_settings())
        notice_row = hbox(StatusDot(Colors.YELLOW, 8), notice_text, 8, self.location_btn, spacing=8)
        notice_row.setStretchFactor(notice_text, 1)
        self.location_notice.body.addLayout(notice_row)
        layout.addWidget(self.location_notice)

        self.errors_note = Label("", 11.5, color=Colors.TEXT_MUTED)
        self.errors_note.setWordWrap(True)
        layout.addWidget(self.errors_note)

        self.cards_grid = QGridLayout()
        self.cards_grid.setHorizontalSpacing(12)
        self.cards_grid.setVerticalSpacing(12)
        for column in range(3):
            self.cards_grid.setColumnStretch(column, 1)
        layout.addLayout(self.cards_grid)
        self.cards = {}

        self.correlation_card = Card(margins=(16, 12, 16, 12), spacing=6)
        self.correlation_card.body.addWidget(section_label("What happened at the same time"))
        self.correlation_rows = QVBoxLayout()
        self.correlation_rows.setSpacing(4)
        self.correlation_card.body.addLayout(self.correlation_rows)
        layout.addWidget(self.correlation_card)

        layout.addWidget(section_label("Findings"))
        self.findings_layout = QVBoxLayout()
        self.findings_layout.setSpacing(8)
        layout.addLayout(self.findings_layout)
        holder.setVisible(False)
        return holder

    def show_report(self, report):
        report = report if isinstance(report, dict) else {}
        self.report = report
        self.saved = None
        self.save_status.setText("")
        self.save_status.setToolTip("")
        try:
            self.report_text = self.backend.report_markdown(report)
        except Exception as e:
            self.report_text = f"Could not format the report: {e}"
        snapshot = report.get("snapshot") or {}
        findings = [f for f in report.get("findings") or [] if isinstance(f, dict)]
        self.fill_verdict(report)
        wifi = snapshot.get("wifi") or {}
        self.location_notice.setVisible(wifi.get("reason") == "location_permission")
        errors = [str(e) for e in report.get("errors") or [] if e]
        self.errors_note.setText(("Some measurements could not run: " + "; ".join(errors[:4])
                                  + (" …" if len(errors) > 4 else "")) if errors else "")
        self.errors_note.setVisible(bool(errors))
        self.fill_cards(snapshot, findings)
        self.fill_correlations(report)
        self.fill_findings(findings)
        if report.get("kind") == "session":
            self.fill_session_live(report)
        self.empty.setVisible(False)
        self.results.setVisible(True)

    def fill_verdict(self, report):
        verdict = report.get("verdict") or {}
        tone = color(TONE_COLORS.get(verdict.get("tone"), "TEXT_MUTED"))
        layer = verdict.get("layer")
        headline = verdict.get("headline") or LAYER_LABELS.get(layer, "Result")
        kind = "Meeting recording" if report.get("kind") == "session" else "Quick check"
        parts = [kind]
        if report.get("label"):
            parts.append(str(report["label"]))
        started = report.get("started")
        if started:
            parts.append(clock(started)[:5] + (f"–{clock(report.get('ended'))[:5]}" if report.get("ended") and
                                               report.get("kind") == "session" else ""))
        if report.get("tenant"):
            parts.append(f"organization {report['tenant']}")
        self.verdict_kicker.setText(" · ".join(parts))
        self.verdict_title.setText(headline)
        self.verdict_title.set_color(tone if verdict.get("tone") in ("warn", "bad") else Colors.TEXT_STRONG)
        self.verdict_dot.set_state(tone, "filled" if verdict.get("tone") != "neutral" else "hollow")
        self.verdict_text.setText(verdict.get("text") or "")
        self.verdict.setStyleSheet(f"QFrame[card=\"card\"] {{ background-color: {rgba(tone, 0.08)}; "
                                   f"border-color: {tone}; }}")
        self.open_folder_btn.setVisible(True)

    # ---------------------------------------------------------------- cards
    def card(self, key, title):
        card = self.cards.get(key)
        if card is None:
            card = LayerCard(key, title)
            self.cards[key] = card
        card.title.setText(title)
        return card

    def fill_cards(self, snapshot, findings):
        for card in self.cards.values():
            self.cards_grid.removeWidget(card)
            card.setVisible(False)
        order = [self.wifi_card(snapshot, findings), self.local_card(snapshot, findings),
                 self.internet_card(snapshot, findings)]
        checks = [c for c in snapshot.get("services") or [] if isinstance(c, dict)]
        media = snapshot.get("media") or {}
        sids = list(SERVICE_ORDER)
        for sid in [c.get("service_id") for c in checks] + list(media):
            if sid and sid not in sids:
                sids.append(sid)
        for sid in sids:
            order.append(self.service_card(sid, snapshot, checks, findings))
        for index, card in enumerate(order):
            self.cards_grid.addWidget(card, index // 3, index % 3)
            card.setVisible(True)

    def wifi_card(self, snapshot, findings):
        card = self.card("wifi", "Wi-Fi")
        connection = snapshot.get("connection") or "unknown"
        wifi = snapshot.get("wifi") or {}
        card.set_note("")
        if connection == "ethernet":
            card.set_status(None, "Not used")
            card.set_rows([])
            card.set_note("This computer is on a network cable, so Wi-Fi is not part of the path.")
            return card
        blocked = wifi.get("reason") == "location_permission"
        measured = any(wifi.get(k) is not None for k in ("rssi_dbm", "signal_percent", "band", "channel"))
        if not blocked and (not wifi or wifi.get("connected") is False or wifi.get("available") is False):
            card.set_status(None, "Not measured")
            card.set_rows([])
            card.set_note(wifi.get("message") or "No Wi-Fi connection was found.")
            return card
        rows = self.wifi_rows(snapshot, wifi)
        if blocked:
            # Windows hides the network name, access point and rates; signal, band and channel may remain
            card.set_status("warn", "Details blocked")
            card.set_rows([row for row in rows if row[0] in ("Signal", "Band", "Channel congestion")
                           and row[1] != "—"] if measured else [])
            card.set_note("Windows hides the network name, access point and link rate until location access is "
                          "on (see the notice above).", Colors.YELLOW)
            return card
        severity = worst(f["severity"] for f in findings if f.get("layer") == "wifi" and f.get("id") != "use_ethernet")
        card.set_status(severity or "ok")
        card.set_rows(rows)
        return card

    @staticmethod
    def wifi_rows(snapshot, wifi):
        rssi, percent = wifi.get("rssi_dbm"), wifi.get("signal_percent")
        if rssi is None and percent is not None:
            rssi = round(percent / 2 - 100)
        signal_tone = None
        if rssi is not None:
            signal_tone = (Colors.RED if rssi <= office_quality.RSSI_FAIL else
                           Colors.YELLOW if rssi <= office_quality.RSSI_WARN else None)
        signal = " · ".join(t for t in ((f"{rssi} dBm" if rssi is not None else ""),
                                        (f"{percent}%" if percent is not None else "")) if t) or "—"
        band = wifi.get("band") or ""
        channel = wifi.get("channel")
        band_text = " · ".join(t for t in (band, f"channel {channel}" if channel else "") if t) or "—"
        congestion = (snapshot.get("congestion") or {}).get("level")
        congestion_tone = {"high": Colors.YELLOW, "medium": Colors.YELLOW}.get(congestion)
        events = snapshot.get("wifi_events") or []
        roams = sum(1 for e in events if e.get("kind") == "roam")
        drops = sum(1 for e in events if e.get("kind") == "disconnect")
        rates = [r for r in (wifi.get("rx_rate_mbps"), wifi.get("tx_rate_mbps")) if r is not None]
        rows = [("Network", wifi.get("ssid") or "hidden network", None, wifi.get("bssid") or ""),
                ("Signal", signal, signal_tone),
                ("Band", band_text, None),
                ("Link rate", f"{min(rates):g} Mbps" if rates else "—",
                 Colors.YELLOW if rates and min(rates) < office_quality.LINK_RATE_WARN else None),
                ("Channel congestion", congestion or "—", congestion_tone),
                ("Roams", str(roams), Colors.YELLOW if roams >= office_quality.ROAMS_WARN else None)]
        if drops:
            rows.append(("Disconnects", str(drops), Colors.RED))
        return rows

    def series_rows(self, series):
        loss = series.get("loss_pct")
        return [("Packet loss", fmt_pct(loss) + f"  ({series.get('lost', 0)}/{series.get('sent', 0)})",
                 Colors.RED if (loss or 0) >= 5 else Colors.YELLOW if (loss or 0) >= 1 else None),
                ("Average", fmt_ms(series.get("avg_ms")), None),
                ("Jitter", fmt_ms(series.get("jitter_ms")), None)]

    def local_card(self, snapshot, findings):
        card = self.card("local", "Local network")
        card.set_note("")
        gateway = snapshot.get("gateway")
        gateway_info = ("gateway_silent", "gateway_changed")
        related = [f["severity"] for f in findings if f.get("id") == "gateway_loss" or
                   (f.get("layer") == "local" and f.get("id") not in ("dns",) + gateway_info)]
        silent = any(f.get("id") == "gateway_silent" for f in findings)
        changed = any(f.get("id") == "gateway_changed" for f in findings)
        addresses = snapshot.get("gateway_addresses") or []
        change_note = ("The default gateway changed during the recording (" + " -> ".join(addresses) + "). "
                       "These figures cover the current gateway only.") if changed else ""
        if not gateway or not gateway.get("sent"):
            card.set_status(worst(related), None if related else "Not measured")
            card.set_rows([])
            card.set_note(" ".join(t for t in ("The router (default gateway) was not measured.", change_note) if t))
            return card
        rows = self.series_rows(gateway)
        if changed and addresses:
            rows.append(("Gateways seen", " -> ".join(addresses), None))
        if silent:
            # The router ignores ping while traffic beyond it gets through: information, not a failure.
            loss = gateway.get("loss_pct")
            rows[0] = ("Ping replies", f"{fmt_pct(100 - loss) if loss is not None else '—'}  "
                       f"({gateway.get('sent', 0) - gateway.get('lost', 0)}/{gateway.get('sent', 0)})", None)
            card.set_status("info", "No ping reply")
            card.set_rows(rows)
            card.set_note(" ".join(t for t in (
                "The router does not answer ping. This is normal for many routers; the path beyond it is fine.",
                change_note) if t))
            return card
        card.set_status(worst(related) or "ok")
        card.set_rows(rows)
        card.set_note(change_note)
        return card

    def internet_card(self, snapshot, findings):
        card = self.card("internet", "Internet")
        card.set_note("")
        internet = snapshot.get("internet")
        dns = snapshot.get("dns") or {}
        related = [f["severity"] for f in findings if f.get("id") in ("internet_loss", "dns")
                   or f.get("layer") == "isp"]
        rows = self.series_rows(internet) if internet and internet.get("sent") else []
        if dns:
            ok = dns.get("ok")
            rows.append(("DNS lookup", fmt_ms(dns.get("ms")) if ok else "failed" if ok is False else "—",
                         Colors.RED if ok is False else None, f"DNS server: {dns.get('server') or 'system resolver'}"))
        if not rows:
            card.set_status(worst(related), None if related else "Not measured")
            card.set_rows([])
            card.set_note("The internet connection was not measured.")
            return card
        severity = worst(related) or "ok"
        follows = any(f.get("id") == "internet_loss" and f.get("severity") == "info" for f in findings)
        if severity == "info" and follows:
            # Loss here that the router link already explains: a real symptom, not the place to fix
            card.set_status("warn", "Follows router")
            card.set_note("This loss starts on the link to the router; fix that first.")
        else:
            card.set_status(severity)
        card.set_rows(rows)
        return card

    def service_card(self, sid, snapshot, checks, findings):
        own = [c for c in checks if c.get("service_id") == sid]
        card = self.card(f"service:{sid}", service_label(sid, checks))
        card.set_note("")
        tested = [c for c in own if c.get("ok") is not None]
        failed = [c for c in tested if c.get("ok") is False]
        severities = []
        if failed:
            severities.append("fail" if len(failed) == len(tested) else "warn")
        severities += [f["severity"] for f in findings
                       if f.get("id") in (f"service_{sid}", f"call_quality_{sid}") and f.get("severity") != "info"]
        if any(f.get("id") == "udp_blocked" and service_label(sid, checks) in (f.get("summary") or "")
               for f in findings):
            severities.append("warn")
        rows = []
        for check in own:
            kind = CHECK_KINDS.get(check.get("kind"), (check.get("kind") or "").upper())
            name = check.get("name") or check.get("check_id") or kind
            target = f"{check.get('host')}" + (f":{check['port']}" if check.get("port") else "")
            tooltip = f"{kind} {target}" + (f"\n{check['error']}" if check.get("error") else "")
            if check.get("category") and check.get("category_source") == "m365":
                tooltip += f"\nMicrosoft category: {check['category']} (Microsoft's current address list)"
            if check.get("ok") is None:
                rows.append((f"{name}", "untested", Colors.TEXT_FAINT, tooltip))
            elif check.get("ok"):
                rows.append((f"{name}", fmt_ms(check.get("ms"), 0), None, tooltip))
            else:
                rows.append((f"{name}", "failed", Colors.RED, tooltip))
        series = (snapshot.get("media") or {}).get(sid)
        if series and series.get("sent"):
            mos = series_mos(series)
            label = mos_label(mos)
            quality_tone = {"Good": None, "Fair": None, "Poor": Colors.YELLOW, "Bad": Colors.RED}.get(label)
            loss = series.get("loss_pct")
            if series.get("avg_ms") is None:
                rows.append(("Call relay", "no answer", Colors.RED))
            else:
                rows.append(("Call relay RTT", fmt_ms(series.get("avg_ms")), None))
                rows.append(("Call relay jitter", fmt_ms(series.get("jitter_ms")), None))
                rows.append(("Call relay loss", fmt_pct(loss),
                             Colors.RED if (loss or 0) >= 5 else Colors.YELLOW if (loss or 0) >= 1 else None))
                rows.append(("Call quality (estimate)", f"{label} · MOS {mos:.1f}" if mos is not None else label,
                             quality_tone, "Estimated from network numbers only (simplified ITU-T G.107 E-model)"))
        card.set_rows(rows)
        if not tested and not (series and series.get("sent")):
            card.set_status(None, "Not tested")
            card.set_note("No checks ran for this service." if not own else "The checks did not run.")
        else:
            card.set_status(worst(severities) or "ok")
            listing = m365_list_text(snapshot.get("m365_endpoints"))
            if sid == "m365" and listing:
                card.set_note(f"Microsoft 365 address list: {listing}")
        return card

    # ---------------------------------------------------------------- findings and correlations
    def fill_correlations(self, report):
        clear_now(self.correlation_rows)
        lines = [str(line) for line in report.get("correlations") or [] if line]
        outages = report.get("outages") or []
        for outage in outages[:8]:
            lines.append(self.outage_text(outage))
        for line in lines:
            text = Label(line, 12.5, color=Colors.TEXT)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.correlation_rows.addLayout(hbox(Label("•", 12.5, color=Colors.TEXT_MUTED), text, spacing=8))
            self.correlation_rows.itemAt(self.correlation_rows.count() - 1).layout().setStretchFactor(text, 1)
        if report.get("kind") == "session" and not lines:
            empty = Label("No outages, and no loss that lined up with a Wi-Fi event.", 12.5, color=Colors.TEXT_MUTED)
            self.correlation_rows.addWidget(empty)
        self.correlation_card.setVisible(report.get("kind") == "session")

    @staticmethod
    def outage_text(outage):
        if not isinstance(outage, dict):
            return f"Outage: {outage}"
        what = (outage.get("text") or (f"{outage['name']} stopped answering" if outage.get("name") else None)
                or LAYER_LABELS.get(outage.get("layer"), outage.get("target") or "connection"))
        start = clock(outage.get("start") or outage.get("time"))
        duration = outage.get("duration_s") or outage.get("duration")
        length = f" for {duration:g} s" if isinstance(duration, (int, float)) else ""
        if outage.get("ongoing"):
            length += " (still down when the recording stopped)"
        layer = LAYER_LABELS.get(outage.get("layer"))
        return f"Outage at {start}{length}: {what}" + (f" · {layer}" if layer else "")

    def fill_findings(self, findings):
        clear_now(self.findings_layout)
        problems = [f for f in findings if f.get("severity") in ("warn", "fail", "info")]
        passed = [f for f in findings if f.get("severity") == "ok"]
        layers = list(office_quality.LAYERS)
        groups = {}
        for finding in problems:
            groups.setdefault(finding.get("layer") or "device", []).append(finding)
        for layer in sorted(groups, key=lambda l: layers.index(l) if l in layers else len(layers)):
            items = sorted(groups[layer], key=lambda f: -SEVERITY_RANK.get(f.get("severity"), 0))
            self.findings_layout.addWidget(section_label(LAYER_LABELS.get(layer, layer), Colors.TEXT_MUTED, 10))
            for finding in items:
                self.findings_layout.addWidget(FindingRow(finding))
        if passed:
            card = Card(margins=(14, 10, 14, 10), spacing=4)
            card.body.addWidget(section_label("Looks fine", Colors.TEXT_MUTED, 10))
            for finding in passed:
                summary = Label(f"<b>{html.escape(finding.get('title') or '')}</b> · "
                                f"{html.escape(finding.get('summary') or '')}", 12, color=Colors.TEXT)
                summary.setTextFormat(Qt.RichText)
                summary.setWordWrap(True)
                summary.setToolTip("\n".join(str(e) for e in finding.get("evidence") or []))
                row = hbox(StatusDot(Colors.GREEN, 7), summary, spacing=8)
                row.setStretchFactor(summary, 1)
                card.body.addLayout(row)
            self.findings_layout.addWidget(card)
        if not findings:
            self.findings_layout.addWidget(Label("No findings: too little was measured.", 12.5,
                                                 color=Colors.TEXT_MUTED))

    def fill_session_live(self, report):
        """After a recording, keep the chart and show the full event list from the report."""
        events = [e for e in report.get("events") or [] if isinstance(e, dict)]
        if self.sample_count == 0:
            # Shown from a report only (no live samples arrived): draw the recorded samples
            self.chart.reset()
            for sample in report.get("samples") or []:
                if isinstance(sample, dict):
                    self.chart.add_sample(*chart_values(sample))
        self.events_table.setRowCount(0)
        for event in reversed(events):
            self.add_event_row(event)
        self.events_table.setFixedHeight(30 + max(6, min(len(events), 14)) * 32 + 4)
        self.live_stats.set("outages", str(len(report.get("outages") or [])),
                            Colors.RED if report.get("outages") else Colors.TEXT_STRONG)
        self.live_card.setVisible(True)
        self.live_title.setText("Last recording")

    # ---------------------------------------------------------------- report actions
    def report_folder(self):
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
        default = os.path.join(documents, "network-test-tool")
        folder = (self.health_settings.value("log_folder", default, type=str) or "").strip() or default
        return os.path.expanduser(folder)

    def save_report(self):
        """Write the report files once per result; returns the paths or None (the error is shown)."""
        if not self.report:
            return None
        if self.saved:
            return self.saved
        folder = self.report_folder()
        try:
            os.makedirs(folder, exist_ok=True)
            paths = self.backend.write_report_files(self.report, folder)
        except Exception as e:
            self.save_status.setText(f"Could not save the report: {e}")
            self.save_status.set_color(Colors.RED)
            return None
        self.saved = paths or {}
        present = [self.saved[k] for k in ("html", "md", "json") if self.saved.get(k)]
        if present:
            names = [os.path.basename(present[0])] + [os.path.splitext(p)[1] for p in present[1:]]
            self.save_status.setText(f"Saved in {os.path.dirname(present[0])}: " + " · ".join(names))
            self.save_status.setToolTip("\n".join(present))
            self.save_status.set_color(Colors.TEXT_MUTED)
        return self.saved

    def open_report(self):
        paths = self.save_report()
        if paths and paths.get("html"):
            open_local_file(paths["html"])

    def log_folder(self):
        log_path = (self.report or {}).get("log_path")
        if log_path:
            return log_path if os.path.isdir(log_path) else os.path.dirname(log_path)
        if self.saved:
            first = next((p for p in self.saved.values() if p), None)
            if first:
                return os.path.dirname(first)
        return self.report_folder()

    def open_log_folder(self):
        folder = self.log_folder()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass
        open_local_file(folder)

    def copy_summary(self):
        if not self.report_text:
            return
        QApplication.clipboard().setText(self.report_text)
        self.copy_btn.setText("Copied")
        self.copy_reset.start(1500)

    # ================================================================ shared
    def busy(self):
        return bool((self.quick_thread and self.quick_thread.isRunning()) or self.session is not None
                    or (self.stop_thread and self.stop_thread.isRunning()))

    def update_availability(self):
        """Enable the actions that can run now; one measurement at a time keeps the numbers clean."""
        missing = [name for name in ("quick_test", "OfficeSession", "report_markdown", "write_report_files")
                   if self.backend is None or not hasattr(self.backend, name)]
        quick_running = bool(self.quick_thread and self.quick_thread.isRunning())
        recording = self.session is not None or bool(self.stop_thread and self.stop_thread.isRunning())
        if missing:
            self.quick_btn.setEnabled(False)
            self.record_btn.setEnabled(False)
            self.set_quick_status("The Office apps measurements are not available in this build.", Colors.RED)
            return
        if not quick_running:
            self.quick_btn.setEnabled(not recording)
            self.quick_btn.setToolTip("Stop the recording first" if recording else "")
        if not recording:
            self.record_btn.setEnabled(not quick_running)
            self.record_btn.setToolTip("Wait for the quick check to finish" if quick_running else "")
        self.tenant.setEnabled(not quick_running and not recording)

    def update_running(self):
        self.set_running(self.busy())

    def session_logs(self):
        if self.report_text:
            return {"Office apps check": self.report_text}
        return {}

    def cleanup(self):
        self.record_timer.stop()
        for obj in (self.quick_thread, self.stop_thread, self.connection_thread, self.bridge):
            disconnect_signals(obj)   # no late results into a page that is being torn down
        if self.quick_thread is not None and self.quick_thread.isRunning():
            self.quick_thread.stop()
        session, self.session = self.session, None
        save_thread = None
        if session is not None:
            # Keep what was recorded instead of losing it on exit, also when "Stop recording" is still
            # running (its signals are disconnected, so it would not write anything; stop() returns the same
            # report on repeated calls). Stopping joins the probes and writing may hit a slow folder, so it
            # runs off the GUI thread; finish_thread bounds the wait.
            save_thread = SaveOnExitThread(session, self.backend, self.report_folder(), self)
            save_thread.start()
        deadline = time.monotonic() + CLEANUP_WAIT_MS / 1000.0   # one shared budget for all waits
        for thread in (self.quick_thread, self.stop_thread, self.connection_thread, save_thread):
            if not finish_thread(thread, max(0, int((deadline - time.monotonic()) * 1000))):
                logging.error("Office apps shutdown exceeded its wait budget; a worker is still running")
