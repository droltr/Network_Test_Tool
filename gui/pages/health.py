"""Network health: configuration scan (VPN leftovers, dead DNS, proxy, MTU) and a connection monitor."""
import os
from datetime import datetime

from PyQt5.QtCore import Qt, QThread, QSettings, QStandardPaths, QRectF, QUrl, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QDesktopServices
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QButtonGroup, QComboBox,
                             QScrollArea, QFrame, QTableWidgetItem, QSizePolicy, QMessageBox,
                             QDialog, QPlainTextEdit, QApplication)
from PyQt5.QtCore import QTimer

from gui.file_dialogs import get_existing_directory
from gui.pages.base import Page
from gui.recent import recent_store
from gui.styles.modern_theme import Colors, mono_font, ui_font
from gui.widgets.common import (Card, Label, LineInput, EmptyPane, StatusDot, PulseDot, section_label, button,
                                link_button, hbox, make_table, clear_layout, set_prop, cell_widget)
from network import health
from network.monitor import ConnectionMonitor, SessionRecorder, session_markdown, write_session_files
from network.system_tools import SystemTools

STATUS_COLORS = {"ok": Colors.GREEN, "info": Colors.BLUE, "warn": Colors.YELLOW, "fail": Colors.RED}
STATUS_LABELS = {"ok": "OK", "info": "Info", "warn": "Check", "fail": "Problem"}
TARGET_TITLES = {"gateway": "Gateway", "dns": "DNS", "internet": "Internet", "custom": "Custom host"}
ACTION_LABELS = {"flush_dns": "Flush DNS", "renew_ip": "Renew IP"}


class ScanThread(QThread):
    progress = pyqtSignal(str, object)
    done = pyqtSignal(list)

    def run(self):
        self.done.emit(health.run_scan(self.progress.emit))


class MonitorThread(QThread):
    event = pyqtSignal(str, object)

    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        monitor.callback = self.event.emit

    def run(self):
        self.monitor.run()

    def stop(self):
        self.monitor.stop()


class ActionThread(QThread):
    done = pyqtSignal(str, bool, str)

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action

    def run(self):
        tools = SystemTools()
        ok, output = tools.flush_dns() if self.action == "flush_dns" else tools.renew_ip()
        self.done.emit(self.action, ok, output)


class AvailabilityTimeline(QWidget):
    """One row per target: a thin cell per probe, green when it answered, red when not."""

    def __init__(self, capacity=600, parent=None):
        super().__init__(parent)
        self.capacity = capacity
        self.rows = {}
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def reset(self):
        self.rows = {}
        self.update()

    def add(self, results):
        for target, result in results.items():
            row = self.rows.setdefault(target, [])
            row.append(result["ok"])
            del row[:-self.capacity]
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        label_w = 86
        targets = list(self.rows)
        if not targets:
            p.setPen(QColor(Colors.TEXT_FAINT))
            p.setFont(ui_font(12))
            p.drawText(self.rect(), Qt.AlignCenter, "Start the monitor to see availability over time")
            return
        row_h = min(26.0, (self.height() - 18) / len(targets))
        width = self.width() - label_w
        cell = width / self.capacity
        for i, target in enumerate(targets):
            y = i * row_h
            p.setPen(QColor(Colors.TEXT_MUTED))
            p.setFont(ui_font(11.5))
            p.drawText(QRectF(0, y, label_w - 8, row_h - 6), Qt.AlignVCenter | Qt.AlignLeft,
                       TARGET_TITLES.get(target, target))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(Colors.BG_SUNKEN))
            p.drawRect(QRectF(label_w, y + 3, width, row_h - 10))
            values = self.rows[target]
            offset = self.capacity - len(values)
            for j, ok in enumerate(values):
                p.setBrush(QColor(Colors.GREEN if ok else Colors.RED))
                p.drawRect(QRectF(label_w + (offset + j) * cell, y + 3, max(cell, 1.0), row_h - 10))
        p.setPen(QColor(Colors.TEXT_FAINT))
        p.setFont(mono_font(10.5))
        p.drawText(QRectF(label_w, self.height() - 16, width, 14), Qt.AlignLeft, f"−{self.capacity} probes")
        p.drawText(QRectF(label_w, self.height() - 16, width, 14), Qt.AlignRight, "now")


