from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGroupBox, QGridLayout, QPushButton, QLineEdit,
                            QTextEdit, QProgressBar, QComboBox, QListWidget,
                            QListWidgetItem, QCheckBox, QFileDialog, QCompleter)
from PyQt5.QtCore import QThread, pyqtSignal, QSettings
from PyQt5.QtGui import QFont
from network.scanner import PortScanner


class PortScanThread(QThread):
    progress_update = pyqtSignal(int)
    result_ready = pyqtSignal(dict)
    scan_complete = pyqtSignal(list)

    def __init__(self, host, ports, timeout, parent=None):
        super().__init__(parent)
        self.host = host
        self.ports = ports
        self.timeout = timeout
        self.scanner = PortScanner()

    def run(self):
        self.scanner.scan_ports(
            host=self.host,
            ports=self.ports,
            timeout=self.timeout,
            progress_callback=self._on_progress,
            result_callback=self._on_result
        )
        self.scan_complete.emit(self.scanner.results)

    def _on_progress(self, progress):
        self.progress_update.emit(progress)

    def _on_result(self, result):
        self.result_ready.emit(result)

    def stop(self):
        self.scanner.stop_scan()


class PortScannerWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("NetworkTools", "PortScanner")
        self.history = self.settings.value("host_history", [], type=list)
        self.scanner = PortScanner()
        self.setup_ui()
        self.load_history()
        
    def load_history(self):
        completer = QCompleter(self.history, self)
        self.host_input.setCompleter(completer)

    def save_history(self):
        if self.host_input.text() not in self.history:
            self.history.insert(0, self.host_input.text())
            if len(self.history) > 10: # Keep last 10 entries
                self.history.pop()
            self.settings.setValue("host_history", self.history)
            self.load_history() # Update completer
        
    def cleanup(self):
        if hasattr(self, 'scan_thread') and self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.stop()
            self.scan_thread.wait()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 15, 20, 15)
        
        # Header
        header = QLabel("Port Scanner")
        header.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(header)
        
        # Input group
        input_group = QGroupBox("Scan Settings")
        input_layout = QGridLayout(input_group)
        input_layout.setSpacing(10)
        input_layout.setContentsMargins(15, 20, 15, 15)
        
        # Host input
        input_layout.addWidget(QLabel("Target Host:"), 0, 0)
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("Enter IP address or hostname")
        self.host_input.setText("127.0.0.1")
        self.host_input.setMinimumHeight(35)
        input_layout.addWidget(self.host_input, 0, 1)
        
        # Port preset selection
        input_layout.addWidget(QLabel("Port Preset:"), 1, 0)
        self.preset_combo = QComboBox()
        self.port_presets = PortScanner.get_common_ports()
        self.preset_combo.addItems(list(self.port_presets.keys()))
        self.preset_combo.currentTextChanged.connect(self.on_preset_changed)
        self.preset_combo.setMinimumHeight(35)
        input_layout.addWidget(self.preset_combo, 1, 1)
        
        # Custom port range
        input_layout.addWidget(QLabel("Custom Range:"), 2, 0)
        port_layout = QHBoxLayout()
        self.port_start = QLineEdit()
        self.port_start.setPlaceholderText("Start")
        self.port_start.setText("1")
        self.port_start.setMinimumHeight(35)
        self.port_end = QLineEdit()
        self.port_end.setPlaceholderText("End")
        self.port_end.setText("1000")
        self.port_end.setMinimumHeight(35)
        port_layout.addWidget(self.port_start)
        port_layout.addWidget(QLabel("to"))
        port_layout.addWidget(self.port_end)
        port_layout.addStretch()
        
        port_widget = QWidget()
        port_widget.setLayout(port_layout)
        input_layout.addWidget(port_widget, 2, 1)
        
        # Timeout setting
        input_layout.addWidget(QLabel("Timeout (s):"), 3, 0)
        self.timeout_input = QLineEdit()
        self.timeout_input.setText("1.0")
        self.timeout_input.setPlaceholderText("1.0")
        self.timeout_input.setMinimumHeight(35)
        input_layout.addWidget(self.timeout_input, 3, 1)
        
        # Start button
        self.start_btn = QPushButton("Start Scan")
        self.start_btn.setFixedHeight(40)
        self.start_btn.clicked.connect(self.start_scan)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.clicked.connect(self.stop_scan)
        self.stop_btn.setEnabled(False)
        self.export_btn = QPushButton("Export")
        self.export_btn.setFixedHeight(40)
        self.export_btn.clicked.connect(self.export_log)
        self.export_btn.setEnabled(False)
        
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addWidget(self.export_btn)
        button_layout.addStretch()
        
        input_layout.addLayout(button_layout, 4, 0, 1, 2)
        
        layout.addWidget(input_group)
        
        # Progress
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(25)
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("")
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_label)
        layout.addLayout(progress_layout)
        
        # Results
        results_layout = QHBoxLayout()
        results_layout.setSpacing(15)
        
        # Open ports list
        open_ports_group = QGroupBox("Open Ports")
        open_ports_layout = QVBoxLayout(open_ports_group)
        open_ports_layout.setContentsMargins(15, 20, 15, 15)
        self.open_ports_list = QListWidget()
        self.open_ports_list.setMinimumHeight(200)
        open_ports_layout.addWidget(self.open_ports_list)
        results_layout.addWidget(open_ports_group, 1)
        
        # Detailed results
        details_group = QGroupBox("Scan Results")
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(15, 20, 15, 15)
        self.results_text = QTextEdit()
        self.results_text.setMinimumHeight(200)
        self.results_text.setPlaceholderText("Scan results will appear here...")
        details_layout.addWidget(self.results_text)
        results_layout.addWidget(details_group, 1)
        
        layout.addLayout(results_layout)
        
        # Set initial preset
        self.on_preset_changed("Common")
        
    def on_preset_changed(self, preset_name):
        """Update port range when preset is changed."""
        if preset_name in self.port_presets:
            ports = self.port_presets[preset_name]
            if len(ports) > 0:
                self.port_start.setText(str(min(ports)))
                self.port_end.setText(str(max(ports)))
        
    def get_ports_to_scan(self):
        """Get the list of ports to scan based on current selection."""
        preset_name = self.preset_combo.currentText()
        if preset_name in self.port_presets:
            return self.port_presets[preset_name]
        else:
            # Use custom range
            try:
                start = int(self.port_start.text())
                end = int(self.port_end.text())
                return list(range(start, end + 1))
            except ValueError:
                return []
    
    def start_scan(self):
        """Start the port scan."""
        host = self.host_input.text().strip()
        if not host:
            self.results_text.append("Error: Please enter a host to scan")
            return
            
        ports = self.get_ports_to_scan()
        if not ports:
            self.results_text.append("Error: No valid ports to scan")
            return
            
        try:
            timeout = float(self.timeout_input.text())
        except ValueError:
            timeout = 1.0
            
        # Update UI
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.results_text.clear()
        self.open_ports_list.clear()
        
        self.results_text.append(f"Starting port scan on {host}")
        self.results_text.append(f"Scanning {len(ports)} ports with {timeout}s timeout")
        self.results_text.append("=" * 50)
        
        # Start scan in thread
        self.scan_thread = PortScanThread(host, ports, timeout, self)
        self.scan_thread.progress_update.connect(self.on_progress)
        self.scan_thread.result_ready.connect(self.on_port_result)
        self.scan_thread.scan_complete.connect(self.on_scan_complete)
        self.scan_thread.start()

        # Save host to history
        self.save_history()
        
    def stop_scan(self):
        """Stop the current scan."""
        self.scan_thread.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.results_text.append("\nScan stopped by user.")
        
    def on_progress(self, progress):
        """Update progress bar."""
        self.progress_bar.setValue(progress)
        self.progress_label.setText(f"Scanning... {progress}%")
        
    def on_port_result(self, result):
        """Handle individual port scan result."""
        port = result.get('port', 0)
        status = result.get('status', 'Unknown')
        service = result.get('service', 'Unknown')
        
        if status == 'Open':
            # Add to open ports list
            item_text = f"Port {port}"
            if service and service != "Unknown":
                item_text += f" ({service})"
            
            item = QListWidgetItem(item_text)
            from PyQt5.QtGui import QColor, QBrush
            item.setForeground(QBrush(QColor("#98c379")))
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            self.open_ports_list.addItem(item)
            
            # Add to results text
            self.results_text.append(f"Port {port}: OPEN ({service})")
        
    def on_scan_complete(self, results):
        """Handle scan completion."""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        
        # Count results
        open_ports = [r for r in results if r.get('status') == 'Open']
        closed_ports = [r for r in results if r.get('status') == 'Closed']
        error_ports = [r for r in results if r.get('status') == 'Error']
        
        # Summary
        self.results_text.append("\n" + "=" * 50)
        self.results_text.append("SCAN SUMMARY")
        self.results_text.append("=" * 50)
        self.results_text.append(f"Total ports scanned: {len(results)}")
        self.results_text.append(f"Open ports: {len(open_ports)}")
        self.results_text.append(f"Closed ports: {len(closed_ports)}")
        self.results_text.append(f"Errors: {len(error_ports)}")
        
        if not open_ports:
            self.results_text.append("\nNo open ports found.")
        else:
            self.results_text.append(f"\nFound {len(open_ports)} open port(s):")
            for result in open_ports:
                port = result.get('port', 0)
                service = result.get('service', 'Unknown')
                self.results_text.append(f"  • Port {port} ({service})")
        
        self.export_btn.setEnabled(True)

    def export_log(self):
        """Export the scan results to a text file."""
        log_content = self.results_text.toPlainText()
        if not log_content:
            return

        # Generate default filename with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"port_scan_results_{timestamp}.txt"

        # Open file dialog
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Log File", default_filename, "Text Files (*.txt);;All Files (*)", options=options)

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(log_content)
            except Exception as e:
                self.results_text.append(f"\nError saving log: {e}")