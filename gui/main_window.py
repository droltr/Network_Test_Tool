import sys
import webbrowser
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QTabWidget, QLabel, QFrame, QPushButton, QTextEdit,
                            QLineEdit, QSpinBox, QProgressBar, QGroupBox, QGridLayout,
                            QMessageBox, QComboBox, QListWidget, QSplitter, QApplication, QAction)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QPalette, QColor, QIcon
from .components.network_status import NetworkStatusWidget
from .components.ping_test import PingTestWidget
from .components.port_scanner import PortScannerWidget
from .components.speed_test import SpeedTestWidget
from .components.auto_test import AutoTestWidget
from .styles.modern_theme import ModernTheme

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Diagnostic Tools")
        self.setGeometry(100, 100, 1200, 800)
        self.create_menu_bar()
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
        self.status_widget.overall_status_update.connect(self.update_overall_status)
        self.tab_widget.addTab(self.status_widget, "🌐 Network Status")
        
        self.ping_widget = PingTestWidget()
        self.tab_widget.addTab(self.ping_widget, "📡 Ping Test")
        
        self.port_widget = PortScannerWidget()
        self.tab_widget.addTab(self.port_widget, "🔍 Port Scanner")
        
        self.speed_widget = SpeedTestWidget()
        self.tab_widget.addTab(self.speed_widget, "⚡ Speed Test")

        self.auto_test_widget = AutoTestWidget()
        self.tab_widget.addTab(self.auto_test_widget, "🤖 Automated Test")
        
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

        exit_button = QPushButton("Exit")
        exit_button.clicked.connect(self.close)
        
        layout.addWidget(footer_label)
        layout.addStretch()
        layout.addWidget(exit_button)
        
        return footer_frame
        
    def apply_theme(self):
        theme = ModernTheme()
        self.setStyleSheet(theme.get_stylesheet())
        
    def update_status(self, message):
        self.status_label.setText(message)

    def update_overall_status(self, is_ok):
        if is_ok:
            self.status_label.setText("OK")
            self.status_label.setStyleSheet("color: #A3BE8C;") # Green
        else:
            self.status_label.setText("Problem Detected")
            self.status_label.setStyleSheet("color: #BF616A;") # Red

    def closeEvent(self, event):
        # Call cleanup for all widgets that might have running threads or timers
        self.status_widget.cleanup()
        self.ping_widget.cleanup()
        self.port_widget.cleanup()
        self.speed_widget.cleanup()
        self.auto_test_widget.cleanup()
        super().closeEvent(event)

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        help_menu = menu_bar.addMenu("Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        github_action = QAction("GitHub", self)
        github_action.triggered.connect(self.open_github_link)
        help_menu.addAction(github_action)

    def show_about_dialog(self):
        QMessageBox.about(self, "About Network Diagnostic Tools",
                          """<b>Network Diagnostic Tools v1.0</b>
                          <p>A modern network diagnostic and troubleshooting utility.</p>
                          <p>Developed by droltr.</p>""")

    def open_github_link(self):
        webbrowser.open("https://github.com/droltr")