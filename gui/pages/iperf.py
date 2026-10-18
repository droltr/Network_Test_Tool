"""iPerf3: client against public or custom servers, and a built-in iperf3-compatible server."""
import socket
import time
from datetime import datetime

import psutil
from PyQt5.QtCore import Qt, QThread, QSettings, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QButtonGroup, QComboBox,
                             QSpinBox, QTableWidgetItem, QApplication, QAbstractItemView, QHeaderView)

from gui.pages.base import Page
from gui.recent import recent_store
from gui.styles.modern_theme import Colors, mono_font, ui_font
from gui.widgets.charts import ThroughputChart, SpeedGauge
from gui.widgets.common import (Card, Label, LineInput, LogPane, EmptyPane, StatusDot, PulseDot, section_label,
                                button, link_button, hbox, make_table, clear_layout, set_prop, chip_group,
                                selected_key)
from network import iperf_servers
from network.iperf import IperfClient, IperfServer, DEFAULT_PORT

DIRECTIONS = [("download", "Download"), ("upload", "Upload"), ("both", "Both")]
RETRYABLE = ("busy", "refused", "reset", "closed by the other side", "did not respond")
MAX_PORT_TRIES = 6


def iperf_command(host, port, direction, streams, duration):
    """The equivalent iperf3 command line, shown so users learn the tool."""
    parts = ["iperf3", "-c", host or "<server>"]
    if port != DEFAULT_PORT:
        parts += ["-p", str(port)]
    if streams > 1:
        parts += ["-P", str(streams)]
    parts += ["-t", str(duration)]
    if direction == "download":
        parts.append("-R")
    return " ".join(parts)


class ClientThread(QThread):
    phase = pyqtSignal(str, int)           # direction, port
    interval = pyqtSignal(str, float, float)
    log = pyqtSignal(str)
    done = pyqtSignal(dict)

    def __init__(self, host, ports, directions, streams, duration, parent=None):
        super().__init__(parent)
        self.host, self.ports, self.directions = host, list(ports), directions
        self.streams, self.duration = streams, duration
        self.client = None
        self._stopped = False

    def stop(self):
        self._stopped = True
        if self.client:
            self.client.stop()

    def run(self):
        results = {'host': self.host, 'streams': self.streams, 'duration': self.duration, 'tests': {}}
        port_index = 0
        for direction in self.directions:
            if self._stopped:
                break
            for attempt in range(min(MAX_PORT_TRIES, len(self.ports))):
                port = self.ports[(port_index + attempt) % len(self.ports)]
                self.phase.emit(direction, port)
                self.log.emit(f"$ {iperf_command(self.host, port, direction, self.streams, self.duration)}")
                self.client = IperfClient(
                    self.host, port, duration=self.duration, parallel=self.streams,
                    reverse=direction == "download",
                    interval_callback=lambda s, d=direction: self.interval.emit(d, s['t'], s['mbps']),
                    log_callback=self.log.emit)
                result = self.client.run()
                if not result['error']:
                    port_index = (port_index + attempt + 1) % len(self.ports)
                    break
                self.log.emit(f"Error: {result['error']}")
                retry = any(word in result['error'].lower() for word in RETRYABLE) and not self._stopped
                if not retry or len(self.ports) == 1 and attempt >= 1:
                    break
                self.log.emit("Trying the next port of this server…")
                time.sleep(1.5)
            results['tests'][direction] = result
            if result['error'] and not self._stopped:
                break
            if direction != self.directions[-1]:
                time.sleep(1.5)   # public servers restart between tests
        results['stopped'] = self._stopped
        self.done.emit(results)


class ServerThread(QThread):
    event = pyqtSignal(str, object)

    def __init__(self, port, parent=None):
        super().__init__(parent)
        self.server = IperfServer(port=port, event_callback=self.event.emit)

    def run(self):
        self.server.serve_forever()

    def stop(self):
        self.server.stop()


class ServerListThread(QThread):
    done = pyqtSignal(object)

    def run(self):
        try:
            self.done.emit(iperf_servers.refresh())
        except (OSError, ValueError) as e:
            self.done.emit(e)


