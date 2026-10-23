"""Troubleshooter: step checklist driven by structured events, colourised raw log, suggestions."""
from datetime import datetime

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QWidget, QFrame, QHBoxLayout, QVBoxLayout, QStackedWidget

from gui.pages.base import Page, finish_thread
from gui.styles.modern_theme import Colors, mono_font, ui_font
from gui.widgets.common import (Card, Label, LogPane, EmptyPane, StatusDot, PulseDot, section_label, button,
                                hbox, clear_layout, set_prop)
from network.system_tools import SystemTools
from network.troubleshooter import Troubleshooter

STEP_TITLES = {
    'info': "Device and network info",
    'gateway': "Ping gateway",
    'dns': "Ping primary DNS",
    'external': "Ping external host",
    'trace': "Traceroute 1.1.1.1",
}
STEP_GROUP = {'info': 1, 'gateway': 2, 'dns': 2, 'external': 2, 'trace': 3}
GROUP_NAMES = {1: "device information", 2: "connectivity tests", 3: "traceroute"}


class TroubleshootThread(QThread):
    progress_update = pyqtSignal(str)
    step_event = pyqtSignal(str, str, str)
    test_complete = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.troubleshooter = Troubleshooter()

    def run(self):
        log = self.troubleshooter.run_troubleshooting(progress_callback=self.progress_update.emit,
                                                      event_callback=self.step_event.emit)
        self.test_complete.emit(log)

    def stop(self):
        """Cancel the run: ends the current ping and terminates the traceroute process."""
        self.troubleshooter.stop()


class FlushThread(QThread):
    done = pyqtSignal(bool, str)

    def run(self):
        self.done.emit(*SystemTools().flush_dns())


class StepRow(QFrame):
    """Checklist row: state icon, title, right-aligned value."""

    def __init__(self, step, first=False, parent=None):
        super().__init__(parent)
        self.setProperty("row", "true")
        if first:
            self.setStyleSheet("QFrame[row=\"true\"] { border-top: none; }")
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)
        self.dot = StatusDot(Colors.TEXT_FAINT, 7, "dashed")
        self.pulse = PulseDot(Colors.BLUE, 8, "ring")
        self.pulse.setVisible(False)
        self.title = Label(STEP_TITLES[step], 12.5, color=Colors.TEXT)
        self.value = Label("", 12, color=Colors.TEXT_MUTED)
        layout.addWidget(self.dot)
        layout.addWidget(self.pulse)
        layout.addWidget(self.title, 1)
        layout.addWidget(self.value)
        self.set_state("pending")

    def set_state(self, state, value=""):
        self.state = state
        running = state == "running"
        self.pulse.setVisible(running)
        self.dot.setVisible(not running)
        mono = any(ch.isdigit() for ch in value) and value.endswith("ms")
        if state == "pending":
            self.dot.set_state(Colors.TEXT_FAINT, "dashed")
            self.title.set_color(Colors.TEXT_MUTED)
            self.value.setText("pending")
            self.value.set_color(Colors.TEXT_MUTED)
        elif running:
            self.title.set_color(Colors.TEXT_STRONG)
            self.value.setText("running")
            self.value.set_color(Colors.BLUE)
        else:
            color = {'done': Colors.GREEN, 'failed': Colors.RED, 'partial': Colors.YELLOW}.get(state, Colors.TEXT)
            self.dot.set_state(color, "filled")
            self.title.set_color(Colors.TEXT_STRONG if state == 'failed' else Colors.TEXT)
            self.value.setText(value or state)
            self.value.set_color({'done': Colors.TEXT_MUTED if not mono else Colors.TEXT_STRONG,
                                  'failed': Colors.RED, 'partial': Colors.YELLOW}.get(state, Colors.TEXT_MUTED))
        self.value.setFont(mono_font(11.5) if mono else ui_font(12, 600 if state == 'failed' else 400))
        set_prop(self, "state", state)


