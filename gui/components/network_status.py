from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGroupBox, QGridLayout, QPushButton, QProgressBar,
                            QListWidget, QListWidgetItem, QSplitter, QMessageBox,
                            QFrame, QScrollArea, QComboBox)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, Qt
from PyQt5.QtGui import QFont, QIcon, QDesktopServices
from PyQt5.QtCore import QUrl
from network.detector import NetworkDetector
from network.system_tools import SystemTools
from network.reporting import ReportGenerator
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
            info['diagnostics'] = self.detector.detect_network_issues()
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
        is_apipa = ipv4.startswith('169.254')
        
        # Header row: Name and Status
        header_layout = QHBoxLayout()
        name_label = QLabel(name)
        name_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        name_label.setStyleSheet("color: #abb2bf;")
        
        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)

        if is_apipa:
            apipa_label = QLabel("⚠ APIPA")
            apipa_label.setStyleSheet("color: #e5c07b; font-weight: bold; border: 1px solid #e5c07b; border-radius: 3px; padding: 2px 5px;")
            apipa_label.setToolTip("DHCP server not responding. Try 'ipconfig /renew'")
            status_layout.addWidget(apipa_label)

        status_label = QLabel()
        if is_active:
            status_label.setText("● Active")
            status_label.setStyleSheet("color: #98c379; font-weight: 600;")
        elif is_apipa:
            status_label.setText("● Limited")
            status_label.setStyleSheet("color: #e5c07b; font-weight: 600;")
        else:
            status_label.setText("○ Inactive")
            status_label.setStyleSheet("color: #5c6370; font-weight: 600;")
        
        status_layout.addWidget(status_label)

        header_layout.addWidget(name_label)
        header_layout.addStretch()
        header_layout.addLayout(status_layout)
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
        if is_active or is_apipa:
            ip_title = QLabel("IP Address:")
            ip_title.setStyleSheet("color: #5c6370; font-size: 9pt;")
            ip_value = QLabel(ipv4)
            if is_apipa:
                ip_value.setStyleSheet("color: #e5c07b; font-size: 10pt; font-weight: 600;")
            else:
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
    overall_status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.detector = NetworkDetector()
        self.system_tools = SystemTools()
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
            self.overall_status_update.emit("offline")
            return

        # Update hostname
        self.hostname_label.setText(f"Computer: {info.get('hostname', 'Unknown')}")

        # Update Diagnostics
        diagnostics = info.get('diagnostics', {})
        status = diagnostics.get('status', 'ok')
        all_issues = diagnostics.get('issues', [])
        
        # Filter out APIPA issues as they are now shown on cards
        issues = [i for i in all_issues if i.get('type') != 'apipa_address']
        
        # Clear previous issues
        while self.issues_list.count():
            item = self.issues_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not issues and status != 'critical':
            # Compact healthy state
            self.diag_status_label.setText("✓ System Healthy")
            self.diag_status_label.setStyleSheet("color: #98c379; font-weight: bold;")
            self.diagnostics_frame.setStyleSheet("background-color: #2c313a; border-radius: 5px; margin: 5px 25px;")
            self.diagnostics_frame.setVisible(True)
        else:
            # Issues detected
            if status == 'critical':
                self.diag_status_label.setText(f"❌ {len(issues)} Critical Issue(s)")
                self.diag_status_label.setStyleSheet("color: #e06c75; font-weight: bold;")
                self.diagnostics_frame.setStyleSheet("background-color: #3e2e2e; border-radius: 5px; margin: 5px 25px; border: 1px solid #e06c75;")
            else:
                self.diag_status_label.setText(f"⚠ {len(issues)} Warning(s)")
                self.diag_status_label.setStyleSheet("color: #e5c07b; font-weight: bold;")
                self.diagnostics_frame.setStyleSheet("background-color: #3d382e; border-radius: 5px; margin: 5px 25px; border: 1px solid #e5c07b;")
            
            self.diagnostics_frame.setVisible(True)
            
            for issue in issues:
                issue_widget = QWidget()
                issue_layout = QHBoxLayout(issue_widget)
                issue_layout.setContentsMargins(0, 0, 0, 0)
                issue_layout.setSpacing(5)
                
                msg = QLabel(f"• {issue['message']}")
                msg.setStyleSheet("color: #abb2bf;")
                issue_layout.addWidget(msg)
                
                if 'solution' in issue:
                    sol = QLabel(f"→ {issue['solution']}")
                    sol.setStyleSheet("color: #98c379; font-style: italic; font-size: 9pt;")
                    issue_layout.addWidget(sol)
                
                issue_layout.addStretch()
                self.issues_list.addWidget(issue_widget)

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
            is_apipa = ipv4.startswith('169.254')
            
            if is_active or is_apipa:
                active_adapters.append(interface)
            else:
                inactive_adapters.append(interface)
        
        # Sort each group alphabetically by name
        active_adapters.sort(key=lambda x: x.get('name', ''))
        inactive_adapters.sort(key=lambda x: x.get('name', ''))
        
        # Combine: active first, then inactive
        sorted_interfaces = active_adapters + inactive_adapters
        
        # Update Adapter ComboBox
        current_selection = self.adapter_combo.currentText()
        self.adapter_combo.blockSignals(True)
        self.adapter_combo.clear()
        self.adapter_combo.addItem("All Adapters")
        
        # Add only active/APIPA adapters to the list
        for interface in active_adapters:
            self.adapter_combo.addItem(interface.get('name', 'Unknown'))
            
        # Restore selection if possible
        index = self.adapter_combo.findText(current_selection)
        if index >= 0:
            self.adapter_combo.setCurrentIndex(index)
        self.adapter_combo.blockSignals(False)
        
        # Create card for each adapter
        for interface in sorted_interfaces:
            card = AdapterCard(interface, gateway_list, dns_list)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        # Check overall status
        connections = info.get('connections', [])
        
        internet_status = next((c['status'] for c in connections if c['description'] == 'Internet Connection'), 'Disconnected')
        local_status = next((c['status'] for c in connections if c['description'] == 'Local Network'), 'Disconnected')
        
        if internet_status == 'Connected':
            status = "online"
        elif local_status == 'Connected':
            status = "local"
        else:
            status = "offline"
            
        self.overall_status_update.emit(status)
    
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
        
        # Diagnostics Panel
        self.diagnostics_frame = QFrame()
        self.diagnostics_frame.setObjectName("diagnosticsFrame")
        self.diagnostics_frame.setStyleSheet("background-color: #2c313a; border-radius: 5px; margin: 5px 25px;")
        
        diag_layout = QVBoxLayout(self.diagnostics_frame)
        diag_layout.setContentsMargins(10, 5, 10, 5)
        
        self.diag_status_label = QLabel("✓ System Healthy")
        self.diag_status_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.diag_status_label.setStyleSheet("color: #98c379;")
        diag_layout.addWidget(self.diag_status_label)
        
        self.issues_list = QVBoxLayout()
        diag_layout.addLayout(self.issues_list)
        
        layout.addWidget(self.diagnostics_frame)

        # Quick Actions Panel
        self.actions_frame = QFrame()
        self.actions_frame.setObjectName("actionsFrame")
        self.actions_frame.setStyleSheet("background-color: #2c313a; border-radius: 5px; margin: 0 25px 5px 25px;")
        
        actions_layout = QHBoxLayout(self.actions_frame)
        actions_layout.setContentsMargins(10, 5, 10, 5)
        actions_layout.setSpacing(15)
        
        actions_label = QLabel("Quick Actions:")
        actions_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        actions_label.setStyleSheet("color: #abb2bf;")
        actions_layout.addWidget(actions_label)
        
        # Adapter Selection
        self.adapter_combo = QComboBox()
        self.adapter_combo.setMinimumWidth(200)
        self.adapter_combo.setToolTip("Select target adapter for IP operations")
        self.adapter_combo.addItem("All Adapters")
        actions_layout.addWidget(self.adapter_combo)
        
        # Helper to create compact buttons
        def create_action_btn(text, tooltip, callback, color="#61afef"):
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {color};
                    border: 1px solid {color};
                    border-radius: 3px;
                    padding: 3px 10px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background-color: {color};
                    color: #282c34;
                }}
            """)
            btn.clicked.connect(callback)
            return btn

        self.btn_renew = create_action_btn("Renew IP", "ipconfig /renew", lambda: self.run_quick_action("renew_ip"))
        actions_layout.addWidget(self.btn_renew)
        
        self.btn_flush = create_action_btn("Flush DNS", "ipconfig /flushdns", lambda: self.run_quick_action("flush_dns"))
        actions_layout.addWidget(self.btn_flush)
        
        self.btn_release = create_action_btn("Release IP", "ipconfig /release", lambda: self.run_quick_action("release_ip"))
        actions_layout.addWidget(self.btn_release)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setStyleSheet("background-color: #3e4451;")
        actions_layout.addWidget(line)

        # Report Button
        self.btn_report = create_action_btn("Generate Report", "Export network report", self.generate_report, color="#98c379")
        actions_layout.addWidget(self.btn_report)
        
        actions_layout.addStretch()
        
        layout.addWidget(self.actions_frame)
        
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
        
    def generate_report(self):
        """Generate and open a network report."""
        self.setCursor(Qt.WaitCursor)
        try:
            # Generate default filename with timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"network_report_{timestamp}.txt"
            
            self.setCursor(Qt.ArrowCursor)
            
            options = QFileDialog.Options()
            options |= QFileDialog.DontUseNativeDialog
            file_path, _ = QFileDialog.getSaveFileName(self, "Save Network Report", default_filename, "Text Files (*.txt);;All Files (*)", options=options)
            
            if not file_path:
                return

            self.setCursor(Qt.WaitCursor)
            
            reporter = ReportGenerator()
            # Pass the full path to the reporter
            filepath = reporter.generate_text_report(file_path)
            
            self.setCursor(Qt.ArrowCursor)
            
            msg = QMessageBox()
            msg.setWindowTitle("Report Generated")
            msg.setText(f"Report saved successfully:\n{filepath}")
            msg.setStandardButtons(QMessageBox.Open | QMessageBox.Ok)
            ret = msg.exec_()
            
            if ret == QMessageBox.Open:
                QDesktopServices.openUrl(QUrl.fromLocalFile(filepath))
                
        except Exception as e:
            self.setCursor(Qt.ArrowCursor)
            QMessageBox.critical(self, "Error", f"Failed to generate report: {str(e)}")

    def run_quick_action(self, action_name):
        """Execute a quick action command"""
        self.setCursor(Qt.WaitCursor)
        success = False
        output = ""
        
        # Get selected adapter
        selected_adapter = self.adapter_combo.currentText()
        adapter_arg = None if selected_adapter == "All Adapters" else selected_adapter
        
        try:
            if action_name == "renew_ip":
                success, output = self.system_tools.renew_ip(adapter_arg)
                action_desc = f"Renew IP ({selected_adapter})"
            elif action_name == "flush_dns":
                # DNS flush is global
                success, output = self.system_tools.flush_dns()
                action_desc = "Flush DNS"
            elif action_name == "release_ip":
                success, output = self.system_tools.release_ip(adapter_arg)
                action_desc = f"Release IP ({selected_adapter})"
            
            self.setCursor(Qt.ArrowCursor)
            
            if success:
                QMessageBox.information(self, "Success", f"{action_desc} completed successfully.\n\nOutput:\n{output}")
                self.refresh_info() # Refresh status after action
            else:
                QMessageBox.warning(self, "Failed", f"{action_desc} failed.\n\nError:\n{output}")
                
        except Exception as e:
            self.setCursor(Qt.ArrowCursor)
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")

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