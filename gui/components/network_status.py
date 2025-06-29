from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGroupBox, QGridLayout, QPushButton, QProgressBar,
                            QListWidget, QListWidgetItem, QSplitter)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QFont
from network.detector import NetworkDetector
import socket
import platform

class NetworkInfoThread(QThread):
    info_ready = pyqtSignal(dict)

class NetworkStatusWidget(QWidget):
    overall_status_update = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.detector = NetworkDetector()
        self.current_thread = None  # To keep track of the running thread
        self.setup_ui()
        self.setup_timer()
        self.refresh_info()

    def cleanup(self):
        self.timer.stop()
        if self.current_thread and self.current_thread.isRunning():
            self.current_thread.quit()
            self.current_thread.wait()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def _update_ui_with_info(self, info):
        self.hostname_label.setText(info.get('hostname', 'Unknown'))

        # Update IP addresses and MAC addresses per interface
        ip_mac_text = []
        mac_text = []
        for interface in info.get('interfaces', []):
            name = interface.get('name', 'Unknown')
            ipv4 = interface.get('ipv4', 'N/A')
            mac = interface.get('mac', 'N/A')
            ip_mac_text.append(f"{name} - IP: {ipv4}")
            mac_text.append(f"{name} - {mac}")
        self.ip_label.setText("<br>".join(ip_mac_text) if ip_mac_text else 'Unknown')
        self.mac_label.setText("<br>".join(mac_text) if mac_text else 'Unknown')

        self.gateway_label.setText("<br>".join(info.get('gateway', ['Unknown'])))
        self.dns_label.setText("<br>".join(info.get('dns', ['Unknown'])))
        
        # Update connection list
        self.connection_list.clear()
        connections = info.get('connections', [])
        for conn in connections:
            item = QListWidgetItem()
            self.connection_list.addItem(item)

            label = QLabel()
            status = conn['status']
            description = conn['description']

            if conn['status'] in ['Disconnected', 'Failed']:
                label.setText(f"<b>{description}:</b> <font color='#BF616A'>{status}</font>")
            elif conn['status'] in ['Connected', 'Working']:
                label.setText(f"{description}: <font color='#A3BE8C'>{status}</font>")
            else:
                label.setText(f"{description}: <font color='#EBCB8B'>{status}</font>")
            
            item.setSizeHint(label.sizeHint())
            self.connection_list.setItemWidget(item, label)

        # Check overall status and emit signal
        all_ok = all(conn['status'] in ['Connected', 'Working'] for conn in connections)
        self.overall_status_update.emit(all_ok)

        # Update adapters list
        self.adapters_list.clear()
        for iface in info.get('interfaces', []):
            item = QListWidgetItem(f"{iface['name']}")
            item.setData(Qt.UserRole, iface) # Store full interface info
            self.adapters_list.addItem(item)

    def set_selected_adapter_state(self, state):
        selected_items = self.adapters_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select a network adapter from the list.")
            return

        for item in selected_items:
            iface_info = item.data(Qt.UserRole)
            adapter_name = iface_info['name']
            success, message = self.detector.set_adapter_state(adapter_name, state)
            if success:
                QMessageBox.information(self, "Success", message)
                self.refresh_info() # Refresh to show updated status
            else:
                QMessageBox.critical(self, "Error", message)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Header
        header = QLabel("Network Status & Information")
        header.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(header)
        
        # Main content
        content_layout = QHBoxLayout()
        
        # Left side - Network info
        left_group = QGroupBox("Network Information")
        left_layout = QGridLayout(left_group)
        
        self.hostname_label = QLabel("Loading...")
        self.ip_label = QLabel("Loading...")
        self.gateway_label = QLabel("Loading...")
        self.dns_label = QLabel("Loading...")
        self.mac_label = QLabel("Loading...")
        
        left_layout.addWidget(QLabel("Hostname:"), 0, 0)
        left_layout.addWidget(self.hostname_label, 0, 1)
        left_layout.addWidget(QLabel("IP Address:"), 1, 0)
        left_layout.addWidget(self.ip_label, 1, 1, 1, 2) # Span 2 columns
        left_layout.addWidget(QLabel("Gateway:"), 2, 0)
        left_layout.addWidget(self.gateway_label, 2, 1, 1, 2) # Span 2 columns
        left_layout.addWidget(QLabel("DNS Server:"), 3, 0)
        left_layout.addWidget(self.dns_label, 3, 1, 1, 2) # Span 2 columns
        left_layout.addWidget(QLabel("MAC Address:"), 4, 0)
        left_layout.addWidget(self.mac_label, 4, 1, 1, 2) # Span 2 columns
        
        content_layout.addWidget(left_group)
        
        # Right side - Connection status & Adapters
        right_splitter = QSplitter(Qt.Vertical)

        # Connection Status Group
        right_group = QGroupBox("Connection Status")
        right_layout = QVBoxLayout(right_group)
        self.connection_list = QListWidget()
        right_layout.addWidget(self.connection_list)
        right_splitter.addWidget(right_group)

        # Adapters Group
        adapters_group = QGroupBox("Network Adapters (Administrator privileges required)")
        adapters_layout = QVBoxLayout(adapters_group)
        self.adapters_list = QListWidget()
        adapters_layout.addWidget(self.adapters_list)
        
        adapter_buttons_layout = QHBoxLayout()
        self.enable_adapter_btn = QPushButton("Enable Selected")
        self.enable_adapter_btn.clicked.connect(lambda: self.set_selected_adapter_state(True))
        self.disable_adapter_btn = QPushButton("Disable Selected")
        self.disable_adapter_btn.clicked.connect(lambda: self.set_selected_adapter_state(False))
        adapter_buttons_layout.addWidget(self.enable_adapter_btn)
        adapter_buttons_layout.addWidget(self.disable_adapter_btn)
        adapters_layout.addLayout(adapter_buttons_layout)
        right_splitter.addWidget(adapters_group)

        content_layout.addWidget(right_splitter)
        
        layout.addLayout(content_layout)
        
        # Controls
        controls_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Information")
        self.refresh_btn.clicked.connect(self.refresh_info)
        
        self.auto_refresh_btn = QPushButton("Auto Refresh: OFF")
        self.auto_refresh_btn.clicked.connect(self.toggle_auto_refresh)
        
        controls_layout.addWidget(self.refresh_btn)
        controls_layout.addWidget(self.auto_refresh_btn)
        controls_layout.addStretch()
        
        layout.addLayout(controls_layout)
        
    def setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_info)
        self.auto_refresh = False
        self.toggle_auto_refresh()
        
    def refresh_info(self):
        if self.current_thread and self.current_thread.isRunning():
            self.current_thread.quit()
            self.current_thread.wait() # Wait for the thread to finish

        self.current_thread = NetworkInfoThread(self)
        self.current_thread.info_ready.connect(self._update_ui_with_info)
        self.current_thread.finished.connect(self.thread_finished) # Connect finished signal
        self.current_thread.start()

    def thread_finished(self):
        self.current_thread = None # Clear the reference when the thread finishes
        
    
            
    def toggle_auto_refresh(self):
        self.auto_refresh = not self.auto_refresh
        if self.auto_refresh:
            self.timer.start(5000)  # Refresh every 5 seconds
            self.auto_refresh_btn.setText("Auto Refresh: ON")
        else:
            self.timer.stop()
            self.auto_refresh_btn.setText("Auto Refresh: OFF")