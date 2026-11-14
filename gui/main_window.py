from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QMessageBox, QAction,
                             QActionGroup, QApplication)

from .pages.dashboard import DashboardPage
from .pages.diagnose import DiagnosePage
from .pages.port_scanner import PortScannerPage
from .pages.speed_test import SpeedTestPage
from .pages.advanced import AdvancedPage
from .pages.iperf import IperfPage
from .pages.game import GamePage
from .pages.office import OfficePage
from .pages.health import HealthPage
from .pages.troubleshooter import TroubleshooterPage
from .styles.modern_theme import (ModernTheme, THEMES, SYSTEM_CHOICE, apply_theme, load_fonts, ui_font,
                                  resolve_theme)
from .widgets.sidebar import Sidebar, AppMark

def _settings():
    return QSettings("NetworkTools", "NetworkTestTool")


class MainWindow(QMainWindow):
    # The window that is currently shown; switching the theme replaces it in the same process
    current = None

    def __init__(self, theme_choice=None):
        """theme_choice is the saved choice ("system" or a theme key); None reads the saved setting."""
        super().__init__()
        if theme_choice is None:
            theme_choice = _settings().value("theme", SYSTEM_CHOICE, type=str)
        self.theme_choice = theme_choice if theme_choice in THEMES else SYSTEM_CHOICE
        self.setWindowTitle("Network Test Tool")
        self.resize(1280, 800)
        self.setMinimumSize(1200, 760)
        self.setWindowIcon(self.app_icon())
        self.create_menu_bar()
        self.setup_ui()
        self.apply_theme()
        self.show_page("dashboard")
        MainWindow.current = self

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
            "game": GamePage(),
            "office": OfficePage(),
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
        logs.update(self.pages["game"].session_logs())
        logs.update(self.pages["office"].session_logs())
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

        # View menu: theme choice, applied at once (the window is rebuilt in this process)
        view_menu = menu_bar.addMenu("View")
        theme_menu = view_menu.addMenu("Theme")
        group = QActionGroup(self)
        self.theme_actions = {}
        choices = {SYSTEM_CHOICE: "Follow system", **THEMES}
        for key, title in choices.items():
            action = QAction(title, self, checkable=True)
            action.setChecked(key == self.theme_choice)
            action.triggered.connect(lambda _=False, k=key: self.choose_theme(k))
            group.addAction(action)
            theme_menu.addAction(action)
            self.theme_actions[key] = action

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

    def busy_pages(self):
        """Titles of the pages that have work running (a test, a recording, a server)."""
        return [key for key, page in self.pages.items() if page.running]

    def choose_theme(self, choice):
        if choice == self.theme_choice:
            return
        if self.busy_pages():
            answer = QMessageBox.question(
                self, "Theme", "A test is running. Switching the theme stops it. Switch now?")
            if answer != QMessageBox.Yes:
                self.theme_actions[self.theme_choice].setChecked(True)
                return
        _settings().setValue("theme", choice)
        self.switch_theme(choice)

    def switch_theme(self, choice):
        """Replace this window with a new one in the new theme, in the same process.

        Widgets read the colour tokens when they are built, so the window cannot be restyled
        in place. The old window is closed first (its pages stop their threads and timers),
        then the tokens change and a new window takes over its geometry and page.
        """
        app = QApplication.instance()
        geometry = self.saveGeometry()
        state = self.saveState()
        page_key = next((k for k, p in self.pages.items() if p is self.stack.currentWidget()), "dashboard")
        quit_on_close = app.quitOnLastWindowClosed()
        app.setQuitOnLastWindowClosed(False)   # closing the old window must not end the app
        try:
            self.close()
            apply_theme(resolve_theme(choice))
            load_fonts()
            app.setFont(ui_font(12.5))
            window = MainWindow(choice)
            window.restoreGeometry(geometry)
            window.restoreState(state)
            window.show_page(page_key)
            MainWindow.current = window
            window.show()
        finally:
            app.setQuitOnLastWindowClosed(quit_on_close)
        self.deleteLater()
        return window

    def show_help(self, topic):
        from .dialogs.help import HelpDialog
        dialog = HelpDialog(topic, self)
        dialog.show()

    def show_about_dialog(self):
        from .dialogs.help import AboutDialog
        AboutDialog(self).exec_()
