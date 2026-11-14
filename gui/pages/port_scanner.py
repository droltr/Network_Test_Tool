"""Port scanner: presets or a custom range, live port map, open ports table."""
import socket
from datetime import datetime

from PyQt5.QtCore import QLocale, QThread, QSettings, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetrics
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QComboBox,
                             QDoubleSpinBox, QProgressBar, QCompleter, QApplication, QTableWidgetItem)

from gui.pages.base import Page, finish_thread
from gui.recent import recent_store
from gui.styles.modern_theme import Colors, mono_font, ui_font
from gui.widgets.common import (Card, Label, LineInput, EmptyPane, ErrorCard, section_label, button,
                                link_button, hbox, make_table, cell_widget, StatusDot, clear_layout)
from gui.widgets.port_map import PortMap
from network.scanner import PortScanner

CUSTOM = "Custom range…"


class PortScanThread(QThread):
    progress_update = pyqtSignal(int)
    result_ready = pyqtSignal(dict)
    scan_complete = pyqtSignal(list)

    def __init__(self, host, ports, timeout, parent=None):
        super().__init__(parent)
        self.host = host
        self.ports = ports
        self.timeout = timeout
        self.scanner = PortScanner()

    def run(self):
        self.scanner.scan_ports(
            host=self.host,
            ports=self.ports,
            timeout=self.timeout,
            progress_callback=self.progress_update.emit,
            result_callback=self.result_ready.emit
        )
        self.scan_complete.emit(self.scanner.results)

    def stop(self):
        self.scanner.stop_scan()


