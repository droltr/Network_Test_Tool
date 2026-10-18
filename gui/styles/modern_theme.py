"""Design tokens, bundled fonts and the application stylesheet.

Three themes share one set of token names: "onedark" (the original redesign) and the
Bauhaus themes "bauhaus-light" and "bauhaus-dark" (paper and ink with the primary
colours; status is shown by shape as well as colour). apply_theme() must run before any
widget is created, because widgets read the tokens when they are built.
"""
import os

from PyQt5.QtGui import QColor, QFont, QFontDatabase

from utils.paths import resource_path

THEMES = {
    "onedark": "One Dark",
    "bauhaus-light": "Bauhaus light",
    "bauhaus-dark": "Bauhaus dark",
}
DEFAULT_THEME = "bauhaus-light"

_PALETTES = {
    "onedark": dict(
        CHROME="#1b1e24", BG_SUNKEN="#21252b", BG="#282c34", SURFACE="#2c313a", SURFACE_2="#323842",
        BORDER="#3a404b", ROW_DIVIDER="#2c313a",
        TEXT="#abb2bf", TEXT_STRONG="#dcdfe4", TEXT_MUTED="#8b929e", TEXT_FAINT="#5c6370",
        BLUE="#61afef", BLUE_HOVER="#528bcc", BLUE_PRESSED="#4078b3",
        GREEN="#98c379", YELLOW="#e5c07b", RED="#e06c75", PURPLE="#c678dd",
        PRIMARY="#61afef", PRIMARY_HOVER="#528bcc", PRIMARY_PRESSED="#4078b3", ON_PRIMARY="#1b1e24",
        SERIES_DOWN="#61afef", SERIES_UP="#98c379",
        SIDEBAR_BG="#21252b", SIDEBAR_TEXT="#c8ccd4", SIDEBAR_MUTED="#8b929e", SIDEBAR_RULE="#3a404b",
        NAV_ACTIVE_BG="#2c313a", NAV_ACTIVE_TEXT="#dcdfe4", NAV_HOVER_BG="#323842", BUTTON_HOVER="#383f4a",
        HEADING_BADGE_BG="#3a404b", HEADING_BADGE_TEXT="#dcdfe4",
        ON_STATUS="#1b1e24",
    ),
    "bauhaus-light": dict(
        CHROME="#141414", BG_SUNKEN="#E7E0D2", BG="#F1ECE2", SURFACE="#F8F4EC", SURFACE_2="#E4DCCB",
        BORDER="#141414", ROW_DIVIDER="#D9D0BE",
        TEXT="#1E1C19", TEXT_STRONG="#141414", TEXT_MUTED="#4A463F", TEXT_FAINT="#6E685D",
        BLUE="#1D4E9E", BLUE_HOVER="#173F80", BLUE_PRESSED="#123266",
        GREEN="#1D4E9E", YELLOW="#B07F00", RED="#C8322A", PURPLE="#141414",
        PRIMARY="#141414", PRIMARY_HOVER="#2E2E2E", PRIMARY_PRESSED="#000000", ON_PRIMARY="#F1ECE2",
        SERIES_DOWN="#1D4E9E", SERIES_UP="#C8322A",
        SIDEBAR_BG="#141414", SIDEBAR_TEXT="#F1ECE2", SIDEBAR_MUTED="#B9B2A5", SIDEBAR_RULE="#3A3A3A",
        NAV_ACTIVE_BG="#C8322A", NAV_ACTIVE_TEXT="#FFFFFF", NAV_HOVER_BG="#2A2A2A", BUTTON_HOVER="#D9D0BE",
        HEADING_BADGE_BG="#F2B705", HEADING_BADGE_TEXT="#141414",
        ON_STATUS="#FFFFFF",
    ),
    "bauhaus-dark": dict(
        CHROME="#0B0B0B", BG_SUNKEN="#101010", BG="#1A1A1A", SURFACE="#222222", SURFACE_2="#2E2E2E",
        BORDER="#5A564E", ROW_DIVIDER="#2E2E2E",
        TEXT="#E4DCCB", TEXT_STRONG="#F1ECE2", TEXT_MUTED="#B9B2A5", TEXT_FAINT="#8F887B",
        BLUE="#6F9BE8", BLUE_HOVER="#8AB0F0", BLUE_PRESSED="#5A86D4",
        GREEN="#6F9BE8", YELLOW="#F2B705", RED="#F0584D", PURPLE="#F1ECE2",
        PRIMARY="#F1ECE2", PRIMARY_HOVER="#FFFFFF", PRIMARY_PRESSED="#D9D0BE", ON_PRIMARY="#141414",
        SERIES_DOWN="#6F9BE8", SERIES_UP="#F2B705",
        SIDEBAR_BG="#0B0B0B", SIDEBAR_TEXT="#F1ECE2", SIDEBAR_MUTED="#B9B2A5", SIDEBAR_RULE="#2E2E2E",
        NAV_ACTIVE_BG="#C8322A", NAV_ACTIVE_TEXT="#FFFFFF", NAV_HOVER_BG="#1F1F1F", BUTTON_HOVER="#3A3A3A",
        HEADING_BADGE_BG="#F2B705", HEADING_BADGE_TEXT="#141414",
        ON_STATUS="#141414",
    ),
}

