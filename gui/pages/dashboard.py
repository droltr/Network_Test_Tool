"""Dashboard: connection path, issues, gateway latency, last speed test, adapters, quick actions."""
import logging
import statistics
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QGridLayout, QHBoxLayout, QVBoxLayout, QWidget, QFrame, QComboBox,
                             QMessageBox, QFileDialog, QApplication)

from gui.pages.base import Page
from gui.recent import recent_store, KIND_TITLES
from gui.styles.modern_theme import Colors, ui_font
from gui.widgets.charts import ConnectionPath, Sparkline
from gui.widgets.common import (Card, Label, section_label, button, link_button, hbox, clear_layout,
                                StatusDot, relative_time)
from network.detector import NetworkDetector
from network.reporting import ReportGenerator
from network.system_tools import SystemTools

REFRESH_MS = 10_000
GATEWAY_PING_INTERVAL = 2.0   # seconds; 300 samples = 10 minutes


def adapter_state(ipv4):
    """('active' | 'apipa' | 'inactive') with the existing active/APIPA rules."""
    if ipv4.startswith('169.254'):
        return 'apipa'
    if ipv4 != 'N/A' and not ipv4.startswith('127.') and not ipv4.startswith('169.'):
        return 'active'
    return 'inactive'


class NetworkInfoThread(QThread):
    info_ready = pyqtSignal(dict)

    def run(self):
        detector = NetworkDetector()
        try:
            info = detector.get_network_info()
            info['diagnostics'] = detector.detect_network_issues(info)
            info['path'] = detector.probe_connection_path(info)
            info['primary'] = detector.get_primary_interface()
            self.info_ready.emit(info)
        except Exception as e:
            logging.error(f"NetworkInfoThread.run - Error: {e}")
            self.info_ready.emit({"error": str(e)})


class GatewayPinger(QThread):
    """Pings the gateway every 2 s while the Dashboard is visible."""
    sample = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gateway = None
        self._active = False
        self.detector = NetworkDetector()

    def run(self):
        self._active = True
        while self._active:
            started = time.monotonic()
            if self.gateway:
                self.sample.emit(self.detector._ping_time(self.gateway, timeout=1))
            while self._active and time.monotonic() - started < GATEWAY_PING_INTERVAL:
                self.msleep(100)

    def stop(self):
        self._active = False


class TaskThread(QThread):
    """Runs a callable off the GUI thread (quick actions, reports)."""
    done = pyqtSignal(object)

    def __init__(self, func, parent=None):
        super().__init__(parent)
        self.func = func

    def run(self):
        try:
            self.done.emit(self.func())
        except Exception as e:
            self.done.emit(e)


