"""Advanced: ARP table, active connections and NetBIOS lookup as header sub-tabs."""
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QButtonGroup, QTableWidgetItem

from gui.pages.base import Page, finish_thread
from gui.styles.modern_theme import Colors, mono_font, ui_font
from gui.widgets.common import (Card, Label, LineInput, LogPane, StatusDot, Badge, button, link_button, hbox,
                                make_table, cell_widget)
from network.advanced import AdvancedDiagnostics

STATUS_COLORS = {
    'ESTABLISHED': Colors.GREEN,
    'LISTEN': Colors.BLUE,
}


class Worker(QThread):
    done = pyqtSignal(object)

    def __init__(self, func, parent=None):
        super().__init__(parent)
        self.func = func

    def run(self):
        self.done.emit(self.func())


def text_item(text, font, color):
    item = QTableWidgetItem(text)
    item.setFont(font)
    item.setForeground(QColor(color))
    return item


class AdvancedPage(Page):
    def __init__(self):
        super().__init__("Advanced")
        self.tool = AdvancedDiagnostics()
        self.workers = []
        self.connections = []
        self.conn_filter = "all"

        # Underline tabs in the page header
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for index, text in enumerate(("ARP table", "Connections", "NetBIOS")):
            tab = button(text, "tab", 47)
            tab.setCheckable(True)
            self.tab_group.addButton(tab, index)
            self.header.tabs.addWidget(tab)
        self.tab_group.buttonClicked[int].connect(self.show_tab)
        self.header.subtitle.setVisible(False)
        self.body.setContentsMargins(20, 14, 20, 18)

        self.stack = QStackedWidget()
        self.body.addWidget(self.stack, 1)
        self.stack.addWidget(self.build_arp())
        self.stack.addWidget(self.build_connections())
        self.stack.addWidget(self.build_netbios())
        self.loaded = set()
        self.tab_group.button(0).setChecked(True)

    def showEvent(self, event):
        super().showEvent(event)
        self.show_tab(self.tab_group.checkedId())

    def show_tab(self, index):
        self.stack.setCurrentIndex(index)
        if index not in self.loaded and index in (0, 1):
            self.loaded.add(index)
            (self.refresh_arp if index == 0 else self.refresh_conns)()

    def run_worker(self, func, callback):
        worker = Worker(func, self)
        worker.done.connect(callback)
        worker.finished.connect(lambda: self.workers.remove(worker))
        self.workers.append(worker)
        worker.start()

    # ------------------------------------------------------------ ARP
    def build_arp(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.arp_filter = LineInput("Filter IP or MAC", height=32, mono=False)
        self.arp_filter.setFixedWidth(300)
        self.arp_filter.textChanged.connect(self.filter_arp)
        self.arp_count = Label("", 12.5, color=Colors.TEXT_MUTED)
        self.arp_refresh = button("Refresh", "secondary", 32)
        self.arp_refresh.clicked.connect(self.refresh_arp)
        layout.addLayout(hbox(self.arp_filter, 6, self.arp_count, "stretch", self.arp_refresh))
        self.arp_table = make_table(["IP address", "MAC address", "Type", "Interface", ""], stretch_column=1)
        header = self.arp_table.horizontalHeader()
        header.resizeSection(0, 300)
        header.resizeSection(2, 120)
        header.resizeSection(3, 120)
        header.resizeSection(4, 90)
        layout.addWidget(self.arp_table, 1)
        return page

    def refresh_arp(self):
        self.arp_refresh.setEnabled(False)
        self.run_worker(self.tool.get_arp_table, self.update_arp_table)

    def update_arp_table(self, data):
        self.arp_refresh.setEnabled(True)
        data = sorted(data, key=lambda e: tuple(int(p) if p.isdigit() else 0 for p in e['ip'].split('.')))
        self.arp_table.setRowCount(len(data))
        for i, entry in enumerate(data):
            self.arp_table.setItem(i, 0, text_item(entry['ip'], mono_font(12.5), Colors.TEXT_STRONG))
            self.arp_table.setItem(i, 1, text_item(entry['mac'], mono_font(12), Colors.TEXT))
            if entry['type'] == 'static':
                self.arp_table.setCellWidget(i, 2, cell_widget(Badge("static", Colors.PURPLE)))
                self.arp_table.setItem(i, 2, QTableWidgetItem(""))
            else:
                self.arp_table.setItem(i, 2, text_item(entry['type'], ui_font(11.5), Colors.TEXT_MUTED))
            self.arp_table.setItem(i, 3, text_item(entry.get('interface') or '', mono_font(12), Colors.TEXT_MUTED))
            ping = link_button("Ping")
            ping.clicked.connect(lambda _=False, ip=entry['ip']: self.navigate.emit('diagnose', {'target': ip}))
            self.arp_table.setCellWidget(i, 4, cell_widget(ping))
        interfaces = sorted({e.get('interface') for e in data if e.get('interface')})
        self.arp_count.setText(f"{len(data)} entries" + (f" · {', '.join(interfaces)}" if interfaces else ""))
        self.filter_arp(self.arp_filter.text())

    def filter_arp(self, text):
        needle = text.strip().lower()
        for row in range(self.arp_table.rowCount()):
            haystack = " ".join(self.arp_table.item(row, c).text().lower() for c in (0, 1, 3)
                                if self.arp_table.item(row, c))
            self.arp_table.setRowHidden(row, bool(needle) and needle not in haystack)

    # ------------------------------------------------------------ connections
    def build_connections(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.conn_filter_input = LineInput("Filter process, address or port", height=32, mono=False)
        self.conn_filter_input.setFixedWidth(300)
        self.conn_filter_input.textChanged.connect(self.apply_conn_filter)
        self.chips = {}
        chip_group = QButtonGroup(self)
        for key in ("all", "established", "listening"):
            chip = button("", "chip", 24)
            chip.setCheckable(True)
            chip.clicked.connect(lambda _=False, k=key: self.set_conn_filter(k))
            chip_group.addButton(chip)
            self.chips[key] = chip
        self.chips["all"].setChecked(True)
        self.conn_refresh = button("Refresh", "secondary", 32)
        self.conn_refresh.clicked.connect(self.refresh_conns)
        layout.addLayout(hbox(self.conn_filter_input, 4, self.chips["all"], self.chips["established"],
                              self.chips["listening"], "stretch", self.conn_refresh, spacing=6))
        self.conn_table = make_table(["Process", "PID", "Proto", "Local", "Remote", "Status"], stretch_column=4)
        header = self.conn_table.horizontalHeader()
        for column, width in ((0, 220), (1, 80), (2, 70), (3, 250), (5, 130)):
            header.resizeSection(column, width)
        layout.addWidget(self.conn_table, 1)
        return page

    def refresh_conns(self):
        self.conn_refresh.setEnabled(False)
        self.run_worker(lambda: self.tool.get_active_connections(include_all=True), self.update_conn_table)

    def update_conn_table(self, data):
        self.conn_refresh.setEnabled(True)
        order = {'ESTABLISHED': 0, 'LISTEN': 1}
        self.connections = sorted(data, key=lambda c: (order.get(c['status'], 2), c['process'].lower()))
        counts = {
            "all": len(data),
            "established": sum(1 for c in data if c['status'] == 'ESTABLISHED'),
            "listening": sum(1 for c in data if c['status'] == 'LISTEN'),
        }
        for key, title in (("all", "All"), ("established", "Established"), ("listening", "Listening")):
            self.chips[key].setText(f"{title} {counts[key]}")
            self.chips[key].setFont(ui_font(12, 600 if self.chips[key].isChecked() else 500))

        table = self.conn_table
        table.setRowCount(len(self.connections))
        for i, c in enumerate(self.connections):
            name = c['process'] if c['process'] != "Unknown" else "—"
            table.setItem(i, 0, text_item(name, ui_font(12.5, 500), Colors.TEXT_STRONG))
            table.setItem(i, 1, text_item(str(c['pid']) if c['pid'] else "—", mono_font(12), Colors.TEXT_MUTED))
            table.setItem(i, 2, text_item(c['proto'], mono_font(12), Colors.TEXT))
            table.setItem(i, 3, text_item(c['local'], mono_font(12), Colors.TEXT))
            table.setItem(i, 4, text_item(c['remote'], mono_font(12), Colors.TEXT))
            status = c['status'] if c['status'] not in ('NONE', '') else "—"
            color = STATUS_COLORS.get(status, Colors.YELLOW if status.endswith('WAIT') else Colors.TEXT_MUTED)
            table.setItem(i, 5, text_item(status, ui_font(11, 600), color))
        self.apply_conn_filter()

    def set_conn_filter(self, key):
        self.conn_filter = key
        for chip_key, chip in self.chips.items():
            chip.setFont(ui_font(12, 600 if chip_key == key else 500))
        self.apply_conn_filter()

    def apply_conn_filter(self, _text=None):
        needle = self.conn_filter_input.text().strip().lower()
        for row, c in enumerate(self.connections):
            visible = (self.conn_filter == "all"
                       or (self.conn_filter == "established" and c['status'] == 'ESTABLISHED')
                       or (self.conn_filter == "listening" and c['status'] == 'LISTEN'))
            if needle:
                haystack = f"{c['process']} {c['pid']} {c['local']} {c['remote']} {c['status']}".lower()
                visible = visible and needle in haystack
            self.conn_table.setRowHidden(row, not visible)

    # ------------------------------------------------------------ NetBIOS
    def build_netbios(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.nbt_input = LineInput("Enter IP address", height=32)
        self.nbt_input.setFixedWidth(300)
        self.nbt_input.returnPressed.connect(self.run_nbt_lookup)
        self.nbt_btn = button("Lookup", "primary", 32)
        self.nbt_btn.clicked.connect(self.run_nbt_lookup)
        layout.addLayout(hbox(self.nbt_input, self.nbt_btn, "stretch"))

        self.nbt_banner = Card("banner", margins=(14, 10, 14, 10))
        self.nbt_banner_title = Label("", 12.5, 600, Colors.TEXT_STRONG)
        self.nbt_banner_text = Label("", 12.5, color=Colors.TEXT)
        self.nbt_banner_text.setWordWrap(True)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(self.nbt_banner_title)
        text_col.addWidget(self.nbt_banner_text)
        self.nbt_ping = button("Ping this IP", "secondary", 30)
        self.nbt_ping.clicked.connect(lambda: self.navigate.emit('diagnose', {'target': self.nbt_input.text().strip()}))
        banner_row = QHBoxLayout()
        banner_row.setSpacing(12)
        banner_row.addWidget(StatusDot(Colors.RED, 7))
        banner_row.addLayout(text_col, 1)
        banner_row.addWidget(self.nbt_ping)
        self.nbt_banner.body.addLayout(banner_row)
        self.nbt_banner.setVisible(False)
        layout.addWidget(self.nbt_banner)

        self.nbt_output = LogPane("Output")
        layout.addWidget(self.nbt_output, 1)
        return page

    def run_nbt_lookup(self):
        ip = self.nbt_input.text().strip()
        if not ip:
            self.nbt_input.set_error(True)
            return
        self.nbt_btn.setEnabled(False)
        self.nbt_output.clear()
        self.nbt_output.append_line(f"Looking up status of {ip}", Colors.TEXT_MUTED)
        self.run_worker(lambda: self.tool.lookup_netbios(ip), lambda result: self.on_nbt_result(ip, result))

    def on_nbt_result(self, ip, result):
        self.nbt_btn.setEnabled(True)
        self.nbt_output.clear()
        for line in (result['output'] or "").splitlines():
            self.nbt_output.append_line(line, Colors.RED if line.startswith("No reply") else None)
        if result['ok']:
            self.nbt_banner.setVisible(False)
            self.nbt_input.set_error(False)
            return
        self.nbt_input.set_error(True)
        if "not found" in (result['error'] or "") and "nmblookup" in result['error']:
            self.nbt_banner_title.setText("NetBIOS lookup is not available")
            self.nbt_banner_text.setText(result['error'])
            self.nbt_ping.setVisible(False)
        else:
            self.nbt_banner_title.setText(f"No response from {ip}")
            self.nbt_banner_text.setText("The host is offline or does not answer NetBIOS name queries (UDP 137).")
            self.nbt_ping.setVisible(True)
        if not result['output']:
            self.nbt_output.append_line(result['error'], Colors.RED)
        self.nbt_banner.setVisible(True)

    def cleanup(self):
        for worker in list(self.workers):
            finish_thread(worker, 5000)
