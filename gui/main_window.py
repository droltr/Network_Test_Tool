import sys

from PyQt5.QtCore import QProcess, QSettings
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QMessageBox, QAction,
                             QActionGroup, QApplication)

from .pages.dashboard import DashboardPage
from .pages.diagnose import DiagnosePage
from .pages.port_scanner import PortScannerPage
from .pages.speed_test import SpeedTestPage
from .pages.advanced import AdvancedPage
from .pages.iperf import IperfPage
from .pages.health import HealthPage
from .pages.troubleshooter import TroubleshooterPage
from .styles.modern_theme import ModernTheme, Theme, THEMES
from .widgets.sidebar import Sidebar, AppMark

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Test Tool")
        self.resize(1280, 800)
        self.setMinimumSize(1200, 760)
        self.setWindowIcon(self.app_icon())
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

        # View menu: theme choice, applied on the next start
        view_menu = menu_bar.addMenu("View")
        theme_menu = view_menu.addMenu("Theme")
        group = QActionGroup(self)
        for key, title in THEMES.items():
            action = QAction(title, self, checkable=True)
            action.setChecked(key == Theme.NAME)
            action.triggered.connect(lambda _=False, k=key: self.choose_theme(k))
            group.addAction(action)
            theme_menu.addAction(action)

        # Help menu
        help_menu = menu_bar.addMenu("Help")

        guide_action = QAction("User guide", self)
        guide_action.setShortcut("F1")
        guide_action.triggered.connect(lambda: self.show_help("User-Guide-Network-Status.md"))
        purpose_action = QAction("Purpose of this tool", self)
        purpose_action.triggered.connect(lambda: self.show_help("Home.md"))
        help_menu.addAction(purpose_action)
        help_menu.addAction(guide_action)
        help_menu.addSeparator()
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    @staticmethod
    def app_icon():
        icon = QIcon()
        for size in (16, 32, 48, 64, 128, 256):
            mark = AppMark(size, ground="#141414")
            pixmap = QPixmap(size, size)
            mark.render(pixmap)
            icon.addPixmap(pixmap)
        return icon

    def choose_theme(self, key):
        if key == Theme.NAME:
            return
        QSettings("NetworkTools", "NetworkTestTool").setValue("theme", key)
        answer = QMessageBox.question(self, "Theme", f"{THEMES[key]} is used from the next start. Restart now?")
        if answer == QMessageBox.Yes:
            self.close()
            QProcess.startDetached(sys.executable, sys.argv)
            QApplication.instance().quit()

    def show_help(self, topic):
        from .dialogs.help import HelpDialog
        dialog = HelpDialog(topic, self)
        dialog.show()

    def show_about_dialog(self):
        from .dialogs.help import AboutDialog
        AboutDialog(self).exec_()
