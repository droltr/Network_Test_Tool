import sys
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QTabWidget, QLabel, QFrame, QPushButton, QTextEdit,
                            QLineEdit, QSpinBox, QProgressBar, QGroupBox, QGridLayout,
                            QMessageBox, QComboBox, QListWidget, QSplitter, QApplication)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QPalette, QColor, QIcon
from .components.network_status import NetworkStatusWidget
from .components.ping_test import PingTestWidget
from .components.port_scanner import PortScannerWidget
from .components.speed_test import SpeedTestWidget
from .styles.modern_theme import ModernTheme

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Diagnostic Tools")
        self.setGeometry(100, 100, 1200, 800)
        self.setup_ui()
        self.apply_theme()
        
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        
        # Header
        header = self.create_header()
        layout.addWidget(header)
        
        # Main content with tabs
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        
        # Add tabs
        self.status_widget = NetworkStatusWidget()
        self.tab_widget.addTab(self.status_widget, "🌐 Network Status")
        
        self.ping_widget = PingTestWidget()
        self.tab_widget.addTab(self.ping_widget, "📡 Ping Test")
        
        self.port_widget = PortScannerWidget()
        self.tab_widget.addTab(self.port_widget, "🔍 Port Scanner")
        
        self.speed_widget = SpeedTestWidget()
        self.tab_widget.addTab(self.speed_widget, "⚡ Speed Test")
        
        layout.addWidget(self.tab_widget)
        
        # Footer
        footer = self.create_footer()
        layout.addWidget(footer)
        
    def create_header(self):
        header_frame = QFrame()
        header_frame.setFixedHeight(80)
        header_frame.setObjectName("headerFrame")
        
        layout = QHBoxLayout(header_frame)
        
        # Title
        title = QLabel("Network Diagnostic Tools")
        title.setObjectName("titleLabel")
        title.setFont(QFont("Arial", 24, QFont.Bold))
        
        # Status indicator
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")
        
        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self.status_label)
        
        return header_frame
        
    def create_footer(self):
        footer_frame = QFrame()
        footer_frame.setFixedHeight(30)
        footer_frame.setObjectName("footerFrame")
        
        layout = QHBoxLayout(footer_frame)
        
        footer_label = QLabel("Network Tools v1.0 - Modern Network Diagnostics")
        footer_label.setObjectName("footerLabel")
        
        layout.addWidget(footer_label)
        layout.addStretch()
        
        return footer_frame
        
    def apply_theme(self):
        theme = ModernTheme()
        self.setStyleSheet(theme.get_stylesheet())
        
    def update_status(self, message):
        self.status_label.setText(message)