class ResultCard(Card):
    def __init__(self, title, color):
        super().__init__(margins=(18, 14, 18, 14), spacing=4)
        self.setStyleSheet(f"QFrame[card=\"card\"] {{ border-top: 3px solid {color}; }}")
        self.value = Label("—", 34, 400, Colors.TEXT_FAINT, mono=True)
        self.body.addLayout(hbox(section_label(title, color, 11), "stretch", self.value,
                                 Label("Mbps", 12.5, color=Colors.TEXT_MUTED), spacing=8))
        self.detail = Label("", 11.5, color=Colors.TEXT_MUTED, mono=True)
        self.detail.setWordWrap(True)
        self.body.addWidget(self.detail)

    def set_result(self, result):
        if not result:
            self.value.setText("—")
            self.value.set_color(Colors.TEXT_FAINT)
            self.detail.setText("not run")
            return
        if result.get('error'):
            self.value.setText("—")
            self.value.set_color(Colors.TEXT_FAINT)
            self.detail.setText(result['error'][:70])
            return
        value = result.get('receiver_mbps') or result.get('sender_mbps') or 0
        self.value.setText(f"{value:.1f}")
        self.value.set_color(Colors.TEXT_STRONG)
        gb = (result.get('received_bytes') or result.get('sent_bytes') or 0) / 1e9
        retrans = result.get('retransmits')
        extra = f" · retr {retrans}" if retrans is not None else ""
        self.detail.setText(f"sender {result.get('sender_mbps', 0):.1f} · {gb:.2f} GB · "
                            f"port {result.get('port')}{extra}")


class IperfPage(Page):
    def __init__(self):
        super().__init__("iPerf3")
        self.settings = QSettings("NetworkTools", "Iperf")
        self.client_thread = None
        self.server_thread = None
        self.list_thread = None
        self.server_running = False
        self.client_running = False
        self.last_results = None

        self.tab_group = QButtonGroup(self)
        for index, text in enumerate(("Client", "Server")):
            tab = button(text, "tab", 47)
            tab.setCheckable(True)
            self.tab_group.addButton(tab, index)
            self.header.tabs.addWidget(tab)
        self.tab_group.buttonClicked[int].connect(lambda i: self.stack.setCurrentIndex(i))
        self.header.subtitle.setVisible(False)
        self.export_btn = button("Export", "secondary")
        self.export_btn.clicked.connect(self.export_results)
        self.body.setContentsMargins(20, 14, 20, 16)

        self.stack = QStackedWidget()
        self.body.addWidget(self.stack, 1)
        self.stack.addWidget(self.build_client())
        self.stack.addWidget(self.build_server())
        self.tab_group.button(0).setChecked(True)
        self.load_servers(iperf_servers.load())

    # ================================================================ client
    def build_client(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Server list
        servers = Card(margins=(0, 0, 0, 0), spacing=0)
        servers.setFixedWidth(410)
        head = QVBoxLayout()
        head.setContentsMargins(14, 12, 14, 10)
        head.setSpacing(8)
        self.list_title = section_label("Public servers")
        self.refresh_link = link_button("Refresh list")
        self.refresh_link.clicked.connect(self.refresh_servers)
        head.addLayout(hbox(self.list_title, "stretch", self.refresh_link))
        self.server_filter = LineInput("Filter city, country or provider", height=30, mono=False)
        self.server_filter.textChanged.connect(self.filter_servers)
        self.region_combo = QComboBox()
        self.region_combo.setFont(ui_font(12))
        self.region_combo.setFixedHeight(30)
        self.region_combo.currentTextChanged.connect(self.filter_servers)
        head.addLayout(hbox(self.server_filter, self.region_combo, spacing=6))
        servers.body.addLayout(head)
        self.server_table = make_table(["Location", "Provider", "Gb/s"], stretch_column=0, row_height=40,
                                       embedded=True)
        self.server_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.server_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.server_table.setFocusPolicy(Qt.StrongFocus)
        self.server_table.horizontalHeader().resizeSection(1, 130)
        self.server_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.server_table.horizontalHeader().resizeSection(2, 66)
        self.server_table.itemSelectionChanged.connect(self.on_server_selected)
        self.server_table.cellDoubleClicked.connect(lambda *_: self.start_client())
        servers.body.addWidget(self.server_table, 1)
        self.list_source = Label("", 11, color=Colors.TEXT_MUTED)
        self.list_source.setWordWrap(True)
        self.list_source.setContentsMargins(14, 8, 14, 10)
        servers.body.addWidget(self.list_source)
        layout.addWidget(servers)

        right = QVBoxLayout()
        right.setSpacing(12)

        # Test settings
        form = Card(margins=(14, 12, 14, 12), spacing=10)
        self.host_input = LineInput("host or IP", height=34)
        self.host_input.setText(self.settings.value("host", "", type=str))
        self.port_input = LineInput("5201", height=34)
        self.port_input.setFixedWidth(128)
        self.port_input.setText(self.settings.value("ports", "5201", type=str))
        self.port_input.setToolTip("A port or a range such as 5201-5209. Busy ports are skipped.")
        for field in (self.host_input, self.port_input):
            field.textChanged.connect(self.update_command)
        self.host_input.returnPressed.connect(self.start_client)
        self.direction_group, direction_row = chip_group(self, DIRECTIONS, "both")
        self.direction_group.buttonClicked.connect(self.update_command)
        self.streams_combo = QComboBox()
        self.streams_combo.addItems(["1", "2", "4", "8", "16"])
        self.streams_combo.setCurrentText("4")
        self.duration_combo = QComboBox()
        self.duration_combo.addItems(["5 s", "10 s", "20 s", "30 s", "60 s"])
        self.duration_combo.setCurrentText("10 s")
        for combo in (self.streams_combo, self.duration_combo):
            combo.setFont(ui_font(12))
            combo.setFixedSize(80, 30)
            combo.currentTextChanged.connect(self.update_command)
        self.run_btn = button("Run test", "primary", 34)
        self.run_btn.clicked.connect(self.start_client)
        self.stop_btn = button("Stop", "stop", 34)
        self.stop_btn.clicked.connect(self.stop_client)
        self.stop_btn.setVisible(False)
        # Two rows so the controls never get squeezed below their size in the narrow column
        form.body.addLayout(hbox(Label("Server", 12, color=Colors.TEXT_MUTED), self.host_input, 6,
                                 Label("Port", 12, color=Colors.TEXT_MUTED), self.port_input, 6,
                                 self.run_btn, self.stop_btn, spacing=8))
        form.body.addLayout(hbox(Label("Direction", 12, color=Colors.TEXT_MUTED), direction_row, 18,
                                 Label("Streams", 12, color=Colors.TEXT_MUTED), self.streams_combo, "stretch",
                                 spacing=6))
        form.body.addLayout(hbox(Label("Duration", 12, color=Colors.TEXT_MUTED), self.duration_combo, "stretch",
                                 spacing=6))
        self.command_label = Label("", 11.5, color=Colors.TEXT_MUTED, mono=True)
        self.command_label.setWordWrap(True)
        self.command_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        copy_cmd = link_button("Copy command")
        copy_cmd.clicked.connect(lambda: QApplication.clipboard().setText(self.command_text))
        terminal_label = Label("Same test in a terminal:", 11.5, color=Colors.TEXT_MUTED)
        terminal_label.setAlignment(Qt.AlignTop)
        self.command_label.setAlignment(Qt.AlignTop)
        form.body.addLayout(hbox(terminal_label, self.command_label, "stretch", copy_cmd, spacing=6))
        right.addWidget(form)

        # Results area
        self.client_views = QStackedWidget()
        self.client_empty = EmptyPane("Pick a server and run a test",
                                      "Download measures server → you (iperf3 -R), upload measures you → server. "
                                      "Several streams fill fast links better. Public servers allow one test at a "
                                      "time; busy ports are skipped automatically.")
        self.client_views.addWidget(self.client_empty)

        live = QWidget()
        ll = QHBoxLayout(live)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)
        gauge_card = Card(margins=(8, 8, 8, 8))
        gauge_card.setFixedWidth(270)
        self.gauge = SpeedGauge()
        gauge_card.body.addWidget(self.gauge, 1)
        ll.addWidget(gauge_card)
        chart_card = Card(margins=(16, 12, 16, 10))
        self.live_title = section_label("Throughput")
        chart_card.body.addWidget(self.live_title)
        self.live_chart = ThroughputChart(Colors.SERIES_DOWN)
        chart_card.body.addWidget(self.live_chart, 1)
        ll.addWidget(chart_card, 1)
        self.client_views.addWidget(live)
        self.live_view = live

        done = QWidget()
        dl = QVBoxLayout(done)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(12)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.download_card = ResultCard("Download", Colors.SERIES_DOWN)
        self.upload_card = ResultCard("Upload", Colors.SERIES_UP)
        cards.addWidget(self.download_card, 1)
        cards.addWidget(self.upload_card, 1)
        dl.addLayout(cards)
        charts = QHBoxLayout()
        charts.setSpacing(12)
        self.download_chart = ThroughputChart(Colors.SERIES_DOWN)
        self.upload_chart = ThroughputChart(Colors.SERIES_UP)
        for title, chart in (("Download · Mbps per second", self.download_chart),
                             ("Upload · Mbps per second", self.upload_chart)):
            card = Card(margins=(16, 12, 16, 10))
            card.body.addWidget(section_label(title))
            card.body.addWidget(chart, 1)
            charts.addWidget(card, 1)
        dl.addLayout(charts, 1)
        self.client_views.addWidget(done)
        self.done_view = done
        right.addWidget(self.client_views, 1)

        self.client_log = LogPane("Log")
        self.client_log.setFixedHeight(150)
        right.addWidget(self.client_log)
        layout.addLayout(right, 1)
        self.update_command()
        return page

    # ---- server list
    def load_servers(self, data):
        self.servers = data.get("servers", [])
        regions = sorted({s['continent'] for s in self.servers if s['continent']})
        current = self.region_combo.currentText()
        self.region_combo.blockSignals(True)
        self.region_combo.clear()
        self.region_combo.addItems(["All regions"] + regions)
        if current and self.region_combo.findText(current) >= 0:
            self.region_combo.setCurrentText(current)
        elif "Europe" in regions:
            self.region_combo.setCurrentText("Europe")
        self.region_combo.blockSignals(False)

        table = self.server_table
        table.setRowCount(len(self.servers))
        for row, server in enumerate(self.servers):
            location = QTableWidgetItem(f"{server['site']}, {server['country']}")
            location.setFont(ui_font(12.5, 500))
            location.setForeground(QColor(Colors.TEXT_STRONG))
            location.setToolTip(f"{server['host']}  ports {server['ports']}")
            location.setData(Qt.UserRole, row)
            provider = QTableWidgetItem(server['provider'])
            provider.setFont(ui_font(12))
            provider.setForeground(QColor(Colors.TEXT))
            speed = QTableWidgetItem(server['gbps'] or "—")
            speed.setFont(mono_font(11.5))
            speed.setForeground(QColor(Colors.TEXT_MUTED))
            for column, item in enumerate((location, provider, speed)):
                table.setItem(row, column, item)
        self.list_source.setText(f"{len(self.servers)} servers · updated {data.get('fetched', '?')} · from "
                                 f"iperf3serverlist.net by R0GGER (MIT). Availability changes often.")
        self.filter_servers()

    def filter_servers(self, *_):
        needle = self.server_filter.text().strip().lower()
        region = self.region_combo.currentText()
        shown = 0
        for row, server in enumerate(self.servers):
            haystack = " ".join((server['site'], server['country'], server['provider'], server['host'])).lower()
            visible = (region in ("", "All regions") or server['continent'] == region) and needle in haystack
            self.server_table.setRowHidden(row, not visible)
            shown += visible
        self.list_title.setText(f"PUBLIC SERVERS · {shown}")

    def on_server_selected(self):
        rows = self.server_table.selectionModel().selectedRows()
        if not rows:
            return
        server = self.servers[rows[0].row()]
        self.host_input.setText(server['host'])
        self.port_input.setText(server['ports'])

    def refresh_servers(self):
        if self.list_thread and self.list_thread.isRunning():
            return
        self.refresh_link.setText("Refreshing…")
        self.list_thread = ServerListThread(self)
        self.list_thread.done.connect(self.on_servers_refreshed)
        self.list_thread.start()

    def on_servers_refreshed(self, result):
        self.refresh_link.setText("Refresh list")
        if isinstance(result, Exception):
            self.client_log.append_line(f"Could not refresh the server list: {result}", Colors.RED)
            return
        self.load_servers(result)
        self.client_log.append_line(f"Server list updated: {len(result['servers'])} servers.", Colors.GREEN)

    # ---- client run
    def test_settings(self):
        host = self.host_input.text().strip()
        ports = iperf_servers.parse_ports(self.port_input.text())
        direction = selected_key(self.direction_group) or "both"
        streams = int(self.streams_combo.currentText())
        duration = int(self.duration_combo.currentText().split()[0])
        return host, ports, direction, streams, duration

    def update_command(self, *_):
        host, ports, direction, streams, duration = self.test_settings()
        if direction == "both":
            text = (iperf_command(host, ports[0], "download", streams, duration) + "\n"
                    + iperf_command(host, ports[0], "upload", streams, duration))
        else:
            text = iperf_command(host, ports[0], direction, streams, duration)
        self.command_text = text
        # Non-breaking hyphens keep options like -p 30001 on one line when the label wraps
        self.command_label.setText(text.replace("-", "\u2011"))

    def start_client(self):
        if self.client_running:
            return
        host, ports, direction, streams, duration = self.test_settings()
        if not host:
            self.host_input.set_error(True)
            return
        self.settings.setValue("host", host)
        self.settings.setValue("ports", self.port_input.text().strip())
        directions = ["download", "upload"] if direction == "both" else [direction]
        self.client_running = True
        self.update_running()
        self.run_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.header.set_actions()
        self.samples = {"download": [], "upload": []}
        self.client_log.clear()
        self.live_chart.reset()
        self.gauge.set_value(None, Colors.BLUE, "", "Mbps")
        self.client_views.setCurrentWidget(self.live_view)
        self.client_thread = ClientThread(host, ports, directions, streams, duration, self)
        self.client_thread.phase.connect(self.on_phase)
        self.client_thread.interval.connect(self.on_interval)
        self.client_thread.log.connect(self.client_log.append_line)
        self.client_thread.done.connect(self.on_client_done)
        self.client_thread.start()

    def on_phase(self, direction, port):
        color = Colors.SERIES_DOWN if direction == "download" else Colors.SERIES_UP
        self.samples[direction] = []
        self.live_chart.reset(color)
        self.live_title.setText(f"{direction.upper()} · {self.host_input.text().strip()}:{port}")
        self.gauge.set_value(None, color, direction.capitalize(), "Mbps ↓" if direction == "download" else "Mbps ↑")

    def on_interval(self, direction, seconds, value):
        self.samples[direction].append((seconds, value))
        self.live_chart.add(seconds, value)
        color = Colors.SERIES_DOWN if direction == "download" else Colors.SERIES_UP
        self.gauge.set_value(value, color)

    def stop_client(self):
        if self.client_thread and self.client_thread.isRunning():
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("Stopping…")
            self.client_thread.stop()

    def on_client_done(self, results):
        self.client_running = False
        self.update_running()
        self.run_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("Stop")
        results['samples'] = self.samples
        results['completed'] = datetime.now().isoformat(timespec='seconds')
        self.show_client_results(results)
        tests = results['tests']
        ok = {d: r for d, r in tests.items() if not r.get('error')}
        if ok:
            parts = [f"{'↓' if d == 'download' else '↑'} {(r.get('receiver_mbps') or r.get('sender_mbps') or 0):.0f}"
                     for d, r in ok.items()]
            recent_store().add('iperf', results['host'], " · ".join(parts) + " Mbps", results)

    def show_client_results(self, results):
        self.last_results = results
        tests = results.get('tests', {})
        self.download_card.set_result(tests.get('download'))
        self.upload_card.set_result(tests.get('upload'))
        samples = results.get('samples', {})
        self.download_chart.set_samples(samples.get('download', []))
        self.upload_chart.set_samples(samples.get('upload', []))
        for direction, result in tests.items():
            if not result.get('error'):
                self.client_log.append_line(
                    f"{direction.capitalize()}: receiver {result.get('receiver_mbps') or 0:.1f} Mbps, "
                    f"sender {result.get('sender_mbps') or 0:.1f} Mbps ({result.get('parallel')} streams, "
                    f"{result.get('duration')} s)", Colors.GREEN)
        self.client_views.setCurrentWidget(self.done_view)
        self.header.set_actions(self.export_btn)

    def handle_request(self, payload):
        if payload.get('open') and not self.client_running:
            entry = recent_store().get(payload['open'])
            if entry:
                self.tab_group.button(0).setChecked(True)
                self.stack.setCurrentIndex(0)
                self.host_input.setText(entry['target'])
                self.client_log.clear()
                self.show_client_results(entry.get('data', {}))

    def export_results(self):
        results = self.last_results or {}
        lines = [f"iPerf3 test against {results.get('host', '')}", f"Completed: {results.get('completed', '')}",
                 f"Streams: {results.get('streams')}  Duration: {results.get('duration')} s", ""]
        for direction, result in results.get('tests', {}).items():
            lines.append(f"[{direction}] port {result.get('port')}")
            if result.get('error'):
                lines.append(f"  Error: {result['error']}")
                continue
            lines.append(f"  Receiver: {result.get('receiver_mbps')} Mbps   Sender: {result.get('sender_mbps')} Mbps")
            lines.append(f"  Bytes received: {result.get('received_bytes')}   Bytes sent: {result.get('sent_bytes')}")
            for sample in result.get('intervals', []):
                lines.append(f"  {sample['t']:>6.1f} s  {sample['mbps']:>9.1f} Mbps")
        lines += ["", "Log:", self.client_log.plain_text()]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.save_text("Save Log File", f"iperf_results_{timestamp}.txt", "\n".join(lines) + "\n")

    # ================================================================ server
    def build_server(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        control = Card(margins=(14, 12, 14, 12))
        self.server_port = QSpinBox()
        self.server_port.setRange(1, 65535)
        self.server_port.setValue(DEFAULT_PORT)
        self.server_port.setFont(mono_font(12.5))
        self.server_port.setFixedSize(100, 32)
        self.server_port.setButtonSymbols(QSpinBox.NoButtons)
        self.server_port.valueChanged.connect(self.update_connect_help)
        self.server_status_dot = StatusDot(Colors.TEXT_FAINT, 8)
        self.server_pulse = PulseDot(Colors.GREEN, 8)
        self.server_pulse.setVisible(False)
        self.server_status = Label("Server is stopped", 12.5, 500, Colors.TEXT_MUTED)
        self.server_btn = button("Start server", "primary", 32)
        self.server_btn.clicked.connect(self.toggle_server)
        control.body.addLayout(hbox(Label("Listen on TCP port", 12, color=Colors.TEXT_MUTED), self.server_port, 14,
                                    self.server_status_dot, self.server_pulse, self.server_status, "stretch",
                                    self.server_btn, spacing=8))
        layout.addWidget(control)

        row = QHBoxLayout()
        row.setSpacing(12)
        help_card = Card(margins=(16, 12, 16, 12), spacing=8)
        help_card.setFixedWidth(470)
        help_card.body.addWidget(section_label("Connect from another device"))
        self.connect_rows = QVBoxLayout()
        self.connect_rows.setSpacing(6)
        help_card.body.addLayout(self.connect_rows)
        note = Label("Run one of these commands on the other device (iperf3 or this app). Without -R the other "
                     "device uploads to this one; with -R this computer sends. If nothing connects, allow the "
                     "port in your firewall, e.g. sudo firewall-cmd --add-port=5201/tcp", 11.5,
                     color=Colors.TEXT_MUTED)
        note.setWordWrap(True)
        help_card.body.addWidget(note)
        help_card.body.addStretch(1)
        row.addWidget(help_card)

        live_card = Card(margins=(16, 12, 16, 10))
        self.server_live_title = section_label("Live throughput")
        live_card.body.addWidget(self.server_live_title)
        self.server_chart = ThroughputChart(Colors.SERIES_DOWN)
        live_card.body.addWidget(self.server_chart, 1)
        row.addWidget(live_card, 1)
        layout.addLayout(row, 1)

        self.session_table = make_table(["Time", "Client", "Direction", "Streams", "Mbps"], stretch_column=2)
        for column, width in ((0, 100), (1, 220), (3, 90), (4, 120)):
            self.session_table.horizontalHeader().resizeSection(column, width)
        self.session_table.setFixedHeight(150)
        layout.addWidget(self.session_table)
        self.server_log = LogPane("Server log")
        self.server_log.setFixedHeight(130)
        layout.addWidget(self.server_log)
        self.update_connect_help()
        return page

    def local_addresses(self):
        addresses = []
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith(("127.", "169.254")):
                    addresses.append((name, addr.address))
        return addresses

    def update_connect_help(self, *_):
        clear_layout(self.connect_rows)
        port = self.server_port.value()
        port_part = f" -p {port}" if port != DEFAULT_PORT else ""
        addresses = self.local_addresses() or [("", "<this computer's IP>")]
        for name, address in addresses[:3]:
            for suffix in ("", " -R"):
                command = f"iperf3 -c {address}{port_part}{suffix}"
                label = Label(command, 12, color=Colors.TEXT_STRONG, mono=True)
                label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                copy = link_button("Copy")
                copy.clicked.connect(lambda _=False, c=command: QApplication.clipboard().setText(c))
                self.connect_rows.addLayout(hbox(label, "stretch", Label(name, 11, color=Colors.TEXT_MUTED,
                                                                         mono=True), copy, spacing=8))

    def toggle_server(self):
        if self.server_running:
            self.server_btn.setEnabled(False)
            self.server_btn.setText("Stopping…")
            self.server_thread.stop()
            return
        self.server_thread = ServerThread(self.server_port.value(), self)
        self.server_thread.event.connect(self.on_server_event)
        self.server_running = True
        self.server_port.setEnabled(False)
        self.server_btn.setText("Stop server")
        set_prop(self.server_btn, "variant", "stop")
        self.update_running()
        self.server_thread.start()

    def on_server_event(self, kind, data):
        if kind == 'listening':
            self.server_status.setText(f"Listening on port {data['port']} · waiting for a client")
            self.server_status.set_color(Colors.GREEN)
            self.server_status_dot.setVisible(False)
            self.server_pulse.setVisible(True)
            self.server_log.append_line(f"Server listening on TCP port {data['port']}", Colors.GREEN)
        elif kind == 'client':
            direction = "this computer sends (-R)" if data['reverse'] else "client sends"
            self.server_status.setText(f"Testing with {data['address']}")
            self.server_chart.reset(Colors.SERIES_DOWN if data['reverse'] else Colors.SERIES_UP)
            self.server_live_title.setText(f"LIVE · {data['address']} · {direction}")
            self.server_log.append_line(f"Accepted {data['address']}: {data['parallel']} stream(s), "
                                        f"{data['duration']:.0f} s, {direction}. Client: {data['version']}")
        elif kind == 'interval':
            self.server_chart.add(data['t'], data['mbps'])
        elif kind == 'result':
            self.session_table.insertRow(0)
            values = (datetime.now().strftime("%H:%M:%S"), data['address'], data['direction'],
                      str(data['parallel']), f"{data['local_mbps']:.1f}")
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFont(mono_font(12) if column != 2 else ui_font(12.5))
                item.setForeground(QColor(Colors.TEXT_STRONG if column == 4 else Colors.TEXT))
                self.session_table.setItem(0, column, item)
            self.server_status.setText(f"Listening on port {self.server_port.value()} · waiting for a client")
            self.server_log.append_line(f"Finished with {data['address']}: {data['local_mbps']:.1f} Mbps over "
                                        f"{data['seconds']:.1f} s", Colors.GREEN)
        elif kind == 'error':
            self.server_log.append_line(str(data), Colors.RED)
            if not self.server_thread or not self.server_thread.server.listener:
                self.server_status.setText(str(data))
                self.server_status.set_color(Colors.RED)
        elif kind == 'stopped':
            self.server_running = False
            self.update_running()
            self.server_port.setEnabled(True)
            self.server_btn.setEnabled(True)
            self.server_btn.setText("Start server")
            set_prop(self.server_btn, "variant", "primary")
            self.server_pulse.setVisible(False)
            self.server_status_dot.setVisible(True)
            if "Could not" not in self.server_status.text():
                self.server_status.setText("Server is stopped")
                self.server_status.set_color(Colors.TEXT_MUTED)
            self.server_log.append_line("Server stopped.", Colors.TEXT_MUTED)

    # ================================================================ shared
    def update_running(self):
        self.set_running(self.client_running or self.server_running)

    def cleanup(self):
        for thread in (self.client_thread, self.server_thread):
            if thread and thread.isRunning():
                thread.stop()
                thread.wait(8000)
        if self.list_thread and self.list_thread.isRunning():
            self.list_thread.wait(5000)
