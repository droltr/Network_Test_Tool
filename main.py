import sys
import os

"""
Network Test Tool
GitHub: https://github.com/droltr/Network_Test_Tool
"""

# Add the src directory to Python path
src_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, src_path)

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from utils.paths import log_file_path


def main():
    # Crisp rendering on HiDPI screens
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    try:
        app.setApplicationName("Network Test Tool")
        app.setOrganizationName("NetworkTools")
        # Matches the .desktop file so Linux shells group the window correctly
        app.setDesktopFileName("network-test-tool")

        from PyQt5.QtCore import QSettings
        from gui.styles.modern_theme import apply_theme, load_fonts, ui_font, DEFAULT_THEME
        # The theme must be active before any widget is built; NTT_THEME overrides it for testing
        theme = os.environ.get("NTT_THEME") or QSettings("NetworkTools", "NetworkTestTool").value(
            "theme", DEFAULT_THEME, type=str)
        apply_theme(theme)
        load_fonts()
        app.setFont(ui_font(12.5))

        from gui.main_window import MainWindow
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        from PyQt5.QtWidgets import QMessageBox
        import traceback
        error_msg = f"An error occurred: {e}\n\n" + traceback.format_exc()
        crash_log = log_file_path("crash_log.txt")

        # Log the error
        with open(crash_log, "a") as f:
            f.write(f"\n\n--- Crash at {sys.argv[0]} ---\n")
            f.write(error_msg)

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Application Error")
        msg.setText(f"A critical error occurred. Please check {crash_log} for details.")
        msg.setDetailedText(error_msg)
        msg.exec_()
        sys.exit(1)


if __name__ == "__main__":
    main()
