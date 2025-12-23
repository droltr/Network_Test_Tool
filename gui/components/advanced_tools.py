from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QTableWidget, QTableWidgetItem, QHeaderView, 
                            QTabWidget, QPushButton, QLineEdit, QTextEdit, QSplitter)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from network.advanced import AdvancedDiagnostics

class ArpWorker(QThread):
    finished = pyqtSignal(list)
    def __init__(self):
        super().__init__()
        self.tool = AdvancedDiagnostics()
    def run(self):
        data = self.tool.get_arp_table()
        self.finished.emit(data)

class ConnectionsWorker(QThread):
    finished = pyqtSignal(list)
    def __init__(self):
        super().__init__()
        self.tool = AdvancedDiagnostics()
    def run(self):
        data = self.tool.get_active_connections()
        self.finished.emit(data)

class AdvancedWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        
        # ARP Table Tab
        self.arp_tab = QWidget()
        self.setup_arp_tab()
        self.tabs.addTab(self.arp_tab, "ARP Table")
        
        # Connections Tab
        self.conn_tab = QWidget()
        self.setup_conn_tab()
        self.tabs.addTab(self.conn_tab, "Active Connections")
        
        # NetBIOS Tab
        self.nbt_tab = QWidget()
        self.setup_nbt_tab()
        self.tabs.addTab(self.nbt_tab, "NetBIOS Lookup")
        
        layout.addWidget(self.tabs)

    def setup_arp_tab(self):
        layout = QVBoxLayout(self.arp_tab)
        
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh ARP Table")
        refresh_btn.clicked.connect(self.refresh_arp)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.arp_table = QTableWidget()
        self.arp_table.setColumnCount(4)
        self.arp_table.setHorizontalHeaderLabels(["IP Address", "MAC Address", "Type", "Interface"])
        self.arp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.arp_table)

    def setup_conn_tab(self):
        layout = QVBoxLayout(self.conn_tab)
        
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Connections")
        refresh_btn.clicked.connect(self.refresh_conns)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.conn_table = QTableWidget()
        self.conn_table.setColumnCount(6)
        self.conn_table.setHorizontalHeaderLabels(["Process", "PID", "Protocol", "Local Address", "Remote Address", "Status"])
        self.conn_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.conn_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.conn_table)

    def setup_nbt_tab(self):
        layout = QVBoxLayout(self.nbt_tab)
        
        input_layout = QHBoxLayout()
        layout.addLayout(input_layout)
        
        self.nbt_input = QLineEdit()
        self.nbt_input.setPlaceholderText("Enter IP Address")
        input_layout.addWidget(self.nbt_input)
        
        lookup_btn = QPushButton("Lookup")
        lookup_btn.clicked.connect(self.run_nbt_lookup)
        input_layout.addWidget(lookup_btn)
        
        self.nbt_output = QTextEdit()
        self.nbt_output.setReadOnly(True)
        self.nbt_output.setFontFamily("Consolas")
        layout.addWidget(self.nbt_output)

    def refresh_arp(self):
        self.arp_table.setRowCount(0)
        self.arp_worker = ArpWorker()
        self.arp_worker.finished.connect(self.update_arp_table)
        self.arp_worker.start()

    def update_arp_table(self, data):
        self.arp_table.setRowCount(len(data))
        for i, entry in enumerate(data):
            self.arp_table.setItem(i, 0, QTableWidgetItem(entry['ip']))
            self.arp_table.setItem(i, 1, QTableWidgetItem(entry['mac']))
            self.arp_table.setItem(i, 2, QTableWidgetItem(entry['type']))
            self.arp_table.setItem(i, 3, QTableWidgetItem(entry.get('interface', '')))

    def refresh_conns(self):
        self.conn_table.setRowCount(0)
        self.conn_worker = ConnectionsWorker()
        self.conn_worker.finished.connect(self.update_conn_table)
        self.conn_worker.start()

    def update_conn_table(self, data):
        self.conn_table.setRowCount(len(data))
        for i, entry in enumerate(data):
            self.conn_table.setItem(i, 0, QTableWidgetItem(entry['process']))
            self.conn_table.setItem(i, 1, QTableWidgetItem(str(entry['pid'])))
            self.conn_table.setItem(i, 2, QTableWidgetItem(entry['proto']))
            self.conn_table.setItem(i, 3, QTableWidgetItem(entry['local']))
            self.conn_table.setItem(i, 4, QTableWidgetItem(entry['remote']))
            self.conn_table.setItem(i, 5, QTableWidgetItem(entry['status']))

    def run_nbt_lookup(self):
        ip = self.nbt_input.text().strip()
        if not ip: return
        
        tool = AdvancedDiagnostics()
        result = tool.get_netbios_info(ip)
        self.nbt_output.setText(result)
