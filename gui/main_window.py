from PyQt5.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QMessageBox, QAction

from version import __version__
from .pages.dashboard import DashboardPage
from .pages.diagnose import DiagnosePage
from .pages.port_scanner import PortScannerPage
from .pages.speed_test import SpeedTestPage
from .pages.advanced import AdvancedPage
from .pages.iperf import IperfPage
from .pages.health import HealthPage
from .pages.troubleshooter import TroubleshooterPage
from .styles.modern_theme import ModernTheme
from .widgets.sidebar import Sidebar

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Test Tool")
        self.resize(1280, 800)
        self.setMinimumSize(1200, 760)
        self.create_menu_bar()
        self.setup_ui()
        self.apply_theme()
        self.show_page("dashboard")

    def setup_ui(self):
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.page_selected.connect(self.show_page)
        self.sidebar.ask_ai.connect(self.open_ask_ai)
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pages")
        layout.addWidget(self.stack, 1)

        self.pages = {
            "dashboard": DashboardPage(),
            "diagnose": DiagnosePage(),
            "port": PortScannerPage(),
            "speed": SpeedTestPage(),
            "iperf": IperfPage(),
            "health": HealthPage(),
            "advanced": AdvancedPage(),
            "trouble": TroubleshooterPage(),
        }
        for key, page in self.pages.items():
            self.stack.addWidget(page)
            page.running_changed.connect(lambda running, k=key: self.sidebar.items[k].set_running(running))
            page.navigate.connect(self.navigate)

        dashboard = self.pages["dashboard"]
        dashboard.overall_status.connect(self.sidebar.status_card.set_status)
        dashboard.issues_changed.connect(self.sidebar.items["dashboard"].set_count)

    def show_page(self, key):
        self.stack.setCurrentWidget(self.pages[key])
        self.sidebar.set_active(key)

    def navigate(self, key, payload):
        self.show_page(key)
        self.pages[key].handle_request(payload or {})

    def session_logs(self):
        """Logs from this session that can go into the AI package."""
        logs = {}
        trouble_log = self.pages["trouble"].log.plain_text().strip()
        if trouble_log:
            logs["Troubleshooter log"] = trouble_log
        logs.update(self.pages["health"].session_logs())
        return logs

    def open_ask_ai(self):
        from .dialogs.ask_ai import AskAiDialog
        AskAiDialog(self.session_logs, self).exec_()

    def apply_theme(self):
        self.setStyleSheet(ModernTheme().get_stylesheet())

    def closeEvent(self, event):
        # Call cleanup for all pages that might have running threads or timers
        for page in self.pages.values():
            page.cleanup()
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

    def show_about_dialog(self):
        QMessageBox.about(self, "About Network Test Tool",
                          f"""<b>Network Test Tool v{__version__}</b>
                          <p>A modern network diagnostic and troubleshooting utility.</p>
                          <p>Developed by droltr.</p>
                          <p>Includes speedtest-cli by Matt Martz (Apache 2.0), IBM Plex Sans and
                          JetBrains Mono (SIL OFL 1.1). Built with PyQt5 (GPL v3) and psutil (BSD).
                          See THIRD_PARTY_NOTICES.md.</p>
                          <p><a href='https://github.com/droltr/Network_Test_Tool'>GitHub Repository</a></p>""")