class TargetCard(Card):
    def __init__(self, title):
        super().__init__(margins=(14, 10, 14, 10), spacing=3)
        self.dot = StatusDot(Colors.TEXT_FAINT, 8)
        self.title = Label(title, 12.5, 600, Colors.TEXT_STRONG)
        self.address = Label("", 11, color=Colors.TEXT_MUTED, mono=True)
        self.body.addLayout(hbox(self.dot, self.title, "stretch", self.address, spacing=6))
        self.value = Label("—", 18, 400, Colors.TEXT_FAINT, mono=True)
        self.detail = Label("", 11.5, color=Colors.TEXT_MUTED)
        self.body.addWidget(self.value)
        self.body.addWidget(self.detail)

    def update_result(self, result, stat, outages):
        self.dot.set_state(Colors.GREEN if result["ok"] else Colors.RED)
        self.address.setText(result.get("address", ""))
        if result["ok"]:
            self.value.setText(f"{result['ms']:.1f} ms" if result["ms"] is not None else "ok")
            self.value.set_color(Colors.TEXT_STRONG)
        else:
            self.value.setText("no reply")
            self.value.set_color(Colors.RED)
        loss = 100 * (stat["sent"] - stat["ok"]) / stat["sent"] if stat["sent"] else 0
        self.detail.setText(f"{loss:.1f}% lost · {outages} outage{'s' if outages != 1 else ''}")


class ReportDialog(QDialog):
    """Shows a session report with copy and open-file actions."""

    def __init__(self, text, path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Monitor session report")
        self.resize(900, 640)
        self.setStyleSheet(f"QDialog {{ background: {Colors.BG}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setFont(mono_font(11.5))
        view.setStyleSheet(f"QPlainTextEdit {{ border: 1px solid {Colors.BORDER}; border-radius: 8px; }}")
        layout.addWidget(view, 1)
        copy = button("Copy report", "primary", 32)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
        buttons = [copy]
        if path and os.path.exists(path):
            open_file = button("Open file", "secondary", 32)
            open_file.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
            open_folder = button("Open folder", "secondary", 32)
            open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path))))
            buttons += [open_file, open_folder]
        close = button("Close", "secondary", 32)
        close.clicked.connect(self.accept)
        path_label = Label(path or "", 11, color=Colors.TEXT_MUTED, mono=True)
        layout.addLayout(hbox(*buttons, 10, path_label, "stretch", close, spacing=8))


