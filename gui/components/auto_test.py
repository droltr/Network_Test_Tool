from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QGroupBox, QPushButton, QTextEdit, QFileDialog)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont
from network.troubleshooter import Troubleshooter

class TroubleshootThread(QThread):
    progress_update = pyqtSignal(str)
    test_complete = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.troubleshooter = Troubleshooter()

    def run(self):
        log = self.troubleshooter.run_troubleshooting(progress_callback=self.progress_update.emit)
        self.test_complete.emit(log)

class AutoTestWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()

    def cleanup(self):
        if hasattr(self, 'thread') and isinstance(self.thread, QThread) and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Automated Network Troubleshooter")
        header.setFont(QFont("Arial", 16, QFont.Bold))
        layout.addWidget(header)

        # Controls
        controls_group = QGroupBox("Controls")
        controls_layout = QHBoxLayout(controls_group)
        self.start_btn = QPushButton("Start Troubleshooting")
        self.start_btn.clicked.connect(self.start_troubleshooting)
        self.export_btn = QPushButton("Export Log")
        self.export_btn.clicked.connect(self.export_log)
        self.export_btn.setEnabled(False)
        controls_layout.addWidget(self.start_btn)
        controls_layout.addWidget(self.export_btn)
        controls_layout.addStretch()
        layout.addWidget(controls_group)

        # Results
        results_group = QGroupBox("Log")
        results_layout = QVBoxLayout(results_group)
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setPlaceholderText("Troubleshooting log will appear here...")
        results_layout.addWidget(self.results_text)
        
        # Clear log button
        clear_btn_layout = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Log")
        self.clear_btn.clicked.connect(self.results_text.clear)
        clear_btn_layout.addStretch()
        clear_btn_layout.addWidget(self.clear_btn)
        clear_btn_layout.addStretch()
        results_layout.addLayout(clear_btn_layout)

        layout.addWidget(results_group)

    def start_troubleshooting(self):
        self.start_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.results_text.clear()

        self.thread = TroubleshootThread(self)
        self.thread.progress_update.connect(self.update_log)
        self.thread.test_complete.connect(self.on_complete)
        self.thread.start()

    def update_log(self, message):
        self.results_text.append(message)

    def on_complete(self, log):
        self.start_btn.setEnabled(True)
        self.export_btn.setEnabled(True)

    def export_log(self):
        log_content = self.results_text.toPlainText()
        if not log_content:
            return

        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Log File", "", "Text Files (*.txt);;All Files (*)", options=options)

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(log_content)
            except Exception as e:
                self.update_log(f"\nError saving log: {e}")
