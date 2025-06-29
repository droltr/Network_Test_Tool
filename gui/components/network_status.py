from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGroupBox, QGridLayout, QPushButton, QProgressBar,
                            QListWidget, QListWidgetItem, QSplitter, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtGui import QFont
from network.detector import NetworkDetector
import socket
import platform
import logging

logging.basicConfig(filename='network_status_debug.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

class NetworkInfoThread(QThread):
    info_ready = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.detector = NetworkDetector()
        
    def run(self):
        try:
            info = self.detector.get_network_info()
            self.info_ready.emit(info)
        except Exception as e:
            logging.error(f"NetworkInfoThread.run - Error: {e}")
            self.info_ready.emit({"error": str(e)})

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
        logging.debug(f"_update_ui_with_info - Received info: {info}")
        if info.get('error'):
            self.hostname_label.setText(f"Error: {info['error']}")
            self.ip_label.setText("N/A")
            self.gateway_label.setText("N/A")
            self.dns_label.setText("N/A")
            self.mac_label.setText("N/A")
            self.connection_list.clear()
            self.connection_list.addItem(QListWidgetItem(f"Error: {info['error']}"))
            self.adapters_list.clear()
            self.overall_status_update.emit(False)
            return

        # Update hostname
        self.hostname_label.setText(info.get('hostname', 'Unknown'))

        # Update IP addresses and MAC addresses per interface
        ip_mac_text = []
        mac_text = []
        logging.debug(f"Interfaces: {info.get('interfaces', [])}")
        for interface in info.get('interfaces', []):
            name = interface.get('name', 'Unknown')
            ipv4 = interface.get('ipv4', 'N/A')
            mac = interface.get('mac', 'N/A')
            if ipv4 != 'N/A' and not ipv4.startswith('127.') and not ipv4.startswith('169.'):  # Exclude loopback and APIPA
                ip_mac_text.append(f"<b>{name}</b> - IP: {ipv4}")
                mac_text.append(f"<b>{name}</b> - {mac}")
        self.ip_label.setText("<br>".join(ip_mac_text) if ip_mac_text else 'No active network connections')
        self.mac_label.setText("<br>".join(mac_text) if mac_text else 'No active network connections')

        # Update gateway and DNS info
        self.gateway_label.setText("<br>".join(info.get('gateway', ['Unknown'])))
        self.dns_label.setText("<br>".join(info.get('dns', ['Unknown'])))
        
        # Update connection list
        self.connection_list.clear()
        connections = info.get('connections', [])
        logging.debug(f"Connection status update - connections: {connections}")
        
        if not connections:
            # Add default item if no connections are found
            item = QListWidgetItem("No connection data available")
            self.connection_list.addItem(item)
            return
            
        for conn in connections:
            try:
                item = QListWidgetItem()
                self.connection_list.addItem(item)

                label = QLabel()
                status = conn.get('status', 'Unknown')
                description = conn.get('description', 'Unknown')

                if status in ['Disconnected', 'Failed', 'Error']:
                    label.setText(f"<b>{description}:</b> <font color='#BF616A'>{status}</font>")
                elif status in ['Connected', 'Working']:
                    label.setText(f"<b>{description}:</b> <font color='#A3BE8C'>{status}</font>")
                else:
                    label.setText(f"<b>{description}:</b> <font color='#EBCB8B'>{status}</font>")
                
                
                self.connection_list.setItemWidget(item, label)
                
                logging.debug(f"Added connection status: {description}={status}")
            except Exception as e:
                logging.error(f"Error adding connection to UI: {str(e)}")
                continue

        # Check overall status and emit signal
        all_ok = all(conn['status'] in ['Connected', 'Working'] for conn in connections)
        self.overall_status_update.emit(all_ok)

        # Update adapters list
        self.adapters_list.clear()
        for iface in info.get('interfaces', []):
            item = QListWidgetItem(f"{iface['name']}")
            item.setData(32, iface) # 32 is the UserRole (Qt.UserRole)
            self.adapters_list.addItem(item)

    def set_selected_adapter_state(self, state):
        selected_items = self.adapters_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select a network adapter from the list.")
            return

        for item in selected_items:
            iface_info = item.data(32) # 32 is the UserRole (Qt.UserRole)
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
        right_splitter = QSplitter()

        # Connection Status Group
        right_group = QGroupBox("Connection Status")
        right_layout = QVBoxLayout(right_group)
        self.connection_list = QListWidget()
        self.connection_list.setMinimumHeight(100) # Ensure it has some height
        right_layout.addWidget(self.connection_list)
        right_splitter.addWidget(right_group)
        right_splitter.setStretchFactor(0, 1) # Give connection status group a stretch factor
        right_splitter.setStretchFactor(1, 1) # Give adapters group a stretch factor

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
        layout.addStretch()
        
    def setup_timer(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_info)
        self.auto_refresh = False
        self.toggle_auto_refresh()
        
    def refresh_info(self):
        logging.debug("Refreshing network information...")
        
        
        
        # Clear current thread if it's still running
        if self.current_thread and self.current_thread.isRunning():
            logging.debug("Stopping previous thread...")
            self.current_thread.quit()
            self.current_thread.wait() # Wait for the thread to finish

        # Create and start a new thread
        logging.debug("Starting new network info thread...")
        self.current_thread = NetworkInfoThread(self)
        self.current_thread.info_ready.connect(self._update_ui_with_info)
        self.current_thread.finished.connect(self.thread_finished) # Connect finished signal
        self.current_thread.start()

    def thread_finished(self):
        logging.debug("Network info thread finished")
        self.current_thread = None # Clear the reference when the thread finishes
        
        
    
            
    def toggle_auto_refresh(self):
        self.auto_refresh = not self.auto_refresh
        if self.auto_refresh:
            self.timer.start(5000)  # Refresh every 5 seconds
            self.auto_refresh_btn.setText("Auto Refresh: ON")
        else:
            self.timer.stop()
            self.auto_refresh_btn.setText("Auto Refresh: OFF")