class HealthPage(Page):
    def __init__(self):
        super().__init__("Network health")
        self.settings = QSettings("NetworkTools", "Health")
        self.scan_thread = None
        self.monitor_thread = None
        self.monitor = None
        self.action_thread = None
        self.scan_results = []
        self.recorder = None
        self.session_owns_monitor = False
        self.last_session_text = ""
        self.record_timer = QTimer(self)
        self.record_timer.timeout.connect(self.update_recording_status)

        self.tab_group = QButtonGroup(self)
        for index, text in enumerate(("Health scan", "Connection monitor")):
            tab = button(text, "tab", 47)
            tab.setCheckable(True)
            self.tab_group.addButton(tab, index)
            self.header.tabs.addWidget(tab)
        self.tab_group.buttonClicked[int].connect(self.show_tab)
        self.header.subtitle.setVisible(False)
        self.body.setContentsMargins(20, 14, 20, 16)
        self.stack = QStackedWidget()
        self.body.addWidget(self.stack, 1)
        self.stack.addWidget(self.build_scan())
        self.stack.addWidget(self.build_monitor())
        self.tab_group.button(0).setChecked(True)

    def show_tab(self, index):
        self.stack.setCurrentIndex(index)
        # The scan summary belongs to the scan tab only
        self.header.subtitle.setVisible(index == 0 and bool(self.scan_results))

    # ================================================================ scan
    def build_scan(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        bar = Card(margins=(14, 12, 14, 12))
        intro = Label("Looks for problems that ping tests miss: routes or DNS servers left by a removed VPN, "
                      "virtual adapters, proxies, MTU black holes, broken IPv6.", 12.5, color=Colors.TEXT)
        intro.setWordWrap(True)
        self.scan_btn = button("Run scan", "primary", 34, width=150)
        self.scan_btn.clicked.connect(self.start_scan)
        scan_row = hbox(intro, 12, self.scan_btn, spacing=8)
        scan_row.setStretchFactor(intro, 1)
        bar.body.addLayout(scan_row)
        layout.addWidget(bar)

        self.scan_views = QStackedWidget()
        self.scan_empty = EmptyPane("No scan yet", "About 5–15 seconds. Nothing is changed on your system.")
        self.scan_views.addWidget(self.scan_empty)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        self.scan_rows = QVBoxLayout(holder)
        self.scan_rows.setContentsMargins(0, 0, 0, 0)
        self.scan_rows.setSpacing(10)
        scroll.setWidget(holder)
        self.scan_views.addWidget(scroll)
        self.scan_list = scroll
        layout.addWidget(self.scan_views, 1)
        return page

    def start_scan(self):
        if self.scan_thread and self.scan_thread.isRunning():
            return
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning…")
        self.set_running(True)
        clear_layout(self.scan_rows)
        self.scan_results = []
        self.pending = {}
        for check_id, title, _func in health.CHECKS:
            row = self.result_row({"title": title, "status": "pending", "summary": "waiting", "details": [],
                                   "fix": "", "action": None})
            self.pending[check_id] = row
            self.scan_rows.addWidget(row)
        self.scan_rows.addStretch(1)
        self.scan_views.setCurrentWidget(self.scan_list)
        self.scan_thread = ScanThread(self)
        self.scan_thread.progress.connect(self.on_scan_progress)
        self.scan_thread.done.connect(self.on_scan_done)
        self.scan_thread.finished.connect(self.update_running)
        self.scan_thread.start()

    def on_scan_progress(self, check_id, result):
        row = self.pending.get(check_id)
        if not row:
            return
        index = self.scan_rows.indexOf(row)
        if result is None:
            row.summary.setText("checking…")
            row.summary.set_color(Colors.BLUE)
            return
        new_row = self.result_row(result)
        self.scan_rows.insertWidget(index, new_row)
        row.deleteLater()
        self.pending[check_id] = new_row

    def on_scan_done(self, results):
        self.scan_results = results
        for check_id, row in list(self.pending.items()):
            if not any(r["id"] == check_id for r in results):
                row.deleteLater()   # check does not apply to this OS
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Run scan again")
        problems = [r for r in results if r["status"] in ("warn", "fail")]
        self.header.set_subtitle(f"Completed {datetime.now():%H:%M} · "
                                 + (f"{len(problems)} item(s) to check" if problems else "no problems found"))
        self.header.subtitle.setVisible(True)

    def result_row(self, result):
        card = Card(margins=(14, 10, 14, 10), spacing=4)
        status = result["status"]
        color = STATUS_COLORS.get(status, Colors.TEXT_FAINT)
        if status == "pending":
            dot = StatusDot(Colors.TEXT_FAINT, 8, "dashed")
            badge = Label("", 11, 600, Colors.TEXT_MUTED)
        else:
            dot = StatusDot(color, 8)
            badge = Label(STATUS_LABELS[status].upper(), 11, 600, color)
        title = Label(result["title"], 13, 600, Colors.TEXT_STRONG)
        title.setFixedWidth(210)
        summary = Label(result["summary"], 12.5, color=Colors.TEXT)
        summary.setWordWrap(True)
        top = hbox(dot, title, summary, spacing=10)
        top.setStretchFactor(summary, 1)
        if result.get("action"):
            action = button(ACTION_LABELS[result["action"]], "ghost", 28)
            action.clicked.connect(lambda _=False, a=result["action"], b=action: self.run_action(a, b))
            top.addWidget(action)
        badge.setFixedWidth(70)
        badge.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(badge)
        card.body.addLayout(top)
        if status in ("warn", "fail") and result["status"] != "pending":
            card.setStyleSheet(f"QFrame[card=\"card\"] {{ border-color: {color}; }}")
        for line in result.get("details", [])[:8]:
            detail = Label(line, 11.5, color=Colors.TEXT_MUTED, mono=True)
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail.setContentsMargins(242, 0, 0, 0)
            card.body.addWidget(detail)
        if result.get("fix"):
            fix = Label("Fix: " + result["fix"], 12, color=Colors.YELLOW if status != "ok" else Colors.TEXT_MUTED)
            fix.setWordWrap(True)
            fix.setContentsMargins(242, 2, 0, 0)
            card.body.addWidget(fix)
        card.summary = summary
        return card

    def run_action(self, action, btn):
        if self.action_thread and self.action_thread.isRunning():
            return
        btn.setEnabled(False)
        btn.setText("Working…")
        self.action_thread = ActionThread(action, self)
        self.action_thread.done.connect(lambda a, ok, out, b=btn: self.on_action_done(a, ok, out, b))
        self.action_thread.start()

    def on_action_done(self, action, ok, output, btn):
        try:
            btn.setEnabled(True)
            btn.setText(ACTION_LABELS[action])
        except RuntimeError:
            pass   # the row was rebuilt meanwhile
        if ok:
            QMessageBox.information(self, ACTION_LABELS[action], f"Done.\n\n{output.strip()}\n\nRun the scan again "
                                                                  "to check the result.")
        else:
            QMessageBox.warning(self, ACTION_LABELS[action], f"Failed.\n\n{output.strip()}")

    # ================================================================ monitor
    def build_monitor(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        control = Card(margins=(14, 12, 14, 12), spacing=10)
        self.interval_combo = QComboBox()
        self.interval_combo.addItems(["1 s", "2 s", "5 s", "10 s"])
        self.threshold_combo = QComboBox()
        self.threshold_combo.addItems(["1 failed probe", "2 failed probes", "3 failed probes"])
        self.threshold_combo.setCurrentIndex(1)
        for combo, width in ((self.interval_combo, 80), (self.threshold_combo, 150)):
            combo.setFont(ui_font(12))
            combo.setFixedSize(width, 30)
        self.extra_host = LineInput("optional, e.g. a game or work server", height=30)
        self.extra_host.setFixedWidth(260)
        self.monitor_btn = button("Start monitor", "primary", 32)
        self.monitor_btn.clicked.connect(self.toggle_monitor)
        control.body.addLayout(hbox(Label("Probe every", 12, color=Colors.TEXT_MUTED), self.interval_combo, 10,
                                    Label("Outage after", 12, color=Colors.TEXT_MUTED), self.threshold_combo, 10,
                                    Label("Extra host", 12, color=Colors.TEXT_MUTED), self.extra_host, "stretch",
                                    self.monitor_btn, spacing=6))
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
        self.log_folder = LineInput("Log folder", height=30)
        self.log_folder.setText(self.settings.value("log_folder", os.path.join(documents, "network-test-tool"),
                                                    type=str))
        browse = button("Browse…", "secondary", 30)
        browse.clicked.connect(self.choose_log_folder)
        self.open_log = link_button("Open log folder")
        self.open_log.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.expanduser(self.log_folder.text()))))
        control.body.addLayout(hbox(Label("Save CSV log to", 12, color=Colors.TEXT_MUTED), self.log_folder, browse,
                                    self.open_log, spacing=6))
        self.monitor_pulse = PulseDot(Colors.GREEN, 8)
        self.monitor_pulse.setVisible(False)
        self.monitor_status = Label("Stopped. The monitor keeps running when you switch pages.", 12,
                                    color=Colors.TEXT_MUTED)
        control.body.addLayout(hbox(self.monitor_pulse, self.monitor_status, "stretch", spacing=6))
        layout.addWidget(control)

        record = Card(margins=(14, 10, 14, 10))
        self.session_label = LineInput("Session label (optional), e.g. \"video call\" or \"evening drops\"",
                                       height=30, mono=False)
        self.session_label.setFixedWidth(330)
        self.record_dot = PulseDot(Colors.RED, 9)
        self.record_dot.setVisible(False)
        self.record_status = Label("Record a session to get a report for just that time window. The monitor keeps "
                                   "logging either way.", 12, color=Colors.TEXT_MUTED)
        self.record_btn = button("Start recording", "secondary", 32)
        self.record_btn.clicked.connect(self.toggle_recording)
        record.body.addLayout(hbox(section_label("Session"), 6, self.session_label, 8, self.record_dot,
                                   self.record_status, "stretch", self.record_btn, spacing=6))
        layout.addWidget(record)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.target_cards = {}
        for key in ("gateway", "dns", "internet", "custom"):
            card = TargetCard(TARGET_TITLES[key])
            cards.addWidget(card, 1)
            self.target_cards[key] = card
        layout.addLayout(cards)

        timeline_card = Card(margins=(16, 12, 16, 10))
        timeline_card.body.addWidget(section_label("Availability"))
        self.timeline = AvailabilityTimeline()
        timeline_card.body.addWidget(self.timeline, 1)
        layout.addWidget(timeline_card, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.event_table = make_table(["Time", "Event", "Layer", "Duration"], stretch_column=1)
        for column, width in ((0, 150), (2, 130), (3, 80)):
            self.event_table.horizontalHeader().resizeSection(column, width)
        self.event_table.setFixedHeight(190)
        bottom.addWidget(self.event_table, 3)
        self.session_table = make_table(["Session", "Duration", "Verdict", ""], stretch_column=2)
        for column, width in ((0, 150), (1, 80), (3, 70)):
            self.session_table.horizontalHeader().resizeSection(column, width)
        self.session_table.setFixedHeight(190)
        bottom.addWidget(self.session_table, 2)
        layout.addLayout(bottom)
        self.load_sessions()
        self.target_cards["custom"].setVisible(False)
        return page

    def choose_log_folder(self):
        folder = get_existing_directory(self, "Choose log folder", self.log_folder.text())
        if folder:
            self.log_folder.setText(folder)
            self.settings.setValue("log_folder", folder)

    def toggle_monitor(self):
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_btn.setEnabled(False)
            self.monitor_btn.setText("Stopping…")
            self.monitor_thread.stop()
            return
        folder = os.path.expanduser(self.log_folder.text().strip())
        self.settings.setValue("log_folder", folder)
        self.monitor = ConnectionMonitor(
            interval=float(self.interval_combo.currentText().split()[0]),
            fail_threshold=int(self.threshold_combo.currentText().split()[0]),
            extra_host=self.extra_host.text(), log_dir=folder or None)
        self.timeline.reset()
        self.event_table.setRowCount(0)
        self.target_cards["custom"].setVisible(bool(self.extra_host.text().strip()))
        self.monitor_thread = MonitorThread(self.monitor, self)
        self.monitor_thread.event.connect(self.on_monitor_event)
        self.monitor_thread.finished.connect(self.on_monitor_stopped)
        self.monitor_btn.setText("Stop monitor")
        set_prop(self.monitor_btn, "variant", "stop")
        for widget in (self.interval_combo, self.threshold_combo, self.extra_host, self.log_folder):
            widget.setEnabled(False)
        self.monitor_pulse.setVisible(True)
        self.update_running()
        self.monitor_thread.start()

    def on_monitor_event(self, kind, data):
        if kind == "sample":
            results = data["results"]
            if self.recorder:
                self.recorder.add_sample(data["time"], results)
            self.timeline.add(results)
            outages = {}
            for event in self.monitor.events:
                if event["type"] == "outage":
                    outages[event["target"]] = outages.get(event["target"], 0) + 1
            for target, result in results.items():
                stat = self.monitor.stats.get(target, {"sent": 0, "ok": 0})
                self.target_cards[target].update_result(result, stat, outages.get(target, 0))
            elapsed = int((datetime.now() - self.monitor.started).total_seconds())
            log = f" · log {os.path.basename(self.monitor.csv_path)}" if self.monitor.csv_path else ""
            self.monitor_status.setText(f"Running for {elapsed // 3600:02d}:{elapsed // 60 % 60:02d}:"
                                        f"{elapsed % 60:02d} · {self.monitor.samples} rounds{log}")
            self.monitor_status.set_color(Colors.GREEN)
        elif kind == "outage":
            self.add_event(data["start"], f"{TARGET_TITLES.get(data['target'], data['target'])} stopped answering",
                           data["layer"], "ongoing", Colors.RED)
        elif kind == "restore":
            self.add_event(data["end"], f"{TARGET_TITLES.get(data['target'], data['target'])} is back",
                           data["layer"], f"{data['duration']:.1f} s", Colors.GREEN)
        elif kind == "change":
            if self.recorder:
                self.recorder.add_change(data)
            self.add_event(data["time"], data["message"], "Interface", "", Colors.YELLOW)
        elif kind == "error":
            self.monitor_status.setText(str(data))
            self.monitor_status.set_color(Colors.RED)

    def add_event(self, when, text, layer, duration, color):
        self.event_table.insertRow(0)
        values = (when.replace("T", " "), text, layer, duration)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setFont(mono_font(12) if column in (0, 3) else ui_font(12.5))
            item.setForeground(QColor(color if column == 1 else Colors.TEXT))
            self.event_table.setItem(0, column, item)

    def on_monitor_stopped(self):
        if self.recorder:
            self.finish_recording()
        self.monitor_btn.setEnabled(True)
        self.monitor_btn.setText("Start monitor")
        set_prop(self.monitor_btn, "variant", "primary")
        for widget in (self.interval_combo, self.threshold_combo, self.extra_host, self.log_folder):
            widget.setEnabled(True)
        self.monitor_pulse.setVisible(False)
        if self.monitor:
            outages = sum(1 for e in self.monitor.events if e["type"] == "outage")
            self.monitor_status.setText(f"Stopped after {self.monitor.samples} rounds · {outages} outage(s)"
                                        + (f" · log {os.path.basename(self.monitor.csv_path)}"
                                           if self.monitor.csv_path else ""))
            self.monitor_status.set_color(Colors.TEXT_MUTED)
        self.update_running()

    # ================================================================ sessions
    def toggle_recording(self):
        if self.recorder:
            self.finish_recording()
            return
        monitor_running = bool(self.monitor_thread and self.monitor_thread.isRunning())
        self.session_owns_monitor = not monitor_running
        if not monitor_running:
            self.toggle_monitor()
        self.recorder = SessionRecorder(self.session_label.text(), fail_threshold=self.monitor.fail_threshold,
                                        interval=self.monitor.interval)
        self.record_btn.setText("Stop recording")
        set_prop(self.record_btn, "variant", "stop")
        self.session_label.setEnabled(False)
        self.record_dot.setVisible(True)
        self.record_timer.start(1000)
        self.update_recording_status()
        self.update_running()

    def update_recording_status(self):
        if not self.recorder:
            return
        elapsed = int((datetime.now() - self.recorder.started).total_seconds())
        rounds = len(self.recorder.samples)
        internet = [r["internet"]["ok"] for _w, r in self.recorder.samples if "internet" in r]
        loss = 100 * internet.count(False) / len(internet) if internet else 0
        self.record_status.setText(f"Recording {elapsed // 3600:02d}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d} · "
                                   f"{rounds} rounds · {self.recorder.outage_count} outage(s) · {loss:.1f}% loss")
        self.record_status.set_color(Colors.TEXT_STRONG)

    def finish_recording(self):
        recorder, self.recorder = self.recorder, None
        self.record_timer.stop()
        report = recorder.stop()
        folder = os.path.expanduser(self.log_folder.text().strip())
        path = None
        try:
            path = write_session_files(recorder, report, folder)
        except OSError as e:
            self.record_status.setText(f"Could not save the report: {e}")
        text = session_markdown(report)
        self.last_session_text = text
        summary = recorder.summary_line(report)
        recent_store().add('monitor', report['label'] or "Connection monitor", summary,
                           {"report": report, "file": path})
        self.record_btn.setText("Start recording")
        set_prop(self.record_btn, "variant", "secondary")
        self.session_label.setEnabled(True)
        self.record_dot.setVisible(False)
        self.record_status.setText(f"Last session: {report['verdict']} · {summary}")
        self.record_status.set_color(Colors.RED if report['outages'] else Colors.GREEN)
        self.load_sessions()
        if self.session_owns_monitor and self.monitor_thread and self.monitor_thread.isRunning():
            self.toggle_monitor()
        self.session_owns_monitor = False
        self.update_running()
        ReportDialog(text, path, self).show()

    def load_sessions(self):
        entries = recent_store().items('monitor')[:20]
        self.session_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            report = entry['data'].get('report', {})
            when = datetime.fromisoformat(report.get('started', entry['time']))
            label = f"{when:%d.%m %H:%M}" + (f" · {report['label']}" if report.get('label') else "")
            duration = report.get('duration_s', 0)
            verdict_color = Colors.RED if report.get('outages') else Colors.GREEN
            for column, (text, color, font) in enumerate((
                    (label, Colors.TEXT_STRONG, ui_font(12.5)),
                    (f"{duration // 60}m {duration % 60:02d}s", Colors.TEXT, mono_font(12)),
                    (report.get('verdict', ''), verdict_color, ui_font(12.5)))):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(color))
                item.setFont(font)
                self.session_table.setItem(row, column, item)
            view = link_button("Report")
            view.clicked.connect(lambda _=False, e=entry['id']: self.show_session(e))
            self.session_table.setCellWidget(row, 3, cell_widget(view))

    def show_session(self, entry_id):
        entry = recent_store().get(entry_id)
        if entry:
            data = entry['data']
            ReportDialog(session_markdown(data['report']), data.get('file'), self).show()

    def handle_request(self, payload):
        if payload.get('open'):
            self.tab_group.button(1).setChecked(True)
            self.show_tab(1)
            self.show_session(payload['open'])

    # ================================================================ shared
    def update_running(self):
        scanning = bool(self.scan_thread and self.scan_thread.isRunning())
        monitoring = bool(self.monitor_thread and self.monitor_thread.isRunning())
        self.set_running(scanning or monitoring or bool(self.recorder))

    def session_logs(self):
        logs = {}
        if self.scan_results:
            logs["Network health scan"] = health.scan_as_text(self.scan_results)
        if self.monitor and self.monitor.samples:
            logs["Connection monitor"] = self.monitor.summary_text()
        if self.recorder:
            logs["Monitor session (in progress)"] = session_markdown(self.recorder.report())
        elif self.last_session_text:
            logs["Last monitor session report"] = self.last_session_text
        return logs

    def cleanup(self):
        if self.recorder:
            # Save what was recorded so far instead of losing it on exit
            recorder, self.recorder = self.recorder, None
            report = recorder.stop()
            try:
                path = write_session_files(recorder, report, os.path.expanduser(self.log_folder.text().strip()))
                recent_store().add('monitor', report['label'] or "Connection monitor",
                                   recorder.summary_line(report), {"report": report, "file": path})
            except OSError:
                pass
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.monitor_thread.wait(8000)
        for thread in (self.scan_thread, self.action_thread):
            if thread and thread.isRunning():
                thread.wait(20000)
