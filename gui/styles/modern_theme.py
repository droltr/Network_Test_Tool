
class ModernTheme:
    def __init__(self):
        # Professional dark theme with soft colors
        self.primary_color = "#1e2128"
        self.secondary_color = "#282c34"
        self.accent_color = "#61afef"
        self.success_color = "#98c379"
        self.warning_color = "#e5c07b"
        self.error_color = "#e06c75"
        self.text_color = "#abb2bf"
        self.text_light = "#5c6370"
        self.background_color = "#282c34"
        self.border_color = "#3e4451"
        
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
            font-size: 9pt;
        }}
        
        #headerFrame {{
            background-color: {self.primary_color};
            border-bottom: 1px solid {self.border_color};
        }}
        
        #footerFrame {{
            background-color: {self.primary_color};
            border-top: 1px solid {self.border_color};
        }}
        
        #titleLabel {{
            color: {self.text_color};
            font-size: 16pt;
            font-weight: bold;
        }}
        
        #versionLabel {{
            color: {self.text_light};
            font-size: 8pt;
        }}
        
        #statusLabel {{
            color: {self.success_color};
            font-size: 10pt;
            font-weight: 500;
        }}
        
        #footerLabel {{
            color: {self.text_light};
            font-size: 8pt;
        }}
        
        #exitButton {{
            background-color: {self.error_color};
            color: white;
            border: none;
            border-radius: 4px;
            font-weight: 500;
            font-size: 9pt;
        }}
        
        #exitButton:hover {{
            background-color: #d05d68;
        }}
        
        QMenuBar {{
            background-color: {self.primary_color};
            color: {self.text_color};
            border-bottom: 1px solid {self.border_color};
            padding: 2px;
        }}
        
        QMenuBar::item {{
            padding: 6px 12px;
            background-color: transparent;
            color: {self.text_color};
        }}
        
        QMenuBar::item:selected {{
            background-color: {self.border_color};
            color: {self.accent_color};
        }}
        
        QMenuBar::item:pressed {{
            background-color: {self.border_color};
        }}
        
        QMenu {{
            background-color: {self.secondary_color};
            color: {self.text_color};
            border: 1px solid {self.border_color};
            padding: 5px;
        }}
        
        QMenu::item {{
            padding: 8px 25px 8px 20px;
            background-color: transparent;
        }}
        
        QMenu::item:selected {{
            background-color: {self.accent_color};
            color: white;
        }}
        
        QTabWidget::pane {{
            border: 1px solid {self.border_color};
            background-color: {self.background_color};
            border-radius: 0px;
            top: -1px;
        }}
        
        QTabBar::tab {{
            background-color: {self.primary_color};
            color: {self.text_color};
            padding: 10px 20px;
            margin-right: 2px;
            border: 1px solid {self.border_color};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            font-weight: 500;
            min-width: 100px;
        }}
        
        QTabBar::tab:selected {{
            background-color: {self.background_color};
            color: {self.accent_color};
            font-weight: 600;
            border-bottom: 2px solid {self.accent_color};
        }}
        
        QTabBar::tab:hover {{
            background-color: {self.secondary_color};
            color: {self.accent_color};
        }}
        
        QPushButton {{
            background-color: {self.accent_color};
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            font-weight: 500;
            font-size: 9pt;
        }}
        
        QPushButton:hover {{
            background-color: #528bcc;
        }}
        
        QPushButton:pressed {{
            background-color: #4078b3;
        }}
        
        QPushButton:disabled {{
            background-color: {self.border_color};
            color: {self.text_light};
        }}
        
        QLineEdit {{
            background-color: {self.primary_color};
            border: 1px solid {self.border_color};
            border-radius: 6px;
            padding: 10px;
            color: {self.text_color};
            font-size: 9pt;
        }}
        
        QLineEdit:focus {{
            border: 2px solid {self.accent_color};
            padding: 9px;
        }}
        
        QTextEdit {{
            background-color: {self.primary_color};
            border: 1px solid {self.border_color};
            border-radius: 6px;
            padding: 10px;
            color: {self.text_color};
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 9pt;
        }}
        
        QGroupBox {{
            font-weight: 600;
            font-size: 10pt;
            border: 1px solid {self.border_color};
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 15px;
            background-color: transparent;
        }}
        
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 15px;
            padding: 0 10px 0 10px;
            color: {self.text_color};
        }}
        
        QProgressBar {{
            border: 1px solid {self.border_color};
            border-radius: 6px;
            text-align: center;
            background-color: {self.primary_color};
            height: 24px;
            color: {self.text_color};
        }}
        
        QProgressBar::chunk {{
            background-color: {self.accent_color};
            border-radius: 5px;
        }}
        
        QListWidget {{
            background-color: {self.primary_color};
            border: 1px solid {self.border_color};
            border-radius: 6px;
            color: {self.text_color};
            padding: 5px;
        }}
        
        QListWidget::item {{
            padding: 8px;
            border-bottom: 1px solid {self.border_color};
            border-radius: 4px;
        }}
        
        QListWidget::item:selected {{
            background-color: {self.accent_color};
            color: white;
        }}
        
        QListWidget::item:hover {{
            background-color: {self.secondary_color};
        }}
        
        QComboBox {{
            background-color: {self.primary_color};
            border: 1px solid {self.border_color};
            border-radius: 6px;
            padding: 10px;
            color: {self.text_color};
        }}
        
        QComboBox:hover {{
            border: 2px solid {self.accent_color};
            padding: 9px;
        }}
        
        QComboBox::drop-down {{
            border: none;
            padding-right: 10px;
        }}
        
        QComboBox::down-arrow {{
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid {self.text_color};
        }}
        
        QComboBox QAbstractItemView {{
            background-color: {self.secondary_color};
            border: 1px solid {self.border_color};
            color: {self.text_color};
            selection-background-color: {self.accent_color};
        }}
        
        QSpinBox {{
            background-color: {self.primary_color};
            border: 1px solid {self.border_color};
            border-radius: 6px;
            padding: 10px;
            color: {self.text_color};
        }}
        
        QSpinBox:focus {{
            border: 2px solid {self.accent_color};
            padding: 9px;
        }}
        
        QLabel {{
            color: {self.text_color};
            background: transparent;
        }}
        
        #adapterCard {{
            background-color: {self.primary_color};
            border: 1px solid {self.border_color};
            border-radius: 8px;
        }}
        
        #adapterCard:hover {{
            border-color: {self.accent_color};
        }}
        
        #statusHeader {{
            background-color: {self.primary_color};
            border-bottom: 1px solid {self.border_color};
        }}
        
        #statusFooter {{
            background-color: {self.primary_color};
            border-top: 1px solid {self.border_color};
        }}
        
        QScrollArea {{
            border: none;
            background-color: transparent;
        }}
        
        QScrollBar:vertical {{
            background-color: {self.primary_color};
            width: 10px;
            border-radius: 5px;
        }}
        
        QScrollBar::handle:vertical {{
            background-color: {self.border_color};
            border-radius: 5px;
            min-height: 20px;
        }}
        
        QScrollBar::handle:vertical:hover {{
            background-color: {self.accent_color};
        }}
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        
        QScrollBar:horizontal {{
            background-color: {self.primary_color};
            height: 10px;
            border-radius: 5px;
        }}
        
        QScrollBar::handle:horizontal {{
            background-color: {self.border_color};
            border-radius: 5px;
            min-width: 20px;
        }}
        
        QScrollBar::handle:horizontal:hover {{
            background-color: {self.accent_color};
        }}
        """