_GEOMETRY = {
    "onedark": dict(RADIUS_CARD=9, RADIUS_CONTROL=6, RADIUS_PILL=11, BORDER_W=1, BAUHAUS=False, SHAPES=False,
                    UI_FAMILY="IBM Plex Sans", CHECK_ICON="check.svg", SIDEBAR_W=212),
    "bauhaus-light": dict(RADIUS_CARD=0, RADIUS_CONTROL=0, RADIUS_PILL=0, BORDER_W=2, BAUHAUS=True, SHAPES=True,
                          UI_FAMILY="Jost*", CHECK_ICON="check-light.svg", SIDEBAR_W=232),
    "bauhaus-dark": dict(RADIUS_CARD=0, RADIUS_CONTROL=0, RADIUS_PILL=0, BORDER_W=2, BAUHAUS=True, SHAPES=True,
                         UI_FAMILY="Jost*", CHECK_ICON="check.svg", SIDEBAR_W=232),
}


class Colors:
    """Colour tokens of the active theme (filled by apply_theme)."""


class Theme:
    """Non-colour tokens of the active theme (filled by apply_theme)."""
    NAME = DEFAULT_THEME


def apply_theme(name):
    """Activate a theme's tokens. Call before creating widgets."""
    if name not in _PALETTES:
        name = DEFAULT_THEME
    for key, value in _PALETTES[name].items():
        setattr(Colors, key, value)
    for key, value in _GEOMETRY[name].items():
        setattr(Theme, key, value)
    Theme.NAME = name
    global UI_FAMILY
    UI_FAMILY = Theme.UI_FAMILY


apply_theme(DEFAULT_THEME)


def rgba(hex_color, alpha):
    """CSS rgba() string for a token at the given opacity (0..1)."""
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def qcolor(hex_color, alpha=1.0):
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


UI_FAMILY = Theme.UI_FAMILY
MONO_FAMILY = "JetBrains Mono"
_UI_FALLBACKS = ["IBM Plex Sans", "Segoe UI", "Noto Sans", "DejaVu Sans"]
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
    UI_FAMILY = Theme.UI_FAMILY
    if UI_FAMILY not in families:
        UI_FAMILY = next((f for f in _UI_FALLBACKS if f in families), QFont().defaultFamily())
    if MONO_FAMILY not in families:
        MONO_FAMILY = next((f for f in _MONO_FALLBACKS if f in families), "Monospace")


def _font(family, px, weight):
    font = QFont(family)
    # Point sizes keep fractional design sizes (12.5px) and scale with the screen DPI
    # Jost runs small for its size, so Bauhaus themes scale UI text up a little
    scale = 1.08 if Theme.BAUHAUS and family == UI_FAMILY else 1.0
    font.setPointSizeF(px * 0.75 * scale)
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
    font = ui_font(px, 700 if Theme.BAUHAUS else 600)
    font.setLetterSpacing(QFont.AbsoluteSpacing, px * (0.16 if Theme.BAUHAUS else 0.07))
    return font


