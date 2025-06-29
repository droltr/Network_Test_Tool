
class ModernTheme:
    def __init__(self):
        self.primary_color = "#2E3440"
        self.secondary_color = "#3B4252"
        self.accent_color = "#5E81AC"
        self.success_color = "#A3BE8C"
        self.warning_color = "#EBCB8B"
        self.error_color = "#BF616A"
        self.text_color = "#ECEFF4"
        self.background_color = "#2E3440"
        
    def get_stylesheet(self):
        return f"""
        QMainWindow {{
            background-color: {self.background_color};
            color: {self.text_color};
        }}
        
        QWidget {{
            background-color: {self.background_color};
            color: {self.text_color};
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 10pt;
        }}
        
        #headerFrame {{
            background-color: {self.secondary_color};
            border-bottom: 2px solid {self.accent_color};
        }}
        
        #footerFrame {{
            background-color: {self.secondary_color};
            border-top: 1px solid {self.accent_color};
        }}
        
        #titleLabel {{
            color: {self.text_color};
            font-size: 24pt;
            font-weight: bold;
        }}
        
        #statusLabel {{
            color: {self.success_color};
            font-size: 12pt;
            font-weight: bold;
        }}
        
        #footerLabel {{
            color: #88C0D0;
            font-size: 9pt;
        }}
        
        QTabWidget::pane {{
            border: 1px solid {self.accent_color};
            background-color: {self.background_color};
        }}
        
        QTabBar::tab {{
            background-color: {self.secondary_color};
            color: {self.text_color};
            padding: 10px 20px;
            margin: 2px;
            border-radius: 5px;
        }}
        
        QTabBar::tab:selected {{
            background-color: {self.accent_color};
            color: white;
        }}
        
        QTabBar::tab:hover {{
            background-color: #4C566A;
        }}
        
        QPushButton {{
            background-color: {self.accent_color};
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 5px;
            font-weight: bold;
        }}
        
        QPushButton:hover {{
            background-color: #81A1C1;
        }}
        
        QPushButton:pressed {{
            background-color: #4C566A;
        }}
        
        QPushButton:disabled {{
            background-color: #4C566A;
            color: #6C7B7F;
        }}
        
        QLineEdit {{
            background-color: {self.secondary_color};
            border: 2px solid #4C566A;
            border-radius: 5px;
            padding: 8px;
            color: {self.text_color};
        }}
        
        QLineEdit:focus {{
            border-color: {self.accent_color};
        }}
        
        QTextEdit {{
            background-color: {self.secondary_color};
            border: 2px solid #4C566A;
            border-radius: 5px;
            padding: 10px;
            color: {self.text_color};
            font-family: 'Consolas', 'Courier New', monospace;
        }}
        
        QGroupBox {{
            font-weight: bold;
            border: 2px solid {self.accent_color};
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
        }}
        
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 10px 0 10px;
            color: {self.accent_color};
        }}
        
        QProgressBar {{
            border: 2px solid {self.accent_color};
            border-radius: 5px;
            text-align: center;
            background-color: {self.secondary_color};
        }}
        
        QProgressBar::chunk {{
            background-color: {self.success_color};
            border-radius: 3px;
        }}
        
        QListWidget {{
            background-color: {self.secondary_color};
            border: 2px solid #4C566A;
            border-radius: 5px;
            color: {self.text_color};
        }}
        
        QListWidget::item {{
            padding: 5px;
            border-bottom: 1px solid #4C566A;
        }}
        
        QListWidget::item:selected {{
            background-color: {self.accent_color};
        }}
        
        QComboBox {{
            background-color: {self.secondary_color};
            border: 2px solid #4C566A;
            border-radius: 5px;
            padding: 8px;
            color: {self.text_color};
        }}
        
        QComboBox:hover {{
            border-color: {self.accent_color};
        }}
        
        QComboBox::drop-down {{
            border: none;
        }}
        
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid {self.text_color};
        }}
        
        QSpinBox {{
            background-color: {self.secondary_color};
            border: 2px solid #4C566A;
            border-radius: 5px;
            padding: 8px;
            color: {self.text_color};
        }}
        
        QSpinBox:focus {{
            border-color: {self.accent_color};
        }}
        
        QLabel {{
            color: {self.text_color};
        }}
        
        .success {{
            color: {self.success_color};
        }}
        
        .warning {{
            color: {self.warning_color};
        }}
        
        .error {{
            color: {self.error_color};
        }}
        """