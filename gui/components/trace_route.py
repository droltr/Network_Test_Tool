from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                            QHeaderView, QProgressBar, QMessageBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from network.trace import TraceRoute

class TraceWorker(QThread):
    update_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal()

    def __init__(self, target):
        super().__init__()
        self.target = target
        self.tracer = TraceRoute()

    def run(self):
        self.tracer.run_trace(self.target, self.update_signal.emit)
        self.finished_signal.emit()

    def stop(self):
        self.tracer.stop()

class TraceRouteWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setup_ui()
        self.worker = None

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Header
        header_layout = QHBoxLayout()
        
        target_label = QLabel("Target Host:")
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("e.g., google.com or 8.8.8.8")
        self.target_input.returnPressed.connect(self.start_trace)
        
        self.start_btn = QPushButton("Start Trace")
        self.start_btn.clicked.connect(self.start_trace)
        self.start_btn.setFixedWidth(100)
        
        header_layout.addWidget(target_label)
        header_layout.addWidget(self.target_input)
        header_layout.addWidget(self.start_btn)
        
        layout.addLayout(header_layout)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 0) # Indeterminate
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Results Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Hop", "IP Address", "Latency", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

    def start_trace(self):
        target = self.target_input.text().strip()
        if not target:
            QMessageBox.warning(self, "Input Error", "Please enter a target host.")
            return

        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()

        self.table.setRowCount(0)
        self.start_btn.setText("Stop")
        self.start_btn.clicked.disconnect()
        self.start_btn.clicked.connect(self.stop_trace)
        self.target_input.setEnabled(False)
        self.progress_bar.show()

        self.worker = TraceWorker(target)
        self.worker.update_signal.connect(self.update_table)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def stop_trace(self):
        if self.worker:
            self.worker.stop()
        self.on_finished()

    def on_finished(self):
        self.start_btn.setText("Start Trace")
        self.start_btn.clicked.disconnect()
        self.start_btn.clicked.connect(self.start_trace)
        self.target_input.setEnabled(True)
        self.progress_bar.hide()

    def update_table(self, data):
        if "error" in data:
            QMessageBox.critical(self, "Error", data["error"])
            return

        row = self.table.rowCount()
        self.table.insertRow(row)
        
        hop_item = QTableWidgetItem(str(data.get("hop", "")))
        hop_item.setTextAlignment(Qt.AlignCenter)
        
        ip_item = QTableWidgetItem(data.get("ip", ""))
        
        time_item = QTableWidgetItem(data.get("time", ""))
        time_item.setTextAlignment(Qt.AlignCenter)
        
        status_str = "OK" if data.get("status") == "ok" else "Timeout"
        status_item = QTableWidgetItem(status_str)
        status_item.setTextAlignment(Qt.AlignCenter)
        
        if data.get("status") == "timeout":
            status_item.setForeground(Qt.red)
            time_item.setForeground(Qt.red)
        else:
            status_item.setForeground(Qt.darkGreen)

        self.table.setItem(row, 0, hop_item)
        self.table.setItem(row, 1, ip_item)
        self.table.setItem(row, 2, time_item)
        self.table.setItem(row, 3, status_item)
        
        self.table.scrollToBottom()
