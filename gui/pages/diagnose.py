"""Diagnose host: ping and trace route to one target in parallel."""
import socket
from datetime import datetime

from PyQt5.QtCore import Qt, QThread, QSettings, pyqtSignal
from PyQt5.QtWidgets import (QWidget, QFrame, QHBoxLayout, QVBoxLayout, QGridLayout, QStackedWidget,
                             QProgressBar, QCompleter, QScrollArea)

from gui.pages.base import Page
from gui.recent import recent_store
from gui.styles.modern_theme import Colors
from gui.widgets.charts import LatencyChart
from gui.widgets.common import (Card, Label, LineInput, ToggleChip, StatStrip, EmptyPane, ErrorCard,
                                section_label, button, link_button, hbox, clear_layout, relative_time, fmt_ms)
from gui.widgets.route import HopList
from network.detector import NetworkDetector
from network.ping import PingTester
from network.system_tools import SystemTools
from network.trace import TraceRoute

PING_COUNT = 20
MAX_HOPS = 15


class ResolveThread(QThread):
    """Resolve the target first; on failure collect the checks shown in the error card."""
    resolved = pyqtSignal(bool, str, list)   # ok, address or message, checks

    def __init__(self, host, flush_dns=False, parent=None):
        super().__init__(parent)
        self.host = host
        self.flush_dns = flush_dns

    def run(self):
        if self.flush_dns:
            SystemTools().flush_dns()
        try:
            address = socket.getaddrinfo(self.host, None, socket.AF_INET)[0][4][0]
            self.resolved.emit(True, address, [])
            return
        except (OSError, UnicodeError):
            pass
        detector = NetworkDetector()
        checks = []
        gateways = [g for g in detector.get_default_gateway() if g != 'N/A']
        if gateways:
            ms = detector._ping_time(gateways[0])
            checks.append((f"Gateway {gateways[0]}", f"reachable · {ms:.1f} ms" if ms is not None else "no reply",
                           ms is not None))
        dns_servers = [d for d in detector.get_dns_servers() if d != 'N/A']
        dns_ok = detector.test_dns_resolution()
        label = f"DNS {dns_servers[0]}" if dns_servers else "DNS"
        checks.append((label, "answering" if dns_ok else "no answer", dns_ok))
        self.resolved.emit(False, "dns" if not dns_ok else "name", checks)


class PingThread(QThread):
    reply = pyqtSignal(dict)
    result_ready = pyqtSignal(dict)

    def __init__(self, host, count, parent=None):
        super().__init__(parent)
        self.host, self.count = host, count
        self.tester = PingTester()

    def run(self):
        try:
            result = self.tester.ping_host(self.host, self.count, reply_callback=self.reply.emit)
        except Exception as e:
            result = {"error": str(e)}
        self.result_ready.emit(result)

    def stop(self):
        self.tester.stop()


class TraceThread(QThread):
    hop = pyqtSignal(dict)

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.tracer = TraceRoute()

    def run(self):
        self.tracer.run_trace(self.host, self.hop.emit, max_hops=MAX_HOPS)

    def stop(self):
        self.tracer.stop()


