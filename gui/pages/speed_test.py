"""Speed test: gauge and live throughput while running, hero numbers and charts afterwards."""
from datetime import datetime

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QWidget, QFrame, QHBoxLayout, QVBoxLayout, QStackedWidget

from gui.pages.base import Page
from gui.recent import recent_store
from gui.styles.modern_theme import Colors
from gui.pages.diagnose import PingThread
from gui.widgets.charts import LatencyChart, SpeedGauge, ThroughputChart
from gui.widgets.common import (Card, Label, EmptyPane, ErrorCard, StatStrip, section_label, button, hbox,
                                set_prop, relative_time)
from network.detector import NetworkDetector
from network.speed_test import SpeedTester

LATENCY_HOST = "8.8.8.8"
LATENCY_COUNT = 10
STEPS = [("server", "Server"), ("ping", "Ping"), ("download", "Download"), ("upload", "Upload")]


class SpeedTestThread(QThread):
    progress_update = pyqtSignal(int, str)
    info = pyqtSignal(str, object)
    test_complete = pyqtSignal(dict)

    def __init__(self, test_type, host=None, parent=None):
        super().__init__(parent)
        self.test_type = test_type
        self.host = host
        self.speed_tester = SpeedTester()

    def run(self):
        if self.test_type == "full":
            results = self.speed_tester.perform_speed_test(progress_callback=self.progress_update.emit,
                                                           info_callback=self.info.emit)
            if results.get('error'):
                results['checks'] = connectivity_checks()
            self.test_complete.emit(results)

    def stop(self):
        self.speed_tester.stop_test()


def connectivity_checks():
    """Gateway and internet reachability for the error card."""
    detector = NetworkDetector()
    checks = []
    gateways = [g for g in detector.get_default_gateway() if g != 'N/A']
    for label, host in ([("Gateway", gateways[0])] if gateways else []) + [("Internet", "8.8.8.8")]:
        ms = detector._ping_time(host)
        checks.append((f"{label} {host}", f"reachable · {ms:.1f} ms" if ms is not None else "no reply",
                       ms is not None))
    return checks


class StepCell(QFrame):
    """One step of the running strip: status line and a mono value."""

    def __init__(self, title, first=False, parent=None):
        super().__init__(parent)
        self.title = title
        self.setProperty("cell", "true")
        self.setProperty("first", "true" if first else "false")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(3)
        self.status = Label("", 11.5)
        self.value = Label("", 12.5, color=Colors.TEXT_STRONG, mono=True)
        layout.addWidget(self.status)
        layout.addWidget(self.value)
        self.set_state("pending")

    def set_state(self, state, value=None, color=Colors.GREEN, percent=None):
        if state == "done":
            self.status.setText(f"✓ {self.title}")
            self.status.set_color(color)
        elif state == "active":
            suffix = f" · {percent}%" if percent is not None else ""
            self.status.setText(f"● {self.title}{suffix}")
            self.status.set_color(Colors.BLUE)
        else:
            self.status.setText(f"○ {self.title}")
            self.status.set_color(Colors.TEXT_MUTED)
        if value is not None:
            self.value.setText(value)
            self.value.set_color(Colors.TEXT_STRONG)
        elif state == "pending":
            self.value.setText("waiting")
            self.value.set_color(Colors.TEXT_MUTED)
        set_prop(self, "active", "true" if state == "active" else "false")


class HeroCard(Card):
    def __init__(self, title, color, unit):
        super().__init__(margins=(18, 14, 18, 14))
        self.setStyleSheet(f"QFrame[card=\"card\"] {{ border-top: 3px solid {color}; }}")
        self.value = Label("—", 34, 400, Colors.TEXT_STRONG, mono=True)
        self.unit = Label(unit, 12.5, color=Colors.TEXT_MUTED)
        self.body.addLayout(hbox(section_label(title, color, 11), "stretch", self.value, self.unit, spacing=8))

    def set_value(self, value):
        self.value.setText("—" if value is None else f"{value:.1f}")
        self.value.set_color(Colors.TEXT_STRONG if value is not None else Colors.TEXT_FAINT)