class PortScannerPage(Page):
    def __init__(self):
        super().__init__("Port scanner", "Only scan systems you are allowed to test")
        self.settings = QSettings("NetworkTools", "PortScanner")
        self.history = self.settings.value("host_history", [], type=list)
        self.port_presets = PortScanner.get_common_ports()
        self.scan_thread = None
        self.results = []
        self.host = ""
        self.ports = []
        self.completed_at = None

        self.export_btn = button("Export", "secondary")
        self.export_btn.clicked.connect(self.export_results)
        self.header_stop = button("Stop", "stop")
        self.header_stop.clicked.connect(self.stop_scan)

        # Settings bar
        self.form = Card(margins=(12, 12, 12, 12))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.host_input = LineInput("Target host")
        self.host_input.setText("127.0.0.1")
        self.host_input.setFixedWidth(220)
        self.host_input.returnPressed.connect(self.start_scan)
        self.host_input.setCompleter(QCompleter(self.history, self))
        self.preset_combo = QComboBox()
        self.preset_combo.setFont(ui_font(12.5))
        self.preset_combo.setFixedSize(200, 34)
        self.preset_combo.addItems(list(self.port_presets.keys()) + [CUSTOM])
        self.preset_combo.currentTextChanged.connect(self.on_preset_changed)
        self.range_start = LineInput("Start", height=34)
        self.range_end = LineInput("End", height=34)
        self.range_start.setText("1")
        self.range_end.setText("1000")
        for field in (self.range_start, self.range_end):
            field.setFixedWidth(84)
        self.range_to = Label("to", 12.5, color=Colors.TEXT_MUTED)
        self.timeout_input = QDoubleSpinBox()
        self.timeout_input.setRange(0.1, 10.0)
        self.timeout_input.setSingleStep(0.5)
        self.timeout_input.setValue(1.0)
        self.timeout_input.setDecimals(1)
        self.timeout_input.setPrefix("timeout ")
        self.timeout_input.setSuffix(" s")
        self.timeout_input.setFont(mono_font(12))
        self.timeout_input.setLocale(QLocale.c())
        # Room for the widest value; the spin box keeps some space for its hidden arrows
        widest = QFontMetrics(self.timeout_input.font()).horizontalAdvance("timeout 10.0 s")
        self.timeout_input.setFixedSize(widest + 52, 34)
        self.timeout_input.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.scan_btn = button("Scan", "primary", 34, width=66)
        self.scan_btn.clicked.connect(self.start_scan)
        for widget in (self.host_input, self.preset_combo, self.range_start, self.range_to, self.range_end,
                       self.timeout_input):
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(self.scan_btn)
        self.form.body.addLayout(row)
        self.body.addWidget(self.form)

        # Running bar
        self.progress_card = Card(margins=(14, 10, 14, 10))
        self.progress_label = Label("", 12.5, color=Colors.TEXT_STRONG)
        self.progress_label.setMinimumWidth(130)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_count = Label("", 11.5, color=Colors.TEXT_MUTED, mono=True)
        progress_row = hbox(self.progress_label, 6, self.progress_bar, 6, self.progress_count, spacing=8)
        progress_row.setStretchFactor(self.progress_bar, 1)
        self.progress_card.body.addLayout(progress_row)
        self.body.addWidget(self.progress_card)

        self.views = QStackedWidget()
        self.body.addWidget(self.views, 1)

        self.empty = EmptyPane("No scan yet", "The port map fills in as ports are checked.")
        self.views.addWidget(self.empty)

        # Map + table view
        result = QWidget()
        rl = QVBoxLayout(result)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)
        map_card = Card(margins=(16, 12, 16, 16), spacing=12)
        self.map_title = section_label("Port map")
        self.legend = QHBoxLayout()
        self.legend.setSpacing(14)
        map_card.body.addLayout(hbox(self.map_title, "stretch", self.legend))
        self.port_map = PortMap()
        map_card.body.addWidget(self.port_map)
        rl.addWidget(map_card)
        self.open_table = make_table(["Port", "Service", "State", ""], stretch_column=1)
        self.open_table.horizontalHeader().resizeSection(0, 100)
        self.open_table.horizontalHeader().resizeSection(2, 120)
        self.open_table.horizontalHeader().resizeSection(3, 96)
        self.open_table.setColumnCount(4)
        rl.addWidget(self.open_table, 1)
        self.views.addWidget(result)
        self.result_view = result

        self.error_card = ErrorCard()
        self.views.addWidget(self.error_card)

        self.on_preset_changed(self.preset_combo.currentText())
        self.show_idle()

    # ------------------------------------------------------------ form
    def on_preset_changed(self, preset_name):
        custom = preset_name == CUSTOM
        for widget in (self.range_start, self.range_to, self.range_end):
            widget.setVisible(custom)

    def get_ports_to_scan(self):
        """Get the list of ports to scan based on current selection."""
        preset_name = self.preset_combo.currentText()
        if preset_name in self.port_presets:
            return self.port_presets[preset_name]
        try:
            start = int(self.range_start.text())
            end = int(self.range_end.text())
        except ValueError:
            return []
        if not (1 <= start <= end <= 65535):
            return []
        return list(range(start, end + 1))

    def range_text(self):
        if not self.ports:
            return ""
        if len(self.ports) == 1:
            return str(self.ports[0])
        low, high = min(self.ports), max(self.ports)
        if high - low + 1 == len(self.ports):
            return f"{low}–{high}"
        return f"{len(self.ports)} ports"

    def save_history(self):
        if self.host_input.text() not in self.history:
            self.history.insert(0, self.host_input.text())
            del self.history[10:]  # Keep last 10 entries
            self.settings.setValue("host_history", self.history)
            self.host_input.setCompleter(QCompleter(self.history, self))

    # ------------------------------------------------------------ states
    def show_idle(self):
        self.form.setVisible(True)
        self.progress_card.setVisible(False)
        self.header.set_subtitle("Only scan systems you are allowed to test")
        self.header.set_actions()
        self.views.setCurrentWidget(self.empty)

    def show_error(self, kicker, message, help_text):
        retry = button("Try again", "primary", 32)
        retry.clicked.connect(self.start_scan)
        self.error_card.show_error(kicker, message, None, help_text, [retry])
        self.header.set_actions()
        self.views.setCurrentWidget(self.error_card)

    def handle_request(self, payload):
        if payload.get('open') and not self.running:
            entry = recent_store().get(payload['open'])
            if entry:
                self.load_entry(entry)

    # ------------------------------------------------------------ scan
    def start_scan(self):
        if self.running:
            return
        host = self.host_input.text().strip()
        if not host:
            self.host_input.set_error(True)
            return
        ports = self.get_ports_to_scan()
        if not ports:
            self.show_error("Invalid range", "No valid ports to scan",
                            "Enter a start and end port between 1 and 65535, with the start not above the end.")
            return
        try:
            socket.getaddrinfo(host, None, socket.AF_INET)
        except (OSError, UnicodeError):
            self.host_input.set_error(True)
            self.show_error("Could not resolve host", f"{host} did not resolve to an address, so the scan was "
                            "not started.", "Check the spelling, or scan an IP address instead.")
            return

        self.host, self.ports, self.results = host, ports, []
        self.host_input.set_error(False)
        self.save_history()
        self.set_running(True)
        self.form.setVisible(False)
        self.progress_card.setVisible(True)
        self.progress_bar.setRange(0, len(ports))
        self.progress_bar.setValue(0)
        self.header.set_subtitle(f"{host}  ·  {self.range_text()}", mono=True)
        self.header.set_actions(self.header_stop)
        self.port_map.set_ports(ports)
        self.port_map.set_probing(ports[0])
        self.open_table.setRowCount(0)
        self.set_table_title("Open so far")
        self.update_legend(running=True)
        self.update_progress()
        self.views.setCurrentWidget(self.result_view)

        self.scan_thread = PortScanThread(host, ports, self.timeout_input.value(), self)
        self.scan_thread.result_ready.connect(self.on_port_result)
        self.scan_thread.scan_complete.connect(self.on_scan_complete)
        self.scan_thread.start()

    def stop_scan(self):
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()

    def update_progress(self):
        done, total = len(self.results), len(self.ports)
        current = self.ports[min(done, total - 1)] if total else 0
        self.progress_label.setText(f"Scanning port {current}")
        self.progress_bar.setValue(done)
        self.progress_count.setText(f"{done} / {total} · {done * 100 // max(total, 1)}%")

    def on_port_result(self, result):
        self.results.append(result)
        port, status = result.get('port'), result.get('status')
        self.port_map.set_result(port, status, result.get('service'))
        done = len(self.results)
        self.port_map.set_probing(self.ports[done] if done < len(self.ports) else None)
        if status == 'Open':
            self.add_open_row(port, result.get('service'), copy=False)
            self.update_legend(running=True)
        if done % 8 == 0 or done == len(self.ports):
            self.update_progress()

    def on_scan_complete(self, results):
        self.results = results
        self.set_running(False)
        self.port_map.set_probing(None)
        self.completed_at = datetime.now()
        self.show_results()
        open_ports = [r for r in results if r.get('status') == 'Open']
        recent_store().add('port', self.host, f"{len(open_ports)} open of {len(results)}", {
            'ports': [self.ports[0], self.ports[-1]] if self.preset_combo.currentText() == CUSTOM else None,
            'preset': self.preset_combo.currentText(),
            'scanned': [[r['port'], r['status'], r.get('service')] for r in results
                        if r.get('status') != 'Closed'],
            'total': len(results),
            'all_ports': self.ports if len(self.ports) <= 4096 else None,
            'completed': self.completed_at.isoformat(timespec='seconds'),
        })

    def show_results(self):
        self.form.setVisible(True)
        self.progress_card.setVisible(False)
        if self.completed_at:
            self.header.set_subtitle_parts(self.host, f"completed {self.completed_at:%H:%M}")
        else:
            self.header.set_subtitle(self.host, mono=True)
        self.header.set_actions(self.export_btn)
        self.update_legend(running=False)
        self.open_table.setRowCount(0)
        self.set_table_title(None)
        for result in self.results:
            if result.get('status') == 'Open':
                self.add_open_row(result['port'], result.get('service'), copy=True)
        if not any(r.get('status') == 'Open' for r in self.results):
            self.open_table.setRowCount(1)
            item = QTableWidgetItem("No open ports found.")
            item.setForeground(QColor(Colors.TEXT_MUTED))
            self.open_table.setItem(0, 0, item)
            self.open_table.setSpan(0, 0, 1, 4)
        self.views.setCurrentWidget(self.result_view)

    def set_table_title(self, running_title):
        if running_title:
            self.open_table.setHorizontalHeaderLabels([running_title.upper(), "", "", ""])
            self.open_table.setColumnHidden(2, True)
            self.open_table.setColumnHidden(3, True)
        else:
            self.open_table.setHorizontalHeaderLabels(["PORT", "SERVICE", "STATE", ""])
            self.open_table.setColumnHidden(2, False)
            self.open_table.setColumnHidden(3, False)
        self.open_table.clearSpans()

    def add_open_row(self, port, service, copy):
        row = self.open_table.rowCount()
        self.open_table.insertRow(row)
        cells = ((str(port), mono_font(12.5), Colors.TEXT_STRONG),
                 (service if service and service != "Unknown" else "unknown", ui_font(12.5), Colors.TEXT),
                 ("Open", ui_font(12.5), Colors.GREEN))
        for column, (text, font, color) in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setFont(font)
            item.setForeground(QColor(color))
            self.open_table.setItem(row, column, item)
        if copy:
            link = link_button("Copy")
            link.clicked.connect(lambda _=False, p=port, s=service: QApplication.clipboard().setText(
                f"{self.host}:{p}" + (f" ({s})" if s and s != "Unknown" else "")))
            self.open_table.setCellWidget(row, 3, cell_widget(link))

    def update_legend(self, running):
        clear_layout(self.legend)
        counts = {'Open': 0, 'Closed': 0, 'Error': 0}
        for result in self.results:
            counts[result.get('status', 'Error')] = counts.get(result.get('status', 'Error'), 0) + 1
        span = self.range_text()
        self.map_title.setText(f"PORT MAP · {span.replace('–', ' → ')}" if span else "PORT MAP")

        def entry(color, style, text):
            return hbox(StatusDot(color, 8, style), Label(text, 12, color=Colors.TEXT), spacing=4)

        self.legend.addLayout(entry(Colors.GREEN, "filled", f"open {counts['Open']}"))
        if running:
            self.legend.addLayout(entry(Colors.SURFACE_2, "filled", "closed"))
            self.legend.addLayout(entry(Colors.SURFACE_2, "hollow", "pending"))
        else:
            self.legend.addLayout(entry(Colors.SURFACE_2, "filled", f"closed {counts['Closed']}"))
            self.legend.addWidget(Label(f"errors {counts['Error']}", 12, color=Colors.TEXT_MUTED))

    def load_entry(self, entry):
        data = entry.get('data', {})
        self.host = entry['target']
        self.host_input.setText(self.host)
        known = {port: (status, service) for port, status, service in data.get('scanned', [])}
        preset = data.get('preset')
        if data.get('all_ports'):
            ports = data['all_ports']
        elif preset in self.port_presets:
            ports = self.port_presets[preset]
        else:
            ports = sorted(known)
        if preset and self.preset_combo.findText(preset) >= 0:
            self.preset_combo.setCurrentText(preset)
        self.ports = ports
        self.results = [{'port': port, 'status': known.get(port, ('Closed', None))[0],
                         'service': known.get(port, (None, None))[1]} for port in ports]
        self.port_map.set_ports(ports)
        for result in self.results:
            self.port_map.set_result(result['port'], result['status'], result['service'])
        try:
            self.completed_at = datetime.fromisoformat(data.get('completed', entry['time']))
        except ValueError:
            self.completed_at = None
        self.show_results()

    def export_results(self):
        open_ports = [r for r in self.results if r.get('status') == 'Open']
        closed = [r for r in self.results if r.get('status') == 'Closed']
        errors = [r for r in self.results if r.get('status') == 'Error']
        lines = [f"Port scan on {self.host}", f"Ports: {self.range_text()} ({len(self.ports)} ports)", "=" * 50]
        for result in open_ports:
            lines.append(f"Port {result['port']}: OPEN ({result.get('service') or 'Unknown'})")
        lines += ["", "=" * 50, "SCAN SUMMARY", "=" * 50,
                  f"Total ports scanned: {len(self.results)}",
                  f"Open ports: {len(open_ports)}",
                  f"Closed ports: {len(closed)}",
                  f"Errors: {len(errors)}"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.save_text("Save Log File", f"port_scan_results_{timestamp}.txt", "\n".join(lines) + "\n")

    def cleanup(self):
        self.stop_scan()
        finish_thread(self.scan_thread, 5000)
