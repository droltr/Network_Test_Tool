"""Design tokens, bundled fonts and the application stylesheet (One Dark based redesign)."""
import os

from PyQt5.QtGui import QColor, QFont, QFontDatabase

from utils.paths import resource_path


class Colors:
    CHROME = "#1b1e24"
    BG_SUNKEN = "#21252b"
    BG = "#282c34"
    SURFACE = "#2c313a"
    SURFACE_2 = "#323842"
    BORDER = "#3a404b"
    ROW_DIVIDER = "#2c313a"

    TEXT = "#abb2bf"
    TEXT_STRONG = "#dcdfe4"
    TEXT_MUTED = "#8b929e"
    TEXT_FAINT = "#5c6370"

    BLUE = "#61afef"
    BLUE_HOVER = "#528bcc"
    BLUE_PRESSED = "#4078b3"
    GREEN = "#98c379"
    YELLOW = "#e5c07b"
    RED = "#e06c75"
    PURPLE = "#c678dd"


def rgba(hex_color, alpha):
    """CSS rgba() string for a token at the given opacity (0..1)."""
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def qcolor(hex_color, alpha=1.0):
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


UI_FAMILY = "IBM Plex Sans"
MONO_FAMILY = "JetBrains Mono"
_UI_FALLBACKS = ["Segoe UI", "Noto Sans", "DejaVu Sans"]
_MONO_FALLBACKS = ["Consolas", "DejaVu Sans Mono", "Noto Sans Mono", "Monospace"]

_WEIGHTS = {400: QFont.Normal, 500: QFont.Medium, 600: QFont.DemiBold, 700: QFont.Bold}


def load_fonts():
    """Register the bundled TTFs and pick fallbacks when they are missing."""
    global UI_FAMILY, MONO_FAMILY
    font_dir = resource_path("assets", "fonts")
    if os.path.isdir(font_dir):
        for name in sorted(os.listdir(font_dir)):
            if name.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(font_dir, name))

    families = set(QFontDatabase().families())
    if UI_FAMILY not in families:
        UI_FAMILY = next((f for f in _UI_FALLBACKS if f in families), QFont().defaultFamily())
    if MONO_FAMILY not in families:
        MONO_FAMILY = next((f for f in _MONO_FALLBACKS if f in families), "Monospace")


def _font(family, px, weight):
    font = QFont(family)
    # Point sizes keep fractional design sizes (12.5px) and scale with the screen DPI
    font.setPointSizeF(px * 0.75)
    font.setWeight(_WEIGHTS.get(weight, QFont.Normal))
    font.setHintingPreference(QFont.PreferNoHinting)
    return font


def ui_font(px=12.5, weight=400):
    return _font(UI_FAMILY, px, weight)


def mono_font(px=12, weight=400):
    font = _font(MONO_FAMILY, px, weight)
    font.setStyleHint(QFont.Monospace)
    return font


def section_font(px=10.5):
    font = ui_font(px, 600)
    font.setLetterSpacing(QFont.AbsoluteSpacing, px * 0.07)
    return font


class ModernTheme:
    def get_stylesheet(self):
        c = Colors
        chevron = resource_path("assets", "icons", "chevron-down.svg").replace("\\", "/")
        check = resource_path("assets", "icons", "check.svg").replace("\\", "/")
        return f"""
        QMainWindow, QWidget#appRoot, QWidget#pageBody, QStackedWidget#pages {{
            background-color: {c.BG};
        }}
        QWidget {{
            color: {c.TEXT};
        }}
        QLabel {{
            background: transparent;
        }}
        QScrollArea, QScrollArea > QWidget > QWidget {{
            background: transparent;
            border: none;
        }}
        QToolTip {{
            background-color: {c.SURFACE_2};
            color: {c.TEXT_STRONG};
            border: 1px solid {c.BORDER};
            padding: 4px 6px;
        }}

        /* Menu bar */
        QMenuBar {{
            background-color: {c.CHROME};
            color: {c.TEXT_MUTED};
            border-bottom: 1px solid {c.BORDER};
        }}
        QMenuBar::item {{
            background: transparent;
            padding: 4px 10px;
        }}
        QMenuBar::item:selected {{
            background-color: {c.SURFACE_2};
            color: {c.TEXT_STRONG};
        }}
        QMenu {{
            background-color: {c.SURFACE};
            border: 1px solid {c.BORDER};
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 18px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {c.SURFACE_2};
            color: {c.TEXT_STRONG};
        }}

        /* Shell */
        QFrame#sidebar {{
            background-color: {c.BG_SUNKEN};
            border: none;
            border-right: 1px solid {c.BORDER};
        }}
        QFrame#navItem {{
            background: transparent;
            border-radius: 6px;
        }}
        QFrame#navItem:hover {{
            background-color: {c.SURFACE_2};
        }}
        QFrame#navItem[active="true"] {{
            background-color: {c.SURFACE};
        }}
        QFrame#statusCard {{
            background-color: {c.SURFACE};
            border: 1px solid {c.BORDER};
            border-radius: 8px;
        }}
        QFrame#statusCard[status="local"] {{
            border-color: {rgba(c.YELLOW, 0.55)};
        }}
        QFrame#statusCard[status="offline"] {{
            border-color: {rgba(c.RED, 0.55)};
        }}
        QFrame#pageHeader {{
            background-color: {c.BG};
            border: none;
            border-bottom: 1px solid {c.BORDER};
        }}

        /* Cards */
        QFrame[card="card"] {{
            background-color: {c.SURFACE};
            border: 1px solid {c.BORDER};
            border-radius: 9px;
        }}
        QFrame[card="sunken"] {{
            background-color: {c.BG_SUNKEN};
            border: 1px solid {c.BORDER};
            border-radius: 9px;
        }}
        QFrame[card="dashed"] {{
            background: transparent;
            border: 1px dashed {c.BORDER};
            border-radius: 9px;
        }}
        QFrame[card="error"] {{
            background-color: {c.SURFACE};
            border: 1px solid {rgba(c.RED, 0.5)};
            border-radius: 9px;
        }}
        QFrame[card="issues"] {{
            background-color: {c.SURFACE};
            border: 1px solid {rgba(c.RED, 0.55)};
            border-radius: 9px;
        }}
        QFrame[card="banner"] {{
            background-color: {rgba(c.RED, 0.08)};
            border: 1px solid {rgba(c.RED, 0.5)};
            border-radius: 9px;
        }}
        QFrame[card="checks"] {{
            background-color: {c.BG_SUNKEN};
            border: none;
            border-radius: 6px;
        }}
        QFrame[card="note"] {{
            background-color: {c.BG_SUNKEN};
            border: none;
            border-radius: 7px;
        }}
        QFrame[divider="h"] {{
            background-color: {c.BORDER};
            border: none;
            max-height: 1px;
            min-height: 1px;
        }}
        QFrame[row="true"] {{
            background: transparent;
            border: none;
            border-top: 1px solid {c.BORDER};
        }}
        QFrame[row="true"][state="running"] {{
            background-color: {c.SURFACE_2};
        }}
        QFrame[row="true"][state="failed"] {{
            background-color: {rgba(c.RED, 0.07)};
        }}
        QFrame[cell="true"] {{
            background: transparent;
            border: none;
            border-left: 1px solid {c.BORDER};
        }}
        QFrame[cell="true"][first="true"] {{
            border-left: none;
        }}
        QFrame[cell="true"][active="true"] {{
            background-color: {c.SURFACE_2};
            border-bottom: 2px solid {c.BLUE};
        }}

        /* Buttons */
        QPushButton {{
            border-radius: 6px;
            padding: 0 14px;
            background-color: {c.SURFACE_2};
            color: {c.TEXT_STRONG};
            border: 1px solid {c.BORDER};
        }}
        QPushButton:hover {{
            background-color: #383f4a;
        }}
        QPushButton:pressed {{
            background-color: {c.BORDER};
        }}
        QPushButton[variant="primary"] {{
            background-color: {c.BLUE};
            color: {c.CHROME};
            border: none;
        }}
        QPushButton[variant="primary"]:hover {{
            background-color: {c.BLUE_HOVER};
        }}
        QPushButton[variant="primary"]:pressed {{
            background-color: {c.BLUE_PRESSED};
        }}
        QPushButton[variant="ghost"] {{
            background-color: {rgba(c.BLUE, 0.1)};
            color: {c.BLUE};
            border: none;
        }}
        QPushButton[variant="ghost"]:hover {{
            background-color: {rgba(c.BLUE, 0.18)};
        }}
        QPushButton[variant="stop"] {{
            background: transparent;
            color: {c.RED};
            border: 1px solid {c.RED};
        }}
        QPushButton[variant="stop"]:hover {{
            background-color: {rgba(c.RED, 0.1)};
        }}
        QPushButton[variant="danger"] {{
            background-color: {c.RED};
            color: {c.CHROME};
            border: none;
        }}
        QPushButton[variant="danger"]:hover {{
            background-color: #c95d66;
        }}
        QPushButton[variant="warn"] {{
            background: transparent;
            color: {c.YELLOW};
            border: 1px solid {rgba(c.YELLOW, 0.6)};
        }}
        QPushButton[variant="warn"]:hover {{
            background-color: {rgba(c.YELLOW, 0.1)};
        }}
        QPushButton[variant="link"] {{
            background: transparent;
            color: {c.BLUE};
            border: none;
            padding: 0 4px;
            text-align: left;
        }}
        QPushButton[variant="link"]:hover {{
            color: {c.TEXT_STRONG};
        }}
        QPushButton[variant="chip"] {{
            background-color: {c.SURFACE_2};
            color: {c.TEXT};
            border: none;
            border-radius: 11px;
            padding: 0 11px;
        }}
        QPushButton[variant="chip"]:checked {{
            background-color: {c.BLUE};
            color: {c.CHROME};
        }}
        QPushButton[variant="tab"] {{
            background: transparent;
            color: {c.TEXT_MUTED};
            border: none;
            border-radius: 0;
            border-bottom: 2px solid transparent;
            padding: 0 2px;
        }}
        QPushButton[variant="tab"]:hover {{
            color: {c.TEXT_STRONG};
        }}
        QPushButton[variant="tab"]:checked {{
            color: {c.TEXT_STRONG};
            border-bottom: 2px solid {c.BLUE};
        }}
        QPushButton:disabled, QPushButton[variant="primary"]:disabled {{
            background-color: {c.BORDER};
            color: {c.TEXT_FAINT};
            border: none;
        }}

        /* Inputs */
        QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
            background-color: {c.BG_SUNKEN};
            color: {c.TEXT_STRONG};
            border: 1px solid {c.BORDER};
            border-radius: 6px;
            padding: 0 10px;
            selection-background-color: {rgba(c.BLUE, 0.35)};
        }}
        QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{
            border: 2px solid {c.BLUE};
            padding: 0 9px;
        }}
        QLineEdit[error="true"] {{
            border: 2px solid {c.RED};
            padding: 0 9px;
        }}
        QLineEdit:read-only {{
            color: {c.TEXT};
        }}
        QLineEdit:read-only:focus {{
            border: 1px solid {c.BORDER};
            padding: 0 10px;
        }}
        QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
        QSpinBox::up-button, QSpinBox::down-button {{
            width: 0;
            border: none;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 26px;
        }}
        QComboBox::down-arrow {{
            image: url("{chevron}");
            width: 10px;
            height: 6px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {c.SURFACE};
            color: {c.TEXT_STRONG};
            border: 1px solid {c.BORDER};
            selection-background-color: {c.SURFACE_2};
            outline: none;
            padding: 4px;
        }}
        QCheckBox {{
            spacing: 7px;
            background: transparent;
        }}
        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border-radius: 3px;
            border: 1px solid {c.BORDER};
            background-color: {c.BG_SUNKEN};
        }}
        QCheckBox::indicator:checked {{
            background-color: {c.BLUE};
            border: 1px solid {c.BLUE};
            image: url("{check}");
        }}

        /* Progress */
        QProgressBar {{
            background-color: {c.BG_SUNKEN};
            border: none;
            border-radius: 2px;
            max-height: 4px;
            min-height: 4px;
        }}
        QProgressBar::chunk {{
            background-color: {c.BLUE};
            border-radius: 2px;
        }}
        QProgressBar[tone="purple"]::chunk {{
            background-color: {c.PURPLE};
        }}

        /* Tables */
        QTableWidget {{
            background-color: {c.BG_SUNKEN};
            alternate-background-color: {c.BG_SUNKEN};
            border: 1px solid {c.BORDER};
            border-radius: 9px;
            gridline-color: transparent;
            outline: none;
            selection-background-color: {rgba(c.BLUE, 0.08)};
            selection-color: {c.TEXT_STRONG};
        }}
        QTableWidget[embedded="true"] {{
            border: none;
            border-radius: 0;
            background: transparent;
        }}
        QTableWidget::item {{
            border-bottom: 1px solid {c.ROW_DIVIDER};
            padding-left: 14px;
        }}
        QHeaderView, QHeaderView::section {{
            background-color: {c.BG_SUNKEN};
            color: {c.TEXT_MUTED};
            border: none;
        }}
        QHeaderView::section {{
            border-bottom: 1px solid {c.BORDER};
            padding-left: 14px;
            height: 30px;
        }}
        QTableCornerButton::section {{
            background: transparent;
            border: none;
        }}

        /* Text panes */
        QPlainTextEdit {{
            background-color: {c.BG_SUNKEN};
            color: {c.TEXT};
            border: none;
            selection-background-color: {rgba(c.BLUE, 0.3)};
        }}

        /* Scroll bars */
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {c.BORDER};
            border-radius: 3px;
            min-height: 24px;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 10px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {c.BORDER};
            border-radius: 3px;
            min-width: 24px;
        }}
        QScrollBar::add-line, QScrollBar::sub-line,
        QScrollBar::add-page, QScrollBar::sub-page {{
            background: none;
            border: none;
            width: 0;
            height: 0;
        }}

        QMessageBox {{
            background-color: {c.SURFACE};
        }}
        QMessageBox QLabel {{
            color: {c.TEXT_STRONG};
        }}
        QMessageBox QPushButton {{
            min-width: 72px;
            min-height: 28px;
        }}
        """
