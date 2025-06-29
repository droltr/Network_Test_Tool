from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGroupBox, QGridLayout, QPushButton, QProgressBar,
                            QListWidget, QListWidgetItem)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont
from network.detector import NetworkDetector
import socket
import platform

class NetworkInfoThread(QThread):
    info_ready = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        detector = NetworkDetector()
        info = detector.get_network_info()
        self.info_ready.emit(info)

class NetworkStatusWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.detector = NetworkDetector()
        self.current_thread = None  # To keep track of the running thread
        self.setup_ui()
        self.setup_timer()
        self.refresh_info()
        self.update_queue = []
        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.setInterval(100) # Update UI every 100ms
        self.ui_update_timer.timeout.connect(self.process_update_queue)
        self.ui_update_timer.start()

    def closeEvent(self, event):
        # Ensure thread is terminated when widget is closed
        if self.current_thread and self.current_thread.isRunning():
            self.current_thread.quit()
            self.current_thread.wait()
        super().closeEvent(event)

    def process_update_queue(self):
        if self.update_queue:
            info = self.update_queue.pop(0)
            self.hostname_label.setText(info.get('hostname', 'Unknown'))

            # Update IP addresses and MAC addresses per interface
            ip_mac_text = []
            mac_text = []
            for interface in info.get('interfaces', []):
                name = interface.get('name', 'Unknown')
                ipv4 = interface.get('ipv4', 'N/A')
                mac = interface.get('mac', 'N/A')
                ip_mac_text.append(f"<b>{name}</b><br>  IP: {ipv4}")
                mac_text.append(f"<b>{name}</b><br>  MAC: {mac}")
            self.ip_label.setText("<br><br>".join(ip_mac_text) if ip_mac_text else 'Unknown')
            self.mac_label.setText("<br>".join(mac_text) if mac_text else 'Unknown')

            self.gateway_label.setText(", ".join(info.get('gateway', ['Unknown'])))
            self.dns_label.setText("<br>".join(info.get('dns', ['Unknown'])))
            
            # Update connection list
            self.connection_list.clear()
            connections = info.get('connections', [])
            for conn in connections:
                item = QListWidgetItem()
                item.setText(f"{conn['description']}: {conn['status']}")
                from PyQt5.QtGui import QColor, QBrush
                if conn['status'] == 'Connected' or conn['status'] == 'Working':
                    item.setForeground(QBrush(QColor("#A3BE8C")))  # Green
                elif conn['status'] == 'Disconnected' or conn['status'] == 'Failed':
                    item.setForeground(QBrush(QColor("#BF616A")))  # Red
                else:
                    item.setForeground(QBrush(QColor("#EBCB8B")))  # Yellow
                self.connection_list.addItem(item)

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
        left_layout.addWidget(QLabel("Gateway:"), 2, 0)
        left_layout.addWidget(self.gateway_label, 2, 1)
        left_layout.addWidget(QLabel("DNS Server:"), 3, 0)
        left_layout.addWidget(self.dns_label, 3, 1)
        left_layout.addWidget(QLabel("MAC Address:"), 4, 0)
        left_layout.addWidget(self.mac_label, 4, 1)
        
        content_layout.addWidget(left_group)
        
        # Right side - Connection status
        right_group = QGroupBox("Connection Status")
        right_layout = QVBoxLayout(right_group)
        
        self.connection_list = QListWidget()
        right_layout.addWidget(self.connection_list)
        
        content_layout.addWidget(right_group)
        
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
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_info)
        self.auto_refresh = True
        self.toggle_auto_refresh()
        
    def refresh_info(self):
        if self.current_thread and self.current_thread.isRunning():
            self.current_thread.quit()
            self.current_thread.wait() # Wait for the thread to finish

        self.current_thread = NetworkInfoThread(self)
        self.current_thread.info_ready.connect(self.update_info)
        self.current_thread.finished.connect(self.thread_finished) # Connect finished signal
        self.current_thread.start()

    def thread_finished(self):
        self.current_thread = None # Clear the reference when the thread finishes
        
    def update_info(self, info):
        self.update_queue.append(info)
            
    def toggle_auto_refresh(self):
        self.auto_refresh = not self.auto_refresh
        if self.auto_refresh:
            self.timer.start(5000)  # Refresh every 5 seconds
            self.auto_refresh_btn.setText("Auto Refresh: ON")
        else:
            self.timer.stop()
            self.auto_refresh_btn.setText("Auto Refresh: OFF")