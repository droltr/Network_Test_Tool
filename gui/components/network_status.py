from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGroupBox, QGridLayout, QPushButton, QProgressBar,
                            QListWidget, QListWidgetItem, QSplitter, QMessageBox,
                            QFrame, QScrollArea)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
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

class AdapterCard(QFrame):
    """Custom card widget for each network adapter"""
    def __init__(self, adapter_data, gateway_list, dns_list, parent=None):
        super().__init__(parent)
        self.adapter_data = adapter_data
        self.setup_ui(gateway_list, dns_list)
        
    def setup_ui(self, gateway_list, dns_list):
        self.setObjectName("adapterCard")
        self.setFrameShape(QFrame.StyledPanel)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(8)
        
        name = self.adapter_data.get('name', 'Unknown')
        ipv4 = self.adapter_data.get('ipv4', 'N/A')
        mac = self.adapter_data.get('mac', 'N/A')
        
        is_active = ipv4 != 'N/A' and not ipv4.startswith('127.') and not ipv4.startswith('169.')
        
        # Header row: Name and Status
        header_layout = QHBoxLayout()
        name_label = QLabel(name)
        name_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        name_label.setStyleSheet("color: #abb2bf;")
        
        status_label = QLabel()
        if is_active:
            status_label.setText("● Active")
            status_label.setStyleSheet("color: #98c379; font-weight: 600;")
        else:
            status_label.setText("○ Inactive")
            status_label.setStyleSheet("color: #5c6370; font-weight: 600;")
        
        header_layout.addWidget(name_label)
        header_layout.addStretch()
        header_layout.addWidget(status_label)
        layout.addLayout(header_layout)
        
        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #3e4451;")
        line.setFixedHeight(1)
        layout.addWidget(line)
        
        # Details grid
        details_layout = QGridLayout()
        details_layout.setSpacing(8)
        details_layout.setColumnStretch(1, 1)
        
        row = 0
        
        # IP Address
        if is_active:
            ip_title = QLabel("IP Address:")
            ip_title.setStyleSheet("color: #5c6370; font-size: 9pt;")
            ip_value = QLabel(ipv4)
            ip_value.setStyleSheet("color: #61afef; font-size: 10pt; font-weight: 600;")
            ip_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            details_layout.addWidget(ip_title, row, 0)
            details_layout.addWidget(ip_value, row, 1)
            row += 1
        
        # MAC Address
        mac_title = QLabel("MAC Address:")
        mac_title.setStyleSheet("color: #5c6370; font-size: 9pt;")
        mac_value = QLabel(mac)
        mac_value.setStyleSheet("color: #abb2bf; font-size: 9pt;")
        mac_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        details_layout.addWidget(mac_title, row, 0)
        details_layout.addWidget(mac_value, row, 1)
        row += 1
        
        # Gateway (only for active adapters)
        if is_active and gateway_list:
            gateway_title = QLabel("Gateway:")
            gateway_title.setStyleSheet("color: #5c6370; font-size: 9pt;")
            gateway_value = QLabel(", ".join(gateway_list[:2]))
            gateway_value.setStyleSheet("color: #abb2bf; font-size: 9pt;")
            gateway_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            details_layout.addWidget(gateway_title, row, 0)
            details_layout.addWidget(gateway_value, row, 1)
            row += 1
        
        # DNS (only for active adapters)
        if is_active and dns_list:
            dns_title = QLabel("DNS Servers:")
            dns_title.setStyleSheet("color: #5c6370; font-size: 9pt;")
            dns_value = QLabel(", ".join(dns_list[:2]))
            dns_value.setStyleSheet("color: #abb2bf; font-size: 9pt;")
            dns_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            details_layout.addWidget(dns_title, row, 0)
            details_layout.addWidget(dns_value, row, 1)
        
        layout.addLayout(details_layout)

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
        
        # Clear existing cards
        while self.cards_layout.count() > 1:  # Keep the stretch at the end
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if info.get('error'):
            self.hostname_label.setText(f"Computer: Error")
            error_label = QLabel(f"Error: {info['error']}")
            error_label.setStyleSheet("color: #e06c75; padding: 20px;")
            self.cards_layout.insertWidget(0, error_label)
            self.overall_status_update.emit(False)
            return

        # Update hostname
        self.hostname_label.setText(f"Computer: {info.get('hostname', 'Unknown')}")

        # Get gateway and DNS info
        gateway_list = info.get('gateway', [])
        dns_list = info.get('dns', [])
        interfaces = info.get('interfaces', [])
        
        logging.debug(f"Interfaces: {interfaces}")
        
        # Sort adapters: Active first, then inactive
        active_adapters = []
        inactive_adapters = []
        
        for interface in interfaces:
            ipv4 = interface.get('ipv4', 'N/A')
            is_active = ipv4 != 'N/A' and not ipv4.startswith('127.') and not ipv4.startswith('169.')
            
            if is_active:
                active_adapters.append(interface)
            else:
                inactive_adapters.append(interface)
        
        # Sort each group alphabetically by name
        active_adapters.sort(key=lambda x: x.get('name', ''))
        inactive_adapters.sort(key=lambda x: x.get('name', ''))
        
        # Combine: active first, then inactive
        sorted_interfaces = active_adapters + inactive_adapters
        
        # Create card for each adapter
        for interface in sorted_interfaces:
            card = AdapterCard(interface, gateway_list, dns_list)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        # Check overall status
        connections = info.get('connections', [])
        all_ok = all(conn['status'] in ['Connected', 'Working'] for conn in connections) if connections else False
        self.overall_status_update.emit(all_ok)
    
    def set_selected_adapter_state(self, state):
        # This feature requires selecting from cards - not implemented in card view
        # Could add click-to-select functionality if needed
        QMessageBox.information(self, "Info", "Adapter enable/disable controls are not available in card view.\nUse Windows Network Settings for adapter management.")
        pass

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header with computer name
        header_frame = QFrame()
        header_frame.setObjectName("statusHeader")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(25, 15, 25, 15)
        
        title = QLabel("Network Adapters")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        
        self.hostname_label = QLabel("Computer: Loading...")
        self.hostname_label.setFont(QFont("Segoe UI", 10))
        self.hostname_label.setStyleSheet("color: #5c6370;")
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.hostname_label)
        
        layout.addWidget(header_frame)
        
        # Scroll area for adapter cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scroll_content = QWidget()
        self.cards_layout = QVBoxLayout(scroll_content)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setContentsMargins(20, 20, 20, 20)
        self.cards_layout.addStretch()
        
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        # Bottom controls
        controls_frame = QFrame()
        controls_frame.setObjectName("statusFooter")
        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(25, 15, 25, 15)
        controls_layout.setSpacing(10)
        
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedSize(100, 35)
        self.refresh_btn.clicked.connect(self.refresh_info)
        
        self.auto_refresh_btn = QPushButton("Auto Refresh: OFF")
        self.auto_refresh_btn.setFixedSize(150, 35)
        self.auto_refresh_btn.clicked.connect(self.toggle_auto_refresh)
        
        admin_note = QLabel("⚠ Adapter controls require administrator privileges")
        admin_note.setStyleSheet("color: #5c6370; font-size: 8pt;")
        
        controls_layout.addWidget(self.refresh_btn)
        controls_layout.addWidget(self.auto_refresh_btn)
        controls_layout.addStretch()
        controls_layout.addWidget(admin_note)
        
        layout.addWidget(controls_frame)
        
        # Store reference to selected adapter
        self.selected_adapter = None
        
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
            self.timer.start(10000)  # Refresh every 10 seconds
            self.auto_refresh_btn.setText("Auto Refresh: ON")
        else:
            self.timer.stop()
            self.auto_refresh_btn.setText("Auto Refresh: OFF")