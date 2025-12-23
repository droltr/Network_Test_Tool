from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGroupBox, QGridLayout, QPushButton, QLineEdit,
                            QSpinBox, QTextEdit, QProgressBar, QCompleter, QFileDialog)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer, QSettings
from PyQt5.QtGui import QFont
from network.ping import PingTester

class PingThread(QThread):
    result_ready = pyqtSignal(dict)
    progress_update = pyqtSignal(str)
    
    def __init__(self, host, count):
        super().__init__()
        self.host = host
        self.count = count
        
    def run(self):
        try:
            tester = PingTester()
            result = tester.ping_host(self.host, self.count, progress_callback=self.progress_update.emit)
            self.result_ready.emit(result)
        except Exception as e:
            self.result_ready.emit({"error": str(e)})

class PingTestWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("NetworkTools", "PingTest")
        self.history = self.settings.value("host_history", [], type=list)
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
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 15, 20, 15)
        
        # Header
        header = QLabel("Ping Test")
        header.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(header)
        
        # Input group
        input_group = QGroupBox("Ping Settings")
        input_layout = QGridLayout(input_group)
        input_layout.setSpacing(10)
        input_layout.setContentsMargins(15, 20, 15, 15)
        
        # Host input
        input_layout.addWidget(QLabel("Target Host:"), 0, 0)
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("Enter IP address or hostname (e.g., google.com)")
        self.host_input.setText("8.8.8.8")
        self.host_input.setMinimumHeight(35)
        input_layout.addWidget(self.host_input, 0, 1)
        
        # Count input
        input_layout.addWidget(QLabel("Ping Count:"), 1, 0)
        self.count_input = QSpinBox()
        self.count_input.setMinimum(1)
        self.count_input.setMaximum(100)
        self.count_input.setValue(4)
        self.count_input.setMinimumHeight(35)
        input_layout.addWidget(self.count_input, 1, 1)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Ping Test")
        self.start_btn.setFixedHeight(40)
        self.start_btn.clicked.connect(self.start_ping)
        
        self.export_btn = QPushButton("Export Results")
        self.export_btn.setFixedHeight(40)
        self.export_btn.clicked.connect(self.export_log)
        self.export_btn.setEnabled(False)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.export_btn)
        
        input_layout.addLayout(btn_layout, 2, 0, 1, 2)
        
        layout.addWidget(input_group)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(25)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Results group
        results_group = QGroupBox("Results")
        results_layout = QVBoxLayout(results_group)
        results_layout.setContentsMargins(15, 20, 15, 15)
        
        # Statistics
        stats_layout = QGridLayout()
        stats_layout.setSpacing(15)
        self.sent_label = QLabel("Sent: 0")
        self.received_label = QLabel("Received: 0")
        self.lost_label = QLabel("Lost: 0")
        self.min_label = QLabel("Min: 0 ms")
        self.max_label = QLabel("Max: 0 ms")
        self.avg_label = QLabel("Avg: 0 ms")
        
        for label in [self.sent_label, self.received_label, self.lost_label, 
                      self.min_label, self.max_label, self.avg_label]:
            label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        
        stats_layout.addWidget(self.sent_label, 0, 0)
        stats_layout.addWidget(self.received_label, 0, 1)
        stats_layout.addWidget(self.lost_label, 0, 2)
        stats_layout.addWidget(self.min_label, 1, 0)
        stats_layout.addWidget(self.max_label, 1, 1)
        stats_layout.addWidget(self.avg_label, 1, 2)
        
        results_layout.addLayout(stats_layout)
        
        # Detailed results
        self.results_text = QTextEdit()
        self.results_text.setMinimumHeight(200)
        self.results_text.setPlaceholderText("Ping results will appear here...")
        results_layout.addWidget(self.results_text)
        
        layout.addWidget(results_group)
        
    def cleanup(self):
        if hasattr(self, 'ping_thread') and self.ping_thread and self.ping_thread.isRunning():
            self.ping_thread.quit()
            self.ping_thread.wait()

    def start_ping(self):
        host = self.host_input.text().strip()
        if not host:
            self.results_text.append("Error: Please enter a host to ping")
            return
            
        count = self.count_input.value()
        
        self.start_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, count)
        self.progress_bar.setValue(0)
        self.results_text.clear()
        
        # Reset statistics
        self.sent_label.setText("Sent: 0")
        self.received_label.setText("Received: 0")
        self.lost_label.setText("Lost: 0")
        self.min_label.setText("Min: 0 ms")
        self.max_label.setText("Max: 0 ms")
        self.avg_label.setText("Avg: 0 ms")
        
        # Start ping thread
        self.ping_thread = PingThread(host, count)
        self.ping_thread.result_ready.connect(self.on_ping_finished)
        self.ping_thread.progress_update.connect(self.on_ping_progress)
        self.ping_thread.start()
        
    def on_ping_progress(self, message):
        self.results_text.append(message)
        self.progress_bar.setValue(self.progress_bar.value() + 1)
        
    def on_ping_finished(self, result):
        self.start_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        if "error" in result:
            self.results_text.append(f"Error: {result['error']}")
            return
            
        # Save host to history
        self.save_history()

        # Update statistics
        stats = result.get('statistics', {})
        self.sent_label.setText(f"Sent: {stats.get('sent', 0)}")
        self.received_label.setText(f"Received: {stats.get('received', 0)}")
        self.lost_label.setText(f"Lost: {stats.get('lost', 0)}")
        
        if stats.get('times'):
            times = stats['times']
            self.min_label.setText(f"Min: {min(times):.1f} ms")
            self.max_label.setText(f"Max: {max(times):.1f} ms")
            self.avg_label.setText(f"Avg: {sum(times)/len(times):.1f} ms")
            
        self.results_text.append(f"\n--- Ping Test Complete ---")
        self.results_text.append(f"Host: {result.get('host', 'Unknown')}")
        self.results_text.append(f"Success Rate: {stats.get('success_rate', 0):.1f}%")

    def export_log(self):
        """Export the ping results to a text file."""
        log_content = self.results_text.toPlainText()
        if not log_content:
            return

        # Generate default filename with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"ping_test_results_{timestamp}.txt"

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