from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGroupBox, QGridLayout, QPushButton, QTextEdit,
                            QProgressBar, QFrame, QFileDialog)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont
from network.speed_test import SpeedTester


class SpeedTestThread(QThread):
    progress_update = pyqtSignal(int, str)
    test_complete = pyqtSignal(dict)
    latency_complete = pyqtSignal(dict)

    def __init__(self, test_type, host=None, parent=None):
        super().__init__(parent)
        self.test_type = test_type
        self.host = host
        self.speed_tester = SpeedTester()

    def run(self):
        if self.test_type == "full":
            results = self.speed_tester.perform_speed_test(progress_callback=self._on_progress)
            self.test_complete.emit(results)
        elif self.test_type == "latency":
            results = self.speed_tester.test_latency(host=self.host)
            self.latency_complete.emit(results)

    def _on_progress(self, progress, message):
        self.progress_update.emit(progress, message)

    def stop(self):
        self.speed_tester.stop_test()


class SpeedTestWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.speed_tester = SpeedTester()
        self.setup_ui()
        
    def cleanup(self):
        if hasattr(self, 'test_thread') and self.test_thread and self.test_thread.isRunning():
            self.test_thread.stop()
            self.test_thread.wait()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 15, 20, 15)
        
        # Header
        header = QLabel("Internet Speed Test")
        header.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(header)
        
        # Control group
        control_group = QGroupBox("Speed Test Controls")
        control_layout = QVBoxLayout(control_group)
        control_layout.setContentsMargins(15, 20, 15, 15)
        control_layout.setSpacing(10)
        
        # Test buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        self.full_test_btn = QPushButton("Full Speed Test")
        self.full_test_btn.setFixedHeight(40)
        self.full_test_btn.clicked.connect(self.start_full_test)
        self.latency_test_btn = QPushButton("Latency Test")
        self.latency_test_btn.setFixedHeight(40)
        self.latency_test_btn.clicked.connect(self.start_latency_test)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.clicked.connect(self.stop_test)
        self.stop_btn.setEnabled(False)
        
        button_layout.addWidget(self.full_test_btn)
        button_layout.addWidget(self.latency_test_btn)
        button_layout.addWidget(self.stop_btn)
        button_layout.addStretch()
        
        control_layout.addLayout(button_layout)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(25)
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel("")
        
        control_layout.addWidget(self.progress_bar)
        control_layout.addWidget(self.progress_label)
        
        layout.addWidget(control_group)
        
        # Results display
        results_layout = QHBoxLayout()
        results_layout.setSpacing(15)
        
        # Current results
        current_results_group = QGroupBox("Current Test Results")
        current_layout = QVBoxLayout(current_results_group)
        current_layout.setContentsMargins(15, 20, 15, 15)
        
        # Speed metrics
        metrics_frame = QFrame()
        metrics_layout = QGridLayout(metrics_frame)
        metrics_layout.setSpacing(15)
        
        # Download speed
        metrics_layout.addWidget(QLabel("Download:"), 0, 0)
        self.download_label = QLabel("-- Mbps")
        self.download_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.download_label.setStyleSheet("color: #61afef;")
        metrics_layout.addWidget(self.download_label, 0, 1)
        
        # Upload speed
        metrics_layout.addWidget(QLabel("Upload:"), 1, 0)
        self.upload_label = QLabel("-- Mbps")
        self.upload_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.upload_label.setStyleSheet("color: #98c379;")
        metrics_layout.addWidget(self.upload_label, 1, 1)
        
        # Ping
        metrics_layout.addWidget(QLabel("Ping:"), 2, 0)
        self.ping_label = QLabel("-- ms")
        self.ping_label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        self.ping_label.setStyleSheet("color: #e5c07b;")
        metrics_layout.addWidget(self.ping_label, 2, 1)
        
        # Server info
        metrics_layout.addWidget(QLabel("Server:"), 3, 0)
        self.server_label = QLabel("--")
        self.server_label.setWordWrap(True)
        metrics_layout.addWidget(self.server_label, 3, 1)
        
        metrics_layout.setColumnStretch(1, 1)
        
        current_layout.addWidget(metrics_frame)
        results_layout.addWidget(current_results_group, 1)
        
        # Detailed results log
        log_group = QGroupBox("Test Log")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(15, 20, 15, 15)
        self.results_text = QTextEdit()
        self.results_text.setMinimumHeight(200)
        self.results_text.setPlaceholderText("Speed test results will appear here...")
        log_layout.addWidget(self.results_text)
        
        # Clear log and export buttons
        log_button_layout = QHBoxLayout()
        log_button_layout.setSpacing(10)
        clear_btn = QPushButton("Clear Log")
        clear_btn.setFixedHeight(35)
        clear_btn.clicked.connect(self.clear_log)
        self.export_btn = QPushButton("Export")
        self.export_btn.setFixedHeight(35)
        self.export_btn.clicked.connect(self.export_log)
        self.export_btn.setEnabled(False)
        log_button_layout.addWidget(clear_btn)
        log_button_layout.addWidget(self.export_btn)
        log_button_layout.addStretch()
        log_layout.addLayout(log_button_layout)
        
        results_layout.addWidget(log_group, 1)
        
        layout.addLayout(results_layout)
        
    def start_full_test(self):
        """Start a full speed test."""
        self.full_test_btn.setEnabled(False)
        self.latency_test_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        self.results_text.append("Starting full speed test...")
        self.reset_display()
        
        # Start speed test in thread
        self.test_thread = SpeedTestThread("full", parent=self)
        self.test_thread.progress_update.connect(self.on_progress)
        self.test_thread.test_complete.connect(self.on_test_complete)
        self.test_thread.start()
        
    def start_latency_test(self):
        """Start latency test only."""
        self.full_test_btn.setEnabled(False)
        self.latency_test_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        self.results_text.append("Starting latency test...")
        
        # Run latency test
        self.test_thread = SpeedTestThread("latency", host="8.8.8.8", parent=self)
        self.test_thread.latency_complete.connect(self.on_latency_complete)
        self.test_thread.start()
        
    def stop_test(self):
        """Stop the current test."""
        self.test_thread.stop()
        self.full_test_btn.setEnabled(True)
        self.latency_test_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.results_text.append("Test stopped by user.")
        
    def on_progress(self, progress, message):
        """Update progress display."""
        self.progress_bar.setValue(progress)
        self.progress_label.setText(message)
        
    def on_test_complete(self, result):
        """Handle speed test completion."""
        self.full_test_btn.setEnabled(True)
        self.latency_test_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        
        if result.get('error'):
            self.results_text.append(f"Error: {result['error']}")
            return
            
        # Update display
        download = result.get('download_speed', 0)
        upload = result.get('upload_speed', 0)
        ping = result.get('ping', 0)
        server = result.get('server', {})
        
        self.download_label.setText(f"{download} Mbps")
        self.upload_label.setText(f"{upload} Mbps")
        self.ping_label.setText(f"{ping} ms")
        
        server_text = server.get('name', 'Unknown')
        if server.get('sponsor'):
            server_text += f" ({server['sponsor']})"
        self.server_label.setText(server_text)
        
        # Log results
        self.results_text.append("\n" + "=" * 40)
        self.results_text.append("SPEED TEST RESULTS")
        self.results_text.append("=" * 40)
        self.results_text.append(f"Download Speed: {download} Mbps")
        self.results_text.append(f"Upload Speed: {upload} Mbps")
        self.results_text.append(f"Ping: {ping} ms")
        self.results_text.append(f"Server: {server_text}")
        if server.get('country'):
            self.results_text.append(f"Location: {server['country']}")
        if server.get('distance'):
            self.results_text.append(f"Distance: {server['distance']} km")
        
        self.export_btn.setEnabled(True)

    def on_latency_complete(self, result):
        """Handle latency test completion."""
        self.full_test_btn.setEnabled(True)
        self.latency_test_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        if result.get('error'):
            self.results_text.append(f"Latency test error: {result['error']}")
            return
            
        avg_latency = result.get('avg_latency', 0)
        min_latency = result.get('min_latency', 0)
        max_latency = result.get('max_latency', 0)
        packet_loss = result.get('packet_loss', 0)
        host = result.get('host', '8.8.8.8')
        
        self.ping_label.setText(f"{avg_latency} ms")
        
        # Log results
        self.results_text.append("\n" + "=" * 40)
        self.results_text.append("LATENCY TEST RESULTS")
        self.results_text.append("=" * 40)
        self.results_text.append(f"Host: {host}")
        self.results_text.append(f"Average Latency: {avg_latency} ms")
        self.results_text.append(f"Min Latency: {min_latency} ms")
        self.results_text.append(f"Max Latency: {max_latency} ms")
        self.results_text.append(f"Packet Loss: {packet_loss}%")

        self.export_btn.setEnabled(True)
        
    def reset_display(self):
        """Reset the speed display."""
        self.download_label.setText("-- Mbps")
        self.upload_label.setText("-- Mbps")
        self.ping_label.setText("-- ms")
        self.server_label.setText("--")
        
    def clear_log(self):
        """Clear the results log."""
        self.results_text.clear()
        self.export_btn.setEnabled(False)

    def export_log(self):
        """Export the test results to a text file."""
        log_content = self.results_text.toPlainText()
        if not log_content:
            return

        # Open file dialog
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Log File", "", "Text Files (*.txt);;All Files (*)", options=options)

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(log_content)
            except Exception as e:
                self.results_text.append(f"\nError saving log: {e}")