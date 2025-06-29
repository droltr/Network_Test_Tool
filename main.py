import sys
import os
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
        sys.exit(app.exec_())
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()