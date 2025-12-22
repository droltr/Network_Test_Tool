import sys
import webbrowser
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QTabWidget, QLabel, QFrame, QPushButton, QTextEdit,
                            QLineEdit, QSpinBox, QProgressBar, QGroupBox, QGridLayout,
                            QMessageBox, QComboBox, QListWidget, QSplitter, QApplication, QAction, QSizePolicy)
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
        self.setWindowTitle("Network Test Tool")
        self.setGeometry(100, 100, 1400, 900)
        self.setMinimumSize(1200, 800)
        self.create_menu_bar()
        self.setup_ui()
        self.apply_theme()
        
    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = self.create_header()
        layout.addWidget(header)
        
        # Main content with tabs
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.North)
        
        # Add tabs
        self.status_widget = NetworkStatusWidget()
        self.status_widget.overall_status_update.connect(self.update_overall_status)
        self.tab_widget.addTab(self.status_widget, "Network Status")
        
        self.ping_widget = PingTestWidget()
        self.tab_widget.addTab(self.ping_widget, "Ping Test")
        
        self.port_widget = PortScannerWidget()
        self.tab_widget.addTab(self.port_widget, "Port Scanner")
        
        self.speed_widget = SpeedTestWidget()
        self.tab_widget.addTab(self.speed_widget, "Speed Test")

        self.auto_test_widget = AutoTestWidget()
        self.tab_widget.addTab(self.auto_test_widget, "Troubleshooter")
        
        layout.addWidget(self.tab_widget)
        
        # Footer
        footer = self.create_footer()
        layout.addWidget(footer)
        
    def create_header(self):
        header_frame = QFrame()
        header_frame.setFixedHeight(60)
        header_frame.setObjectName("headerFrame")
        
        layout = QHBoxLayout(header_frame)
        layout.setContentsMargins(25, 0, 25, 0)
        
        # Left: Title
        left_layout = QVBoxLayout()
        left_layout.setSpacing(0)
        title = QLabel("Network Test Tool")
        title.setObjectName("titleLabel")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        left_layout.addWidget(title)
        
        # Right: Round status indicator
        status_layout = QHBoxLayout()
        status_layout.setSpacing(10)
        
        self.status_text = QLabel("Offline")
        self.status_text.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.status_text.setStyleSheet("color: #e06c75;")
        
        self.status_indicator = QLabel("●")
        self.status_indicator.setObjectName("statusIndicator")
        self.status_indicator.setFont(QFont("Segoe UI", 32)) # Increased size
        self.status_indicator.setStyleSheet("color: #e06c75;")  # Red by default
        
        status_layout.addWidget(self.status_text)
        status_layout.addWidget(self.status_indicator)
        
        layout.addLayout(left_layout)
        layout.addStretch()
        layout.addLayout(status_layout)
        
        return header_frame
        
    def create_footer(self):
        footer_frame = QFrame()
        footer_frame.setFixedHeight(35)
        footer_frame.setObjectName("footerFrame")
        
        layout = QHBoxLayout(footer_frame)
        layout.setContentsMargins(25, 0, 25, 0)
        
        # Removed footer label as requested
        
        layout.addStretch()
        
        return footer_frame
        
    def apply_theme(self):
        theme = ModernTheme()
        self.setStyleSheet(theme.get_stylesheet())
        
    def update_status(self, message):
        self.status_label.setText(message)

    def update_overall_status(self, is_ok):
        # This updates the round indicator based on internet connectivity
        if is_ok:
            self.status_indicator.setStyleSheet("color: #98c379;")  # Green
            self.status_text.setText("Online")
            self.status_text.setStyleSheet("color: #98c379;")
        else:
            self.status_indicator.setStyleSheet("color: #e06c75;")  # Red
            self.status_text.setText("Offline")
            self.status_text.setStyleSheet("color: #e06c75;")

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

        # File menu
        file_menu = menu_bar.addMenu("File")
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Help menu
        help_menu = menu_bar.addMenu("Help")

        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        github_action = QAction("GitHub Repository", self)
        github_action.triggered.connect(self.open_github_link)
        help_menu.addAction(github_action)

    def show_about_dialog(self):
        QMessageBox.about(self, "About Network Test Tool",
                          """<b>Network Test Tool v0.5</b>
                          <p>A modern network diagnostic and troubleshooting utility.</p>
                          <p>Developed by droltr.</p>
                          <p><a href='https://github.com/droltr/Network_Test_Tool'>GitHub Repository</a></p>""")

    def open_github_link(self):
        webbrowser.open("https://github.com/droltr/Network_Test_Tool")