class ChartCard(Card):
    def __init__(self, title, color):
        super().__init__(margins=(16, 14, 16, 12))
        self.body.addWidget(section_label(title))
        self.chart = ThroughputChart(color, footer=False)
        self.body.addWidget(self.chart, 1)
        self.footer = Label("", 11, color=Colors.TEXT_MUTED, mono=True)
        self.body.addWidget(self.footer)

    def set_samples(self, samples, final):
        self.chart.set_samples(samples)
        peak = max((m for _t, m in samples), default=0)
        # Peak is the interface rate (0.5 s samples); the result is speedtest.net's own measurement
        self.footer.setText(f"interface peak {peak:.1f} · result {final:.1f} Mbps" if samples else
                            f"result {final:.1f} Mbps" if final else "")


class SpeedTestPage(Page):
    def __init__(self):
        super().__init__("Speed test", "Best server is picked automatically")
        self.test_thread = None
        self.stopped = False
        self.result = {}
        self.samples = {'download': [], 'upload': []}
        self.log = []

        self.latency_btn = button("Latency test", "secondary")
        self.latency_btn.clicked.connect(self.start_latency_test)
        self.export_btn = button("Export", "secondary")
        self.export_btn.clicked.connect(self.export_log)
        self.again_btn = button("Run again", "primary")
        self.again_btn.clicked.connect(self.run_again)
        self.full_btn = button("Speed test", "secondary")
        self.full_btn.clicked.connect(self.start_full_test)
        self.last_mode = "full"
        self.ping_thread = None
        self.stop_btn = button("Stop", "stop")
        self.stop_btn.clicked.connect(self.stop_test)

        # Start bar
        self.bar = Card(margins=(12, 12, 12, 12))
        self.bar_latency = button("Latency only", "secondary", 34)
        self.bar_latency.clicked.connect(self.start_latency_test)
        self.start_btn = button("Start speed test", "primary", 34)
        self.start_btn.clicked.connect(self.start_full_test)
        self.bar.body.addLayout(hbox(Label("Download, upload and ping · best server is picked automatically",
                                           12.5, color=Colors.TEXT_MUTED), "stretch", self.bar_latency,
                                     self.start_btn))
        self.body.addWidget(self.bar)

        self.views = QStackedWidget()
        self.body.addWidget(self.views, 1)

        self.empty = EmptyPane()
        self.views.addWidget(self.empty)

        # Running view
        running = QWidget()
        rl = QVBoxLayout(running)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(12)
        steps_card = Card(margins=(0, 0, 0, 0), spacing=0)
        steps_row = QHBoxLayout()
        steps_row.setSpacing(0)
        self.steps = {}
        for index, (key, title) in enumerate(STEPS):
            cell = StepCell(title, first=index == 0)
            steps_row.addWidget(cell, 1)
            self.steps[key] = cell
        steps_card.body.addLayout(steps_row)
        rl.addWidget(steps_card)
        panes = QHBoxLayout()
        panes.setSpacing(12)
        gauge_card = Card(margins=(10, 10, 10, 10))
        gauge_card.setFixedWidth(320)
        self.gauge = SpeedGauge()
        gauge_card.body.addWidget(self.gauge, 1)
        panes.addWidget(gauge_card)
        live_card = Card(margins=(16, 14, 16, 12))
        live_card.body.addWidget(section_label("Throughput"))
        self.live_chart = ThroughputChart(Colors.SERIES_DOWN)
        live_card.body.addWidget(self.live_chart, 1)
        panes.addWidget(live_card, 1)
        rl.addLayout(panes, 1)
        self.views.addWidget(running)
        self.running_view = running

        # Results view
        results = QWidget()
        sl = QVBoxLayout(results)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(12)
        heroes = QHBoxLayout()
        heroes.setSpacing(12)
        self.hero_down = HeroCard("Download", Colors.SERIES_DOWN, "Mbps")
        self.hero_up = HeroCard("Upload", Colors.SERIES_UP, "Mbps")
        self.hero_ping = HeroCard("Ping", Colors.YELLOW, "ms")
        for hero in (self.hero_down, self.hero_up, self.hero_ping):
            heroes.addWidget(hero, 1)
        sl.addLayout(heroes)
        self.charts_row = QWidget()
        charts = QHBoxLayout(self.charts_row)
        charts.setContentsMargins(0, 0, 0, 0)
        charts.setSpacing(12)
        self.down_chart = ChartCard("Download throughput", Colors.SERIES_DOWN)
        self.up_chart = ChartCard("Upload throughput", Colors.SERIES_UP)
        charts.addWidget(self.down_chart, 1)
        charts.addWidget(self.up_chart, 1)
        sl.addWidget(self.charts_row, 1)
        self.server_row = Card(margins=(0, 0, 0, 0), spacing=0)
        server_layout = QHBoxLayout()
        server_layout.setSpacing(0)
        self.server_values = {}
        for index, (key, title) in enumerate((("name", "Server"), ("sponsor", "Sponsor"),
                                             ("country", "Location"), ("distance", "Distance"))):
            cell = QFrame()
            cell.setProperty("cell", "true")
            cell.setProperty("first", "true" if index == 0 else "false")
            value = Label("—", 12.5, color=Colors.TEXT_STRONG, mono=key == "distance")
            cell.setLayout(hbox(Label(title, 12.5, color=Colors.TEXT_MUTED), "stretch", value,
                                margins=(16, 9, 16, 9)))
            server_layout.addWidget(cell, 1)
            self.server_values[key] = value
        self.server_row.body.addLayout(server_layout)
        sl.addWidget(self.server_row)
        self.views.addWidget(results)
        self.results_view = results

        # Latency view (live and results)
        latency = QWidget()
        ll = QVBoxLayout(latency)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)
        latency_card = Card(margins=(0, 0, 0, 12), spacing=0)
        self.latency_strip = StatStrip([("sent", "Sent"), ("received", "Received"), ("lost", "Lost"),
                                        ("min", "Min"), ("avg", "Avg"), ("max", "Max")])
        self.latency_strip.set_embedded(True)
        latency_card.body.addWidget(self.latency_strip)
        self.latency_chart = LatencyChart()
        chart_holder = QWidget()
        chart_holder.setLayout(hbox(self.latency_chart, margins=(10, 12, 14, 4)))
        latency_card.body.addWidget(chart_holder, 1)
        self.latency_legend = Label("", 11.5, color=Colors.TEXT_MUTED)
        self.latency_legend.setContentsMargins(46, 0, 14, 0)
        latency_card.body.addWidget(self.latency_legend)
        ll.addWidget(latency_card, 1)
        self.views.addWidget(latency)
        self.latency_view = latency

        self.error_card = ErrorCard()
        self.views.addWidget(self.error_card)

        recent_store().changed.connect(self.update_empty)
        self.show_idle()

    # ------------------------------------------------------------ states
    def update_empty(self):
        entry = recent_store().latest('speed')
        if entry:
            data = entry.get('data', {})
            self.empty.set_text(f"Last result · {relative_time(entry['time'])}",
                                f"{data.get('download_speed', 0):.1f} Mbps down · "
                                f"{data.get('upload_speed', 0):.1f} Mbps up · {data.get('ping', 0):.1f} ms ping · "
                                f"{data.get('server', {}).get('name', '')}")
        else:
            self.empty.set_text("No speed test yet", "Download, upload and ping · best server is picked "
                                                     "automatically")

    def show_idle(self):
        self.bar.setVisible(True)
        self.header.set_subtitle("Best server is picked automatically")
        self.header.set_actions()
        self.update_empty()
        self.views.setCurrentWidget(self.empty)

    def handle_request(self, payload):
        if payload.get('action') == 'run':
            self.start_full_test()
        elif payload.get('open') and not self.running:
            entry = recent_store().get(payload['open'])
            if entry:
                data = entry.get('data', {})
                self.result = data
                self.samples = data.get('samples', {'download': [], 'upload': []})
                self.show_results(datetime.fromisoformat(entry['time']))

    def set_buttons_enabled(self, enabled):
        for btn in (self.start_btn, self.bar_latency, self.latency_btn, self.again_btn, self.full_btn):
            btn.setEnabled(enabled)

    # ------------------------------------------------------------ full test
    def run_again(self):
        if self.last_mode == "latency":
            self.start_latency_test()
        else:
            self.start_full_test()

    def start_full_test(self):
        if self.running:
            return
        self.last_mode = "full"
        self.stopped = False
        self.result = {}
        self.samples = {'download': [], 'upload': []}
        self.log = ["Starting full speed test..."]
        self.set_running(True)
        self.set_buttons_enabled(False)
        self.bar.setVisible(False)
        self.header.set_subtitle("Finding the best server…")
        self.header.set_actions(self.stop_btn)
        for key, cell in self.steps.items():
            cell.set_state("pending")
        self.steps["server"].set_state("active")
        self.gauge.set_value(None, Colors.BLUE, "", "Mbps")
        self.live_chart.reset(Colors.SERIES_DOWN)
        self.views.setCurrentWidget(self.running_view)

        self.test_thread = SpeedTestThread("full", parent=self)
        self.test_thread.progress_update.connect(self.on_progress)
        self.test_thread.info.connect(self.on_info)
        self.test_thread.test_complete.connect(self.on_test_complete)
        self.test_thread.start()

    def on_progress(self, progress, message):
        self.log.append(message)
        if "download" in message.lower():
            self.steps["download"].set_state("active", percent=max(0, min(100, (progress - 40) * 100 // 30)))
        elif "upload" in message.lower():
            self.steps["upload"].set_state("active", percent=max(0, min(100, (progress - 70) * 100 // 25)))
        elif "ping" in message.lower():
            self.steps["ping"].set_state("active")

    def on_info(self, kind, value):
        if kind == "server":
            self.result['server'] = value
            self.steps["server"].set_state("done", value.get('name', ''))
            self.header.set_subtitle(f"{value.get('name', '')} · {value.get('sponsor', '')} · "
                                     f"{value.get('distance', 0):.1f} km")
            self.log.append(f"Server: {value.get('name')} ({value.get('sponsor')})")
        elif kind == "ping":
            self.steps["ping"].set_state("done", f"{value:.1f} ms", Colors.YELLOW)
            self.steps["download"].set_state("active", percent=0)
            self.gauge.set_value(None, Colors.SERIES_DOWN, "Download", "Mbps ↓")
        elif kind == "sample":
            phase, seconds, mbps = value
            self.samples[phase].append((seconds, mbps))
            color = Colors.SERIES_DOWN if phase == "download" else Colors.SERIES_UP
            if self.live_chart.color != color:
                self.live_chart.reset(color)
            self.live_chart.add(seconds, mbps)
            self.gauge.set_value(mbps, color, phase.capitalize(), "Mbps ↓" if phase == "download" else "Mbps ↑")
            self.steps[phase].value.setText(f"{mbps:.1f} Mbps")
            self.steps[phase].value.set_color(Colors.TEXT_STRONG)
        elif kind == "download":
            self.steps["download"].set_state("done", f"{value:.1f} Mbps", Colors.SERIES_DOWN)
            self.steps["upload"].set_state("active", percent=0)
            self.gauge.set_value(None, Colors.SERIES_UP, "Upload", "Mbps ↑")
        elif kind == "upload":
            self.steps["upload"].set_state("done", f"{value:.1f} Mbps", Colors.SERIES_UP)

    def stop_test(self):
        if self.ping_thread and self.ping_thread.isRunning():
            self.ping_thread.stop()
            return
        if self.test_thread and self.test_thread.isRunning():
            self.stopped = True
            self.stop_btn.setEnabled(False)
            self.stop_btn.setText("Stopping…")
            self.test_thread.stop()

    def on_test_complete(self, result):
        self.set_running(False)
        self.set_buttons_enabled(True)
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("Stop")
        self.bar.setVisible(True)
        if self.stopped:
            self.log.append("Test stopped by user.")
            self.show_idle()
            return
        if result.get('error'):
            self.show_error(result)
            return
        self.result = result
        self.result['samples'] = self.samples
        completed = datetime.now()
        self.show_results(completed)
        down, up = result.get('download_speed', 0), result.get('upload_speed', 0)
        recent_store().add('speed', result.get('server', {}).get('name', 'speedtest.net'),
                           f"{down:.1f} ↓ · {up:.1f} ↑ Mbps", result)

    def show_results(self, completed):
        result = self.result
        self.bar.setVisible(False)
        self.header.set_subtitle(f"Completed {completed:%H:%M}")
        self.again_btn.setText("Run speed test again")
        self.header.set_actions(self.latency_btn, self.export_btn, self.again_btn)
        self.hero_down.set_value(result.get('download_speed'))
        self.hero_up.set_value(result.get('upload_speed'))
        self.hero_ping.set_value(result.get('ping'))
        samples = result.get('samples', self.samples)
        self.down_chart.set_samples(samples.get('download', []), result.get('download_speed', 0))
        self.up_chart.set_samples(samples.get('upload', []), result.get('upload_speed', 0))
        server = result.get('server', {})
        for key, label in self.server_values.items():
            value = server.get(key)
            label.setText("—" if value in (None, "") else f"{value:.1f} km" if key == "distance" else str(value))
        self.charts_row.setVisible(True)
        self.server_row.setVisible(True)
        self.views.setCurrentWidget(self.results_view)

    def show_error(self, result):
        retry = button("Retry", "primary", 32)
        retry.clicked.connect(self.start_full_test)
        latency = button("Latency test only", "secondary", 32)
        latency.clicked.connect(self.start_latency_test)
        checks = result.get('checks') or []
        online = checks and all(ok for _text, _value, ok in checks)
        help_text = ("The speed test servers did not respond. Your connection looks fine; a firewall or proxy may "
                     "be blocking speedtest.net." if online else
                     "Your connection is not reaching the internet. Run the troubleshooter to find the failing link.")
        self.error_card.show_error("Speed test failed", result['error'], checks, help_text, [retry, latency])
        self.header.set_subtitle("Best server is picked automatically")
        self.header.set_actions()
        self.log.append(f"Error: {result['error']}")
        self.views.setCurrentWidget(self.error_card)

    # ------------------------------------------------------------ latency only
    def start_latency_test(self):
        if self.running:
            return
        self.last_mode = "latency"
        self.latency_replies = []
        self.log = [f"Starting latency test to {LATENCY_HOST} ({LATENCY_COUNT} pings)..."]
        self.set_running(True)
        self.set_buttons_enabled(False)
        self.bar.setVisible(False)
        self.header.set_subtitle_parts(LATENCY_HOST, f"latency · {LATENCY_COUNT} pings")
        self.header.set_actions(self.stop_btn)
        self.latency_chart.reset(LATENCY_COUNT)
        self.latency_strip.reset()
        self.latency_legend.setText("ms per reply · live")
        self.views.setCurrentWidget(self.latency_view)
        self.ping_thread = PingThread(LATENCY_HOST, LATENCY_COUNT, self)
        self.ping_thread.reply.connect(self.on_latency_reply)
        self.ping_thread.result_ready.connect(self.on_latency_complete)
        self.ping_thread.start()

    def on_latency_reply(self, response):
        seq, ms = response['sequence'], response['time']
        self.latency_replies.append((seq, ms))
        self.latency_chart.add_reply(seq, ms)
        self.log.append(f"Reply from {LATENCY_HOST}: seq={seq} time={ms:.1f}ms" if ms is not None
                        else f"Request timeout for {LATENCY_HOST}: seq={seq}")
        self.update_latency_strip()

    def update_latency_strip(self):
        times = [ms for _seq, ms in self.latency_replies if ms is not None]
        sent = len(self.latency_replies)
        lost = sent - len(times)
        self.latency_strip.set("sent", sent)
        self.latency_strip.set("received", len(times))
        self.latency_strip.set("lost", f"{lost} · {lost * 100 / sent:.0f}%" if lost else "0",
                               Colors.YELLOW if lost else Colors.TEXT_STRONG)
        for key, value in (("min", min(times, default=None)), ("max", max(times, default=None)),
                           ("avg", sum(times) / len(times) if times else None)):
            self.latency_strip.set(key, f"{value:.1f} ms" if value is not None else None)
        return times

    def on_latency_complete(self, result):
        self.set_running(False)
        self.set_buttons_enabled(True)
        self.bar.setVisible(True)
        if result.get('error'):
            self.show_error({'error': f"Latency test error: {result['error']}", 'checks': []})
            return
        times = self.update_latency_strip()
        stopped = result.get('stopped')
        if times:
            avg = sum(times) / len(times)
            self.latency_chart.set_avg(avg)
            lost = [seq for seq, ms in self.latency_replies if ms is None]
            legend = f"ms per reply   - - avg {avg:.1f}"
            if lost:
                legend += f"   ¦ seq {', '.join(map(str, lost[:5]))} lost"
            self.latency_legend.setText(legend)
            self.log += ["=" * 40, "LATENCY TEST RESULTS", "=" * 40, f"Host: {LATENCY_HOST}",
                         f"Average Latency: {avg:.2f} ms", f"Min Latency: {min(times):.2f} ms",
                         f"Max Latency: {max(times):.2f} ms",
                         f"Packet Loss: {len(lost) * 100 / len(self.latency_replies):.0f}%"]
        else:
            self.latency_legend.setText("No replies")
        if stopped:
            self.log.append("Test stopped by user.")
        self.bar.setVisible(False)
        state = "stopped" if stopped else "completed"
        self.header.set_subtitle_parts(LATENCY_HOST, f"latency · {state} {datetime.now():%H:%M}")
        self.again_btn.setText("Run latency test again")
        self.header.set_actions(self.full_btn, self.export_btn, self.again_btn)

    # ------------------------------------------------------------ export
    def export_log(self):
        lines = list(self.log)
        if self.result.get('download_speed') is not None and self.result.get('server'):
            server = self.result['server']
            lines += ["", "=" * 40, "SPEED TEST RESULTS", "=" * 40,
                      f"Download Speed: {self.result.get('download_speed')} Mbps",
                      f"Upload Speed: {self.result.get('upload_speed')} Mbps",
                      f"Ping: {self.result.get('ping')} ms",
                      f"Server: {server.get('name', 'Unknown')} ({server.get('sponsor', '')})",
                      f"Location: {server.get('country', '')}",
                      f"Distance: {server.get('distance', '')} km"]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.save_text("Save Log File", f"speed_test_results_{timestamp}.txt", "\n".join(lines) + "\n")

    def cleanup(self):
        if self.ping_thread and self.ping_thread.isRunning():
            self.ping_thread.stop()
            self.ping_thread.wait(5000)
        if self.test_thread and self.test_thread.isRunning():
            self.test_thread.stop()
            self.test_thread.wait(10000)