class DashboardPage(Page):
    overall_status = pyqtSignal(str, str, str)   # online/local/offline, iface, ip
    issues_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__("Dashboard", "…", scroll=True)
        self.system_tools = SystemTools()
        self.info_thread = None
        self.task_thread = None
        self.issues = []
        self.hostname = ""

        self.refresh_btn = button("Refresh", "secondary")
        self.refresh_btn.clicked.connect(self.refresh_info)
        self.report_btn = button("Generate report", "primary")
        self.report_btn.clicked.connect(self.generate_report)
        self.header.set_actions(self.refresh_btn, self.report_btn)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for column in range(12):
            grid.setColumnStretch(column, 1)
        self.body.addLayout(grid)
        self.body.addStretch(1)

        # Connection path
        path_card = Card(margins=(20, 14, 20, 14))
        self.path = ConnectionPath()
        path_card.body.addWidget(self.path)
        grid.addWidget(path_card, 0, 0, 1, 12)

        # Issues
        self.issues_card = Card("issues", margins=(0, 0, 0, 0), spacing=0)
        self.issues_title = section_label("", Colors.RED)
        title_row = QWidget()
        title_row.setLayout(hbox(self.issues_title, margins=(16, 12, 16, 10)))
        self.issues_card.body.addWidget(title_row)
        self.issues_rows = QVBoxLayout()
        self.issues_rows.setSpacing(0)
        self.issues_card.body.addLayout(self.issues_rows)
        self.issues_card.setVisible(False)
        grid.addWidget(self.issues_card, 1, 0, 1, 12)

        # Gateway latency
        latency_card = Card(margins=(16, 14, 16, 12))
        self.latency_now = Label("—", 12.5, 500, Colors.TEXT_STRONG, mono=True)
        self.latency_stats = Label("", 11, color=Colors.TEXT_MUTED, mono=True)
        latency_card.body.addLayout(hbox(section_label("Gateway latency · last 10 min"), "stretch",
                                         self.latency_now, self.latency_stats))
        self.sparkline = Sparkline(capacity=int(600 / GATEWAY_PING_INTERVAL))
        latency_card.body.addWidget(self.sparkline, 1)
        grid.addWidget(latency_card, 2, 0, 1, 7)

        # Last speed test
        speed_card = Card(margins=(16, 14, 16, 14))
        self.speed_title = section_label("Last speed test")
        run_link = link_button("Run")
        run_link.clicked.connect(lambda: self.navigate.emit('speed', {'action': 'run'}))
        speed_card.body.addLayout(hbox(self.speed_title, "stretch", run_link))
        self.speed_values = QHBoxLayout()
        self.speed_values.setSpacing(12)
        speed_card.body.addLayout(self.speed_values)
        speed_card.body.addStretch(1)
        grid.addWidget(speed_card, 2, 7, 1, 5)

        # Adapters
        adapters_card = Card(margins=(0, 0, 0, 0), spacing=0)
        adapters_head = QWidget()
        adapters_head.setLayout(hbox(section_label("Adapters"), margins=(16, 12, 16, 10)))
        adapters_card.body.addWidget(adapters_head)
        self.adapter_rows = QVBoxLayout()
        self.adapter_rows.setSpacing(0)
        adapters_card.body.addLayout(self.adapter_rows)
        adapters_card.body.addStretch(1)
        grid.addWidget(adapters_card, 3, 0, 1, 7)

        # Quick actions
        actions_card = Card(margins=(16, 14, 16, 14))
        actions_card.body.addWidget(section_label("Quick actions"))
        self.adapter_combo = QComboBox()
        self.adapter_combo.setFixedHeight(32)
        self.adapter_combo.setFont(ui_font(12.5))
        self.adapter_combo.addItem("All adapters")
        self.adapter_combo.setToolTip("Select target adapter for IP operations")
        actions_card.body.addWidget(self.adapter_combo)
        self.btn_renew = button("Renew IP", "ghost", 30)
        self.btn_flush = button("Flush DNS", "ghost", 30)
        self.btn_release = button("Release IP", "ghost", 30)
        self.btn_renew.clicked.connect(lambda: self.run_quick_action("renew_ip"))
        self.btn_flush.clicked.connect(lambda: self.run_quick_action("flush_dns"))
        self.btn_release.clicked.connect(lambda: self.run_quick_action("release_ip"))
        row = hbox(self.btn_renew, self.btn_flush, self.btn_release, spacing=6)
        for i in range(3):
            row.setStretch(i, 1)
        actions_card.body.addLayout(row)
        actions_card.body.addWidget(Label(self.system_tools.privilege_note(), 11.5, color=Colors.TEXT_MUTED))
        actions_card.body.addStretch(1)
        grid.addWidget(actions_card, 3, 7, 1, 5)

        # Recent tests
        recent_card = Card(margins=(0, 0, 0, 0), spacing=0)
        recent_head = QWidget()
        recent_head.setLayout(hbox(section_label("Recent tests"), margins=(16, 12, 16, 10)))
        recent_card.body.addWidget(recent_head)
        self.recent_rows = QVBoxLayout()
        self.recent_rows.setSpacing(0)
        recent_card.body.addLayout(self.recent_rows)
        grid.addWidget(recent_card, 4, 0, 1, 12)

        # Timers and threads
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_info)
        self.timer.start(REFRESH_MS)
        self.ago_timer = QTimer(self)
        self.ago_timer.timeout.connect(self.update_recent)
        self.ago_timer.start(60_000)
        self.pinger = GatewayPinger(self)
        self.pinger.sample.connect(self.on_gateway_sample)

        recent_store().changed.connect(self.update_recent)
        recent_store().changed.connect(self.update_last_speed)
        self.update_recent()
        self.update_last_speed()
        self.refresh_info()

    # ------------------------------------------------------------ lifecycle
    def showEvent(self, event):
        super().showEvent(event)
        if not self.pinger.isRunning():
            self.pinger.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.pinger.stop()

    def cleanup(self):
        self.timer.stop()
        self.ago_timer.stop()
        self.pinger.stop()
        self.pinger.wait(3000)
        for thread in (self.info_thread, self.task_thread):
            if thread and thread.isRunning():
                thread.wait(10000)

    # ------------------------------------------------------------ refresh
    def refresh_info(self):
        if self.info_thread and self.info_thread.isRunning():
            return  # a refresh is already in flight
        self.info_thread = NetworkInfoThread(self)
        self.info_thread.info_ready.connect(self.update_ui)
        self.info_thread.start()

    def update_ui(self, info):
        if info.get('error'):
            self.header.set_subtitle(f"Error: {info['error']}")
            self.overall_status.emit("offline", "", "")
            return

        self.hostname = info.get('hostname', '')
        self.header.set_subtitle(f"{self.hostname} · auto-refresh 10 s")
        gateways = [g for g in info.get('gateway', []) if g not in ('N/A', '0.0.0.0')]
        self.pinger.gateway = gateways[0] if gateways else None

        nodes = info.get('path', [])
        if nodes:
            self.path.set_nodes(nodes)

        self.update_issues(info)
        self.update_adapters(info)

        connections = info.get('connections', [])
        internet = next((c['status'] for c in connections if c['description'] == 'Internet Connection'), '')
        local = next((c['status'] for c in connections if c['description'] == 'Local Network'), '')
        status = "online" if internet == 'Connected' else "local" if local == 'Connected' else "offline"
        iface, ip = info.get('primary') or ("", None)
        self.overall_status.emit(status, iface or "", ip or "")

    # ------------------------------------------------------------ issues
    def update_issues(self, info):
        diagnostics = info.get('diagnostics', {})
        self.issues = diagnostics.get('issues', [])
        clear_layout(self.issues_rows)
        self.issues_card.setVisible(bool(self.issues))
        count = len(self.issues)
        self.issues_title.setText(f"{count} ISSUE{'S' if count != 1 else ''}")
        self.issues_changed.emit(count)
        dns = [d for d in info.get('dns', []) if d != 'N/A']

        for issue in self.issues:
            kind = issue.get('type')
            critical = issue.get('severity') == 'critical'
            title, description, actions = issue.get('message', ''), issue.get('solution', ''), []
            if kind == 'dns_failure':
                title = "DNS resolution failed"
                server = dns[0] if dns else "Your DNS server"
                description = f"{server} did not answer. Flush the cache, or switch to 8.8.8.8 / 1.1.1.1."
                flush = button("Flush DNS", "danger", 28)
                flush.clicked.connect(lambda: self.run_quick_action("flush_dns"))
                actions = [flush, self._troubleshoot_button()]
            elif kind == 'apipa_address':
                adapter = issue.get('adapter', '')
                title = f"{adapter}: APIPA address"
                description = f"{issue.get('address', '')} is self-assigned. DHCP server not responding."
                renew = button(f"Renew IP · {adapter}", "warn", 30)
                renew.clicked.connect(lambda _=False, a=adapter: self.run_quick_action("renew_ip", a))
                actions = [renew]
            elif kind == 'gateway_unreachable':
                title = "Gateway unreachable"
                actions = [self._troubleshoot_button()]
            elif kind == 'no_gateway':
                title = "No default gateway"
                renew = button("Renew IP", "warn", 30)
                renew.clicked.connect(lambda: self.run_quick_action("renew_ip"))
                actions = [renew]

            row = QFrame()
            row.setProperty("row", "true")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(16, 10, 16, 10)
            layout.setSpacing(12)
            layout.addWidget(StatusDot(Colors.RED if critical else Colors.YELLOW, 7))
            name = Label(title, 12.5, 500, Colors.TEXT_STRONG)
            name.setFixedWidth(240)
            layout.addWidget(name)
            text = Label(description, 12.5, color=Colors.TEXT)
            text.setWordWrap(True)
            layout.addWidget(text, 1)
            for action in actions:
                layout.addWidget(action)
            self.issues_rows.addWidget(row)

    def _troubleshoot_button(self):
        btn = button("Troubleshoot", "secondary", 28)
        btn.clicked.connect(lambda: self.navigate.emit('trouble', {'action': 'run'}))
        return btn

    # ------------------------------------------------------------ adapters
    def update_adapters(self, info):
        interfaces = info.get('interfaces', [])
        active, inactive = [], []
        for iface in interfaces:
            ipv4 = iface.get('ipv4', 'N/A')
            if ipv4.startswith('127.') or iface.get('name') == 'lo':
                continue  # loopback is not an adapter
            (active if adapter_state(ipv4) != 'inactive' else inactive).append(iface)
        # Keep the existing order: active/APIPA first, then alphabetical
        active.sort(key=lambda x: x.get('name', ''))
        inactive.sort(key=lambda x: x.get('name', ''))

        clear_layout(self.adapter_rows)
        for iface in active + inactive:
            ipv4 = iface.get('ipv4', 'N/A')
            state = adapter_state(ipv4)
            row = QFrame()
            row.setProperty("row", "true")
            if state == 'apipa':
                row.setStyleSheet(f"QFrame {{ background: {Colors.SURFACE_2}; }}")
            row.setFixedHeight(34)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(16, 0, 16, 0)
            layout.setSpacing(10)
            name = Label(iface.get('name', ''), 12.5, color=Colors.TEXT_STRONG if state != 'inactive' else Colors.TEXT)
            name.setFixedWidth(140)
            status_text, status_color = {
                'active': ("● Active", Colors.GREEN),
                'apipa': ("● Limited", Colors.YELLOW),
                'inactive': ("○ Inactive", Colors.TEXT_MUTED),
            }[state]
            status = Label(status_text, 11.5, 600, status_color)
            status.setFixedWidth(96)
            ip_color = {'active': Colors.BLUE, 'apipa': Colors.YELLOW}.get(state, Colors.TEXT_FAINT)
            ip = Label(ipv4 if state != 'inactive' else "—", 12.5, color=ip_color, mono=True)
            ip.setTextInteractionFlags(Qt.TextSelectableByMouse)
            ip.setFixedWidth(150)
            mac = Label(iface.get('mac', 'N/A').upper(), 11.5, color=Colors.TEXT_MUTED, mono=True)
            mac.setTextInteractionFlags(Qt.TextSelectableByMouse)
            for widget in (name, status, ip):
                layout.addWidget(widget)
            layout.addWidget(mac, 1)
            self.adapter_rows.addWidget(row)

        # Adapter combo: active/APIPA adapters only
        current = self.adapter_combo.currentText()
        self.adapter_combo.blockSignals(True)
        self.adapter_combo.clear()
        self.adapter_combo.addItem("All adapters")
        for iface in active:
            self.adapter_combo.addItem(iface.get('name', ''))
        index = self.adapter_combo.findText(current)
        self.adapter_combo.setCurrentIndex(max(index, 0))
        self.adapter_combo.blockSignals(False)

    # ------------------------------------------------------------ gateway latency
    def on_gateway_sample(self, ms):
        self.sparkline.add(ms)
        data = [v for v in self.sparkline.values if v is not None]
        if ms is None:
            self.latency_now.setText("timeout")
            self.latency_now.set_color(Colors.RED)
        else:
            self.latency_now.setText(f"{ms:.1f} ms")
            self.latency_now.set_color(Colors.TEXT_STRONG)
        if len(data) >= 2:
            p95 = statistics.quantiles(data, n=20)[-1] if len(data) >= 3 else max(data)
            self.latency_stats.setText(f"p95 {p95:.1f} · max {max(data):.1f}")

    # ------------------------------------------------------------ last speed test
    def update_last_speed(self):
        clear_layout(self.speed_values)
        entry = recent_store().latest('speed')
        if not entry:
            self.speed_title.setText("LAST SPEED TEST")
            self.speed_values.addWidget(Label("No speed test yet.", 12.5, color=Colors.TEXT_MUTED))
            return
        self.speed_title.setText(f"LAST SPEED TEST · {relative_time(entry['time']).upper()}")
        data = entry.get('data', {})
        for title, color, value, unit in (
                ("Download", Colors.SERIES_DOWN, data.get('download_speed'), "Mbps"),
                ("Upload", Colors.SERIES_UP, data.get('upload_speed'), "Mbps"),
                ("Ping", Colors.YELLOW, data.get('ping'), "ms")):
            column = QVBoxLayout()
            column.setSpacing(2)
            column.addWidget(Label(title, 11.5, color=color))
            column.addWidget(Label("—" if not value else f"{value:.1f}", 22, 400, Colors.TEXT_STRONG, mono=True))
            column.addWidget(Label(unit, 11.5, color=Colors.TEXT_MUTED))
            self.speed_values.addLayout(column, 1)

    # ------------------------------------------------------------ recent tests
    def update_recent(self):
        clear_layout(self.recent_rows)
        entries = recent_store().items()[:5]
        if not entries:
            row = QFrame()
            row.setProperty("row", "true")
            row.setLayout(hbox(Label("No tests yet. Results from Diagnose host, Port scanner, Speed test and "
                                     "iPerf3 appear here.", 12.5, color=Colors.TEXT_MUTED), margins=(16, 10, 16, 12)))
            self.recent_rows.addWidget(row)
            return
        for entry in entries:
            row = QFrame()
            row.setProperty("row", "true")
            row.setFixedHeight(34)
            layout = QHBoxLayout(row)
            layout.setContentsMargins(16, 0, 16, 0)
            layout.setSpacing(10)
            kind = Label(KIND_TITLES.get(entry['kind'], entry['kind']), 12.5, color=Colors.TEXT_STRONG)
            kind.setFixedWidth(130)
            target = Label(entry['target'], 12, color=Colors.TEXT, mono=True)
            target.setFixedWidth(220)
            summary = Label(entry['summary'], 12, color=Colors.TEXT_MUTED, mono=True)
            when = Label(relative_time(entry['time']), 12, color=Colors.TEXT_MUTED)
            when.setFixedWidth(90)
            open_link = link_button("Open")
            page = {'diagnose': 'diagnose', 'port': 'port', 'speed': 'speed', 'iperf': 'iperf',
                    'monitor': 'health'}[entry['kind']]
            open_link.clicked.connect(lambda _=False, p=page, e=entry['id']: self.navigate.emit(p, {'open': e}))
            layout.addWidget(kind)
            layout.addWidget(target)
            layout.addWidget(summary, 1)
            layout.addWidget(when)
            layout.addWidget(open_link)
            self.recent_rows.addWidget(row)

    # ------------------------------------------------------------ actions
    def run_quick_action(self, action_name, adapter=None):
        if self.task_thread and self.task_thread.isRunning():
            return
        selected = adapter or self.adapter_combo.currentText()
        adapter_arg = None if selected == "All adapters" else selected
        if action_name == "release_ip":
            target = adapter_arg or "all adapters"
            answer = QMessageBox.question(self, "Release IP",
                                          f"Release the IP address of {target}? The connection drops until it is "
                                          "renewed.")
            if answer != QMessageBox.Yes:
                return
        descriptions = {"renew_ip": f"Renew IP ({selected})", "flush_dns": "Flush DNS",
                        "release_ip": f"Release IP ({selected})"}
        funcs = {"renew_ip": lambda: self.system_tools.renew_ip(adapter_arg),
                 "flush_dns": self.system_tools.flush_dns,
                 "release_ip": lambda: self.system_tools.release_ip(adapter_arg)}
        description = descriptions[action_name]
        for btn in (self.btn_renew, self.btn_flush, self.btn_release):
            btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.task_thread = TaskThread(funcs[action_name], self)
        self.task_thread.done.connect(lambda result: self.on_action_done(description, result))
        self.task_thread.start()

    def on_action_done(self, description, result):
        QApplication.restoreOverrideCursor()
        for btn in (self.btn_renew, self.btn_flush, self.btn_release):
            btn.setEnabled(True)
        if isinstance(result, Exception):
            QMessageBox.critical(self, "Error", f"An error occurred: {result}")
            return
        success, output = result
        if success:
            QMessageBox.information(self, "Success", f"{description} completed successfully.\n\nOutput:\n{output}")
            self.refresh_info()
        else:
            QMessageBox.warning(self, "Failed", f"{description} failed.\n\nError:\n{output}")

    def generate_report(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        options = QFileDialog.Options() | QFileDialog.DontUseNativeDialog
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Network Report", f"network_report_{timestamp}.txt",
                                                   "Text Files (*.txt);;All Files (*)", options=options)
        if not file_path:
            return
        self.report_btn.setEnabled(False)
        self.report_btn.setText("Generating…")
        self.task_thread = TaskThread(lambda: ReportGenerator().generate_text_report(file_path), self)
        self.task_thread.done.connect(self.on_report_done)
        self.task_thread.start()

    def on_report_done(self, result):
        self.report_btn.setEnabled(True)
        self.report_btn.setText("Generate report")
        if isinstance(result, Exception):
            QMessageBox.critical(self, "Error", f"Failed to generate report: {result}")
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Report Generated")
        msg.setText(f"Report saved successfully:\n{result}")
        msg.setStandardButtons(QMessageBox.Open | QMessageBox.Ok)
        if msg.exec_() == QMessageBox.Open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(result))