class TroubleshooterPage(Page):
    def __init__(self):
        super().__init__("Troubleshooter", "Device checks, connectivity tests and a traceroute")
        self.thread = None
        self.flush_thread = None
        self.lines = []

        self.export_btn = button("Export log", "secondary")
        self.export_btn.clicked.connect(self.export_log)
        self.again_btn = button("Run again", "primary")
        self.again_btn.clicked.connect(self.start_troubleshooting)
        self.running_btn = button("Running…", "primary")
        self.running_btn.setEnabled(False)

        self.bar = Card(margins=(12, 12, 12, 12))
        self.start_btn = button("Start troubleshooting", "primary", 34)
        self.start_btn.clicked.connect(self.start_troubleshooting)
        self.bar.body.addLayout(hbox("stretch", self.start_btn))
        self.body.addWidget(self.bar)

        self.views = QStackedWidget()
        self.body.addWidget(self.views, 1)
        self.views.addWidget(EmptyPane("Three checks, about 30 seconds",
                                       "1. Device and network information · 2. Ping gateway, DNS and 8.8.8.8 · "
                                       "3. Traceroute to 1.1.1.1"))

        run_view = QWidget()
        layout = QHBoxLayout(run_view)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)
        self.checklist = Card(margins=(0, 0, 0, 0), spacing=0)
        self.rows = {}
        for index, step in enumerate(Troubleshooter.STEPS):
            row = StepRow(step, first=index == 0)
            self.checklist.body.addWidget(row)
            self.rows[step] = row
        left.addWidget(self.checklist)
        self.suggest_label = section_label("Suggestions")
        self.suggest_label.setContentsMargins(0, 8, 0, 0)
        left.addWidget(self.suggest_label)
        self.suggestions = QVBoxLayout()
        self.suggestions.setSpacing(10)
        left.addLayout(self.suggestions)
        left.addStretch(1)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setFixedWidth(380)
        layout.addWidget(left_widget)
        self.log = LogPane("Log")
        layout.addWidget(self.log, 1)
        self.views.addWidget(run_view)
        self.run_view = run_view

    def handle_request(self, payload):
        if payload.get('action') == 'run':
            self.start_troubleshooting()

    def start_troubleshooting(self):
        if self.running:
            return
        self.set_running(True)
        self.lines = []
        self.log.clear()
        for row in self.rows.values():
            row.set_state("pending")
        clear_layout(self.suggestions)
        self.suggest_label.setVisible(False)
        self.bar.setVisible(False)
        self.header.set_subtitle("Step 1 of 3 · device information")
        self.header.set_actions(self.running_btn)
        self.views.setCurrentWidget(self.run_view)

        self.thread = TroubleshootThread(self)
        self.thread.progress_update.connect(self.update_log)
        self.thread.step_event.connect(self.on_step)
        self.thread.test_complete.connect(self.on_complete)
        self.thread.start()

    def update_log(self, message):
        # Prevent duplicate consecutive messages
        if self.lines and message.strip() == self.lines[-1].strip():
            return
        self.lines.append(message)
        self.log.append_line(message.rstrip("\n"))

    def on_step(self, step, status, value):
        self.rows[step].set_state(status, value)
        if status == "running":
            group = STEP_GROUP[step]
            self.header.set_subtitle(f"Step {group} of 3 · {GROUP_NAMES[group]}")

    def on_complete(self, _log):
        self.set_running(False)
        failed = [s for s, row in self.rows.items() if row.state in ('failed', 'partial')]
        hard_failed = [s for s, row in self.rows.items() if row.state == 'failed']
        when = datetime.now().strftime("%H:%M")
        if hard_failed:
            self.header.set_subtitle(f"Completed {when} · {len(hard_failed)} check"
                                     f"{'s' if len(hard_failed) != 1 else ''} failed")
        else:
            self.header.set_subtitle(f"Completed {when} · all checks passed")
        self.header.set_actions(self.export_btn, self.again_btn)
        self.build_suggestions(failed)

    def build_suggestions(self, failed_steps):
        """Group each [SUGGESTION] line under the failing check that printed it."""
        clear_layout(self.suggestions)
        groups, current = [], None
        for line in self.lines:
            stripped = line.strip()
            if stripped.startswith("Pinging gateway") or stripped.startswith("Gateway not found"):
                current = 'gateway'
            elif stripped.startswith("Pinging primary DNS") or stripped.startswith("DNS server not found"):
                current = 'dns'
            elif stripped.startswith("Pinging external host"):
                current = 'external'
            if "[SUGGESTION]" in stripped:
                text = stripped.split("[SUGGESTION]", 1)[1].strip()
                if groups and groups[-1][0] == current:
                    groups[-1][1].append(text)
                else:
                    groups.append((current, [text]))
        if 'trace' in failed_steps:
            groups.append(('trace', ["The traceroute did not reach 1.1.1.1. Open Diagnose host to trace a "
                                     "different target."]))

        for step, texts in groups:
            card = Card(margins=(14, 12, 14, 12), spacing=6)
            for text in texts:
                label = Label(text, 12.5, color=Colors.TEXT)
                label.setWordWrap(True)
                card.body.addWidget(label)
            action = None
            if step == 'dns':
                action = button("Flush DNS", "ghost", 28)
                action.clicked.connect(lambda _=False, b=action: self.flush_dns(b))
            elif step in ('gateway', 'external', 'trace'):
                action = button("Open Diagnose host", "ghost", 28)
                target = "8.8.8.8" if step != 'trace' else "1.1.1.1"
                action.clicked.connect(lambda _=False, t=target: self.navigate.emit('diagnose', {'target': t}))
            if action:
                card.body.addLayout(hbox(action, "stretch"))
            self.suggestions.addWidget(card)
        self.suggest_label.setVisible(bool(groups))

    def flush_dns(self, btn):
        btn.setEnabled(False)
        btn.setText("Flushing…")
        self.flush_thread = FlushThread(self)
        self.flush_thread.done.connect(lambda ok, out: (btn.setText("DNS flushed" if ok else "Flush failed"),
                                                        self.update_log(out.strip() or "DNS cache flushed.")))
        self.flush_thread.start()

    def export_log(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.save_text("Save Log File", f"troubleshoot_log_{timestamp}.txt", self.log.plain_text() + "\n")

    def cleanup(self):
        if self.thread and self.thread.isRunning():
            self.thread.stop()
        for thread in (self.thread, self.flush_thread):
            finish_thread(thread, 15000)
