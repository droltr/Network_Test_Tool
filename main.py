import sys
import os

"""
Network Test Tool
Version: 0.5
GitHub: https://github.com/droltr/Network_Test_Tool
"""

# Add the src directory to Python path
src_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, src_path)

from gui.main_window import MainWindow
from PyQt5.QtWidgets import QApplication

def main():
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        print("Application started successfully!")
        print("Window is displayed. Close the window to exit.")
        sys.exit(app.exec_())
    except Exception as e:
        from PyQt5.QtWidgets import QMessageBox
        import traceback
        error_msg = f"An error occurred: {e}\n\n" + traceback.format_exc()
        
        # Log the error
        with open("crash_log.txt", "a") as f:
            f.write(f"\n\n--- Crash at {sys.argv[0]} ---\n")
            f.write(error_msg)
            
        app = QApplication.instance() or QApplication(sys.argv)
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Application Error")
        msg.setText("A critical error occurred. Please check crash_log.txt for details.")
        msg.setDetailedText(error_msg)
        msg.exec_()
        sys.exit(1)

if __name__ == "__main__":
    main()