class ModernTheme:
    def get_stylesheet(self):
        c, g = Colors, Theme
        b = g.BORDER_W
        chevron = resource_path("assets", "icons", "chevron-down.svg").replace("\\", "/")
        check = resource_path("assets", "icons", g.CHECK_ICON).replace("\\", "/")
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
            border: {b}px solid {c.BORDER};
            padding: 4px 6px;
        }}

        /* Menu bar */
        QMenuBar {{
            background-color: {c.CHROME};
            color: {c.SIDEBAR_MUTED};
            border-bottom: {b}px solid {c.BORDER};
        }}
        QMenuBar::item {{
            background: transparent;
            padding: 4px 10px;
        }}
        QMenuBar::item:selected {{
            background-color: {c.NAV_HOVER_BG};
            color: {c.SIDEBAR_TEXT};
        }}
        QMenu {{
            background-color: {c.SURFACE};
            border: {b}px solid {c.BORDER};
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
            background-color: {c.SIDEBAR_BG};
            border: none;
            border-right: {b}px solid {c.BORDER};
        }}
        QFrame#navItem {{
            background: transparent;
            border-radius: {g.RADIUS_CONTROL}px;
        }}
        QFrame#navItem:hover {{
            background-color: {c.NAV_HOVER_BG};
        }}
        QFrame#navItem[active="true"] {{
            background-color: {c.NAV_ACTIVE_BG};
        }}
        QFrame#statusCard {{
            background-color: {c.SURFACE};
            border: {b}px solid {c.BORDER};
            border-radius: {g.RADIUS_CARD}px;
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
            border-bottom: {b}px solid {c.BORDER};
        }}

        /* Cards */
        QFrame[card="card"] {{
            background-color: {c.SURFACE};
            border: {b}px solid {c.BORDER};
            border-radius: {g.RADIUS_CARD}px;
        }}
        QFrame[card="sunken"] {{
            background-color: {c.BG_SUNKEN};
            border: {b}px solid {c.BORDER};
            border-radius: {g.RADIUS_CARD}px;
        }}
        QFrame[card="dashed"] {{
            background: transparent;
            border: {b}px dashed {c.BORDER};
            border-radius: {g.RADIUS_CARD}px;
        }}
        QFrame[card="error"] {{
            background-color: {c.SURFACE};
            border: {b}px solid {rgba(c.RED, 0.5)};
            border-radius: {g.RADIUS_CARD}px;
        }}
        QFrame[card="issues"] {{
            background-color: {c.SURFACE};
            border: {b}px solid {rgba(c.RED, 0.55)};
            border-radius: {g.RADIUS_CARD}px;
        }}
        QFrame[card="banner"] {{
            background-color: {rgba(c.RED, 0.08)};
            border: {b}px solid {rgba(c.RED, 0.5)};
            border-radius: {g.RADIUS_CARD}px;
        }}
        QFrame[card="checks"] {{
            background-color: {c.BG_SUNKEN};
            border: none;
            border-radius: {g.RADIUS_CONTROL}px;
        }}
        QFrame[card="note"] {{
            background-color: {c.BG_SUNKEN};
            border: none;
            border-radius: {g.RADIUS_CARD}px;
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
            border-top: {b}px solid {c.BORDER};
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
            border-left: {b}px solid {c.BORDER};
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
            border-radius: {g.RADIUS_CONTROL}px;
            padding: 0 14px;
            background-color: {c.SURFACE_2};
            color: {c.TEXT_STRONG};
            border: {b}px solid {c.BORDER};
        }}
        QPushButton:hover {{
            background-color: {c.BUTTON_HOVER};
        }}
        QPushButton:pressed {{
            background-color: {c.BORDER};
        }}
        QPushButton[variant="primary"] {{
            background-color: {c.PRIMARY};
            color: {c.ON_PRIMARY};
            border: none;
        }}
        QPushButton[variant="primary"]:hover {{
            background-color: {c.PRIMARY_HOVER};
        }}
        QPushButton[variant="primary"]:pressed {{
            background-color: {c.PRIMARY_PRESSED};
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
            border: {b}px solid {c.RED};
        }}
        QPushButton[variant="stop"]:hover {{
            background-color: {rgba(c.RED, 0.1)};
        }}
        QPushButton[variant="danger"] {{
            background-color: {c.RED};
            color: {c.ON_STATUS};
            border: none;
        }}
        QPushButton[variant="danger"]:hover {{
            background-color: {c.RED};
        }}
        QPushButton[variant="warn"] {{
            background: transparent;
            color: {c.YELLOW};
            border: {b}px solid {rgba(c.YELLOW, 0.6)};
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
            border-radius: {g.RADIUS_PILL}px;
            padding: 0 11px;
        }}
        QPushButton[variant="chip"]:checked {{
            background-color: {c.PRIMARY};
            color: {c.ON_PRIMARY};
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
            border: {b}px solid {c.BORDER};
            border-radius: {g.RADIUS_CONTROL}px;
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
            border: {b}px solid {c.BORDER};
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
            border: {b}px solid {c.BORDER};
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
            border: {b}px solid {c.BORDER};
            background-color: {c.BG_SUNKEN};
        }}
        QCheckBox::indicator:checked {{
            background-color: {c.PRIMARY};
            border: {b}px solid {c.PRIMARY};
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
            border: {b}px solid {c.BORDER};
            border-radius: {g.RADIUS_CARD}px;
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
            border-bottom: {b}px solid {c.BORDER};
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