class ClickableCard(Card):
    clicked = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class ProgressBlock(QWidget):
    """'Ping · reply 7 / 20   35%' above a thin progress bar."""

    def __init__(self, tone="blue", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        self.label = Label("", 12, color=Colors.TEXT)
        self.right = Label("", 11.5, color=Colors.TEXT_MUTED, mono=True)
        layout.addLayout(hbox(self.label, "stretch", self.right))
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        if tone == "purple":
            self.bar.setProperty("tone", "purple")
        layout.addWidget(self.bar)

    def set(self, text, right, value, maximum):
        self.label.setText(text)
        self.right.setText(right)
        self.bar.setRange(0, maximum)
        self.bar.setValue(value)


class DiagnosePage(Page):
    def __init__(self):
        super().__init__("Diagnose host", "Latency and route to one target")
        self.settings = QSettings("NetworkTools", "PingTest")
        self.history = self.settings.value("host_history", [], type=list)
        self.ping_thread = None
        self.trace_thread = None
        self.resolve_thread = None
        self.reset_data()

        self.export_btn = button("Export", "secondary")
        self.export_btn.clicked.connect(self.export_results)
        self.again_btn = button("Run again", "primary")
        self.again_btn.clicked.connect(self.start)

        # Host bar
        bar = Card(margins=(12, 12, 12, 12))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.host_input = LineInput("hostname or IP, e.g. 8.8.8.8")
        self.host_input.returnPressed.connect(self.start)
        self.host_input.setCompleter(QCompleter(self.history, self))
        self.ping_chip = ToggleChip("Ping", f"×{PING_COUNT}")
        self.trace_chip = ToggleChip("Trace", f"≤{MAX_HOPS} hops")
        self.ping_progress = ProgressBlock("blue")
        self.trace_progress = ProgressBlock("purple")
        self.run_btn = button("Run", "primary", 36, width=64)
        self.run_btn.clicked.connect(self.start)
        self.stop_btn = button("Stop", "stop", 36, width=66)
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.host_input, 1)
        for widget in (self.ping_chip, self.trace_chip):
            row.addWidget(widget)
        row.addWidget(self.ping_progress, 1)
        row.addWidget(self.trace_progress, 1)
        row.addWidget(self.run_btn)
        row.addWidget(self.stop_btn)
        bar.body.addLayout(row)
        self.body.addWidget(bar)

        self.views = QStackedWidget()
        self.body.addWidget(self.views, 1)

        # Idle view
        idle = QWidget()
        idle_layout = QVBoxLayout(idle)
        idle_layout.setContentsMargins(0, 2, 0, 0)
        idle_layout.setSpacing(12)
        self.recent_label = section_label("Recent targets")
        idle_layout.addWidget(self.recent_label)
        self.recent_grid = QGridLayout()
        self.recent_grid.setSpacing(10)
        idle_layout.addLayout(self.recent_grid)
        panes = QHBoxLayout()
        panes.setSpacing(12)
        panes.addWidget(EmptyPane("Latency", "Each reply is charted as it arrives"), 3)
        panes.addWidget(EmptyPane("Route", "Hops appear here during the trace"), 2)
        idle_layout.addLayout(panes, 1)
        self.views.addWidget(idle)
        self.idle_view = idle

        # Running / results view
        result = QWidget()
        result_layout = QVBoxLayout(result)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(12)
        self.results_strip = StatStrip([("sent", "Sent"), ("received", "Received"), ("lost", "Lost"),
                                        ("min", "Min"), ("avg", "Avg"), ("max", "Max"),
                                        ("hops", "Hops"), ("noreply", "No reply")])
        result_layout.addWidget(self.results_strip)
        panes = QHBoxLayout()
        panes.setSpacing(12)

        self.latency_card = Card(margins=(0, 0, 0, 12), spacing=0)
        self.live_strip = StatStrip([("sent", "Sent"), ("received", "Received"), ("lost", "Lost"),
                                     ("min", "Min"), ("avg", "Avg"), ("max", "Max")])
        self.live_strip.set_embedded(True)
        self.latency_card.body.addWidget(self.live_strip)
        self.chart = LatencyChart()
        chart_holder = QWidget()
        chart_holder.setLayout(hbox(self.chart, margins=(10, 12, 14, 4)))
        self.latency_card.body.addWidget(chart_holder, 1)
        self.legend = QHBoxLayout()
        self.legend.setContentsMargins(46, 0, 14, 0)
        self.legend.setSpacing(16)
        self.latency_card.body.addLayout(self.legend)
        panes.addWidget(self.latency_card, 1)

        self.route_card = Card(margins=(16, 12, 14, 12), spacing=8)
        self.route_card.setFixedWidth(400)
        self.route_title = section_label("Route")
        self.route_card.body.addWidget(self.route_title)
        self.hop_list = HopList()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setLayout(vbox_with(self.hop_list))
        scroll.setWidget(holder)
        self.route_card.body.addWidget(scroll, 1)
        self.route_note = Card("note", margins=(12, 10, 12, 10))
        self.route_note_text = Label("", 12, color=Colors.TEXT)
        self.route_note_text.setWordWrap(True)
        self.route_note.body.addWidget(self.route_note_text)
        self.route_card.body.addWidget(self.route_note)
        panes.addWidget(self.route_card)
        result_layout.addLayout(panes, 1)
        self.views.addWidget(result)
        self.result_view = result

        # Error view
        self.error_card = ErrorCard()
        self.views.addWidget(self.error_card)

        self.show_idle()
        recent_store().changed.connect(self.update_recent_targets)

    # ------------------------------------------------------------ state
    def reset_data(self):
        self.target = ""
        self.address = ""
        self.replies = []
        self.hops = []
        self.ping_result = None
        self.trace_error = None
        self.ping_done = True
        self.trace_done = True
        self.completed_at = None

    def set_bar_mode(self, running):
        self.host_input.setReadOnly(running)
        self.ping_chip.setVisible(not running)
        self.trace_chip.setVisible(not running)
        self.ping_progress.setVisible(running and self.ping_enabled)
        self.trace_progress.setVisible(running and self.trace_enabled)
        self.run_btn.setVisible(not running)
        self.stop_btn.setVisible(running)
        if running:
            self.host_input.setMaximumWidth(300)
        else:
            self.host_input.setMaximumWidth(16777215)

    def show_idle(self):
        self.ping_enabled = self.trace_enabled = True
        self.set_bar_mode(False)
        self.header.set_subtitle("Latency and route to one target")
        self.header.set_actions()
        self.update_recent_targets()
        self.views.setCurrentWidget(self.idle_view)

    def update_recent_targets(self):
        clear_layout(self.recent_grid)
        seen, entries = set(), []
        for entry in recent_store().items('diagnose'):
            if entry['target'] not in seen:
                seen.add(entry['target'])
                entries.append(entry)
        self.recent_label.setVisible(bool(entries))
        for column, entry in enumerate(entries[:4]):
            card = ClickableCard(margins=(14, 12, 14, 12), spacing=4)
            card.setMinimumHeight(84)
            card.body.addWidget(Label(entry['target'], 13, 500, Colors.TEXT_STRONG, mono=True))
            card.body.addWidget(Label(entry['summary'], 11, color=Colors.TEXT_MUTED, mono=True))
            card.body.addWidget(Label(relative_time(entry['time']), 11.5, color=Colors.TEXT_MUTED))
            card.clicked.connect(lambda t=entry['target']: self.run_target(t))
            self.recent_grid.addWidget(card, 0, column)
        for column in range(4):
            self.recent_grid.setColumnStretch(column, 1)

    def run_target(self, target):
        if self.running:
            return
        self.host_input.setText(target)
        self.start()

    def handle_request(self, payload):
        if payload.get('open'):
            entry = recent_store().get(payload['open'])
            if entry and not self.running:
                self.load_entry(entry)
        elif payload.get('target'):
            self.run_target(payload['target'])

    # ------------------------------------------------------------ run
    def start(self, flush_dns=False):
        if self.running:
            return
        host = self.host_input.text().strip()
        if not host:
            self.host_input.set_error(True)
            self.host_input.setFocus()
            return
        self.ping_enabled = self.ping_chip.isChecked()
        self.trace_enabled = self.trace_chip.isChecked()
        if not (self.ping_enabled or self.trace_enabled):
            self.ping_chip.check.setChecked(True)
            self.ping_enabled = True
        self.reset_data()
        self.target = host
        self.host_input.set_error(False)
        self.set_running(True)
        self.run_btn.setEnabled(False)
        self.run_btn.setText("…")
        self.resolve_thread = ResolveThread(host, flush_dns, self)
        self.resolve_thread.resolved.connect(self.on_resolved)
        self.resolve_thread.start()

    def on_resolved(self, ok, value, checks):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Run")
        if not ok:
            self.set_running(False)
            self.show_resolve_error(value, checks)
            return
        self.address = value
        self.save_history(self.target)

        self.set_bar_mode(True)
        self.header.set_subtitle(self.target, mono=True)
        self.header.set_actions()
        self.chart.reset(PING_COUNT)
        self.chart.show_lost = True
        self.hop_list.reset()
        self.live_strip.reset()
        self.live_strip.setVisible(True)
        self.results_strip.setVisible(False)
        self.latency_card.setVisible(self.ping_enabled)
        self.route_card.setVisible(self.trace_enabled)
        self.route_note.setVisible(False)
        self.route_title.setText("ROUTE")
        self.set_legend(live=True)
        self.views.setCurrentWidget(self.result_view)

        if self.ping_enabled:
            self.ping_done = False
            self.ping_progress.set(f"Ping · reply 0 / {PING_COUNT}", "0%", 0, PING_COUNT)
            self.ping_thread = PingThread(self.target, PING_COUNT, self)
            self.ping_thread.reply.connect(self.on_reply)
            self.ping_thread.result_ready.connect(self.on_ping_done)
            self.ping_thread.start()
        if self.trace_enabled:
            self.trace_done = False
            self.trace_progress.set("Trace · hop 1", f"≤{MAX_HOPS}", 0, MAX_HOPS)
            self.hop_list.set_probing(1)
            self.trace_thread = TraceThread(self.target, self)
            self.trace_thread.hop.connect(self.on_hop)
            self.trace_thread.finished.connect(self.on_trace_done)
            self.trace_thread.start()

    def on_reply(self, response):
        self.replies.append((response['sequence'], response['time']))
        self.chart.add_reply(response['sequence'], response['time'])
        n = len(self.replies)
        self.ping_progress.set(f"Ping · reply {n} / {PING_COUNT}", f"{n * 100 // PING_COUNT}%", n, PING_COUNT)
        self.update_stats(self.live_strip)

    def on_hop(self, hop):
        if 'error' in hop:
            self.trace_error = hop['error']
            return
        self.hops.append(hop)
        self.hop_list.add_hop(hop)
        number = hop['hop']
        if hop.get('destination') or number >= MAX_HOPS:
            self.hop_list.set_probing(None)
        else:
            self.hop_list.set_probing(number + 1)
        self.trace_progress.set(f"Trace · hop {min(number + 1, MAX_HOPS)}", f"≤{MAX_HOPS}", number, MAX_HOPS)

    def on_ping_done(self, result):
        self.ping_result = result
        self.ping_done = True
        self.maybe_finish()

    def on_trace_done(self):
        self.trace_done = True
        self.hop_list.set_probing(None)
        self.maybe_finish()

    def stop(self):
        for thread in (self.ping_thread, self.trace_thread):
            if thread and thread.isRunning():
                thread.stop()

    def maybe_finish(self):
        if not (self.ping_done and self.trace_done):
            return
        self.set_running(False)
        if not self.replies and not self.hops:
            if self.trace_error:
                self.show_trace_error()
            else:
                self.show_idle()
            return
        self.completed_at = datetime.now()
        self.show_results()
        self.store_result()

    # ------------------------------------------------------------ results
    def ping_stats(self):
        times = [ms for _seq, ms in self.replies if ms is not None]
        sent = len(self.replies)
        stats = {'sent': sent, 'received': len(times), 'lost': sent - len(times)}
        if times:
            stats.update(min=min(times), avg=sum(times) / len(times), max=max(times))
        return stats

    def update_stats(self, strip):
        stats = self.ping_stats()
        strip.set("sent", stats['sent'])
        strip.set("received", stats['received'])
        lost = stats['lost']
        loss_pct = lost * 100 / stats['sent'] if stats['sent'] else 0
        strip.set("lost", f"{lost} · {loss_pct:.0f}%" if lost else "0", Colors.YELLOW if lost else Colors.TEXT_STRONG)
        for key in ("min", "avg", "max"):
            strip.set(key, fmt_ms(stats.get(key)) if key in stats else None)

    def silent_hops(self):
        """Hops that timed out although a later hop replied."""
        last_ok = max((h['hop'] for h in self.hops if h['status'] == 'ok'), default=0)
        return [h['hop'] for h in self.hops if h['status'] == 'timeout' and h['hop'] < last_ok]

    def show_results(self):
        self.set_bar_mode(False)
        self.ping_chip.check.setChecked(self.ping_enabled)
        self.trace_chip.check.setChecked(self.trace_enabled)
        when = self.completed_at.strftime("%H:%M") if self.completed_at else ""
        self.header.set_subtitle_parts(self.target, f"completed {when}")
        self.header.set_actions(self.export_btn, self.again_btn)
        self.views.setCurrentWidget(self.result_view)
        self.latency_card.setVisible(self.ping_enabled)
        self.route_card.setVisible(self.trace_enabled)
        self.live_strip.setVisible(False)
        self.results_strip.setVisible(True)

        self.update_stats(self.results_strip)
        stats = self.ping_stats()
        if not self.ping_enabled:
            for key in ("sent", "received", "lost", "min", "avg", "max"):
                self.results_strip.set(key, None)
        self.chart.set_avg(stats.get('avg'))
        self.set_legend(live=False)

        silent = self.silent_hops()
        reached = any(h.get('destination') for h in self.hops)
        hop_count = max((h['hop'] for h in self.hops), default=0)
        if self.trace_enabled:
            self.results_strip.set("hops", hop_count if reached else (f"{hop_count}+" if hop_count else None))
            if silent:
                self.results_strip.set("noreply", "hop " + ", ".join(map(str, silent)), Colors.RED)
            else:
                self.results_strip.set("noreply", "none", Colors.TEXT_STRONG)
        else:
            self.results_strip.set("hops", None)
            self.results_strip.set("noreply", None)
        self.route_title.setText(f"ROUTE · {hop_count} HOPS" if hop_count else "ROUTE")
        if self.trace_error and not self.hops:
            self.route_note_text.setText(self.trace_error)
            self.route_note.setVisible(True)
        elif silent:
            if len(silent) == 1:
                which = f"Hop {silent[0]} did"
            else:
                which = f"Hops {', '.join(map(str, silent[:-1]))} and {silent[-1]} did"
            self.route_note_text.setText(f"{which} not reply, but later hops did. Routers often drop "
                                         "these probes on purpose; the path itself is working.")
            self.route_note.setVisible(True)
        elif self.hops and not reached:
            self.route_note_text.setText(f"The trace stopped at hop {hop_count} without reaching {self.target}. "
                                         "A firewall may be dropping the probes.")
            self.route_note.setVisible(True)
        else:
            self.route_note.setVisible(False)

    def set_legend(self, live):
        clear_layout(self.legend)
        self.legend.addWidget(Label("ms per reply" + (" · live" if live else ""), 11.5, color=Colors.TEXT_MUTED))
        if not live:
            stats = self.ping_stats()
            if 'avg' in stats:
                self.legend.addWidget(Label(f"- - avg {stats['avg']:.1f}", 11.5, color=Colors.GREEN))
            lost = [seq for seq, ms in self.replies if ms is None]
            if lost:
                shown = ", ".join(map(str, lost[:5])) + ("…" if len(lost) > 5 else "")
                self.legend.addWidget(Label(f"¦ seq {shown} lost", 11.5, color=Colors.RED))
        self.legend.addStretch(1)

    def store_result(self):
        stats = self.ping_stats()
        parts = []
        if self.ping_enabled and 'avg' in stats:
            parts.append(f"avg {stats['avg']:.1f} ms")
        if self.ping_enabled and stats['sent']:
            parts.append(f"{stats['lost'] * 100 / stats['sent']:.0f}% loss")
        if self.trace_enabled and self.hops:
            count = max(h['hop'] for h in self.hops)
            parts.append(f"{count} hop{'s' if count != 1 else ''}")
        recent_store().add('diagnose', self.target, " · ".join(parts) or "no reply", {
            'replies': self.replies,
            'hops': self.hops,
            'ping': self.ping_enabled,
            'trace': self.trace_enabled,
            'completed': self.completed_at.isoformat(timespec='seconds'),
        })

    def load_entry(self, entry):
        data = entry.get('data', {})
        self.reset_data()
        self.target = entry['target']
        self.host_input.setText(self.target)
        self.replies = [tuple(r) for r in data.get('replies', [])]
        self.hops = data.get('hops', [])
        self.ping_enabled = data.get('ping', True)
        self.trace_enabled = data.get('trace', True)
        try:
            self.completed_at = datetime.fromisoformat(data.get('completed', entry['time']))
        except ValueError:
            self.completed_at = None
        self.chart.reset(max(PING_COUNT, len(self.replies)))
        for seq, ms in self.replies:
            self.chart.add_reply(seq, ms)
        self.hop_list.reset()
        for hop in self.hops:
            self.hop_list.add_hop(hop)
        self.show_results()

    # ------------------------------------------------------------ error
    def show_resolve_error(self, reason, checks):
        self.set_bar_mode(False)
        self.host_input.set_error(True)
        self.header.set_subtitle(self.target, mono=True)
        self.header.set_actions()
        flush = button("Flush DNS and retry", "primary", 32)
        flush.clicked.connect(lambda: self.start(flush_dns=True))
        trouble = button("Run troubleshooter", "secondary", 32)
        trouble.clicked.connect(lambda: self.navigate.emit('trouble', {'action': 'run'}))
        fallback = link_button("Try 8.8.8.8 instead")
        fallback.clicked.connect(lambda: self.run_target("8.8.8.8"))
        what = "ping and trace were" if self.ping_enabled and self.trace_enabled else \
            "ping was" if self.ping_enabled else "trace was"
        if reason == "dns":
            help_text = "Your DNS server is not answering. Flushing the cache or switching DNS usually fixes this."
            actions = [flush, trouble, fallback]
        else:
            help_text = "DNS is working, so the name probably does not exist. Check the spelling."
            actions = [trouble, fallback]
        self.error_card.show_error("Could not resolve host",
                                   f"{self.target} did not resolve to an address, so {what} not started.",
                                   checks, help_text, actions)
        self.views.setCurrentWidget(self.error_card)

    def show_trace_error(self):
        self.set_bar_mode(False)
        self.header.set_actions()
        retry = button("Try again", "primary", 32)
        retry.clicked.connect(self.start)
        help_text = ("Install the traceroute package (for example: sudo dnf install traceroute) and try again."
                     if "not found" in self.trace_error else "")
        self.error_card.show_error("Trace route failed", self.trace_error, None, help_text, [retry])
        self.views.setCurrentWidget(self.error_card)

    # ------------------------------------------------------------ history / export
    def save_history(self, host):
        if host in self.history:
            self.history.remove(host)
        self.history.insert(0, host)
        del self.history[10:]  # Keep last 10 entries
        self.settings.setValue("host_history", self.history)
        self.host_input.setCompleter(QCompleter(self.history, self))

    def export_results(self):
        lines = [f"Diagnose host: {self.target}"]
        if self.completed_at:
            lines.append(f"Completed: {self.completed_at.isoformat(timespec='seconds')}")
        if self.ping_enabled:
            lines += ["", "--- Ping ---"]
            for seq, ms in self.replies:
                lines.append(f"Reply from {self.target}: seq={seq} time={ms:.1f}ms" if ms is not None
                             else f"Request timeout for {self.target}: seq={seq}")
            stats = self.ping_stats()
            lines.append(f"Sent: {stats['sent']}  Received: {stats['received']}  Lost: {stats['lost']}")
            if 'avg' in stats:
                lines.append(f"Min: {stats['min']:.1f} ms  Avg: {stats['avg']:.1f} ms  Max: {stats['max']:.1f} ms")
        if self.trace_enabled:
            lines += ["", "--- Trace route ---"]
            for hop in self.hops:
                lines.append(f"{hop['hop']:>3}  {hop['ip']:<18} {hop['time']}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.save_text("Save Log File", f"ping_test_results_{timestamp}.txt", "\n".join(lines) + "\n")

    def cleanup(self):
        self.stop()
        for thread in (self.ping_thread, self.trace_thread, self.resolve_thread):
            if thread and thread.isRunning():
                thread.wait(5000)


def vbox_with(widget):
    layout = QVBoxLayout()
    layout.setContentsMargins(0, 4, 0, 0)
    layout.addWidget(widget)
    layout.addStretch(1)
    return layout
