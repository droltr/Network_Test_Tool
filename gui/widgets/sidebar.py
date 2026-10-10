"""Sidebar navigation: grouped nav items, running dots, issue badge and the status card."""
from PyQt5.QtCore import Qt, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPainterPath, QColor, QFontMetrics
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel

from version import __version__
from gui.styles.modern_theme import Colors, ui_font
from gui.widgets.common import Label, section_label, PulseDot, StatusDot, Badge, set_prop, button

NAV_GROUPS = [
    ("Overview", [("dashboard", "Dashboard")]),
    ("Tools", [("diagnose", "Diagnose host"), ("port", "Port scanner"), ("speed", "Speed test"),
               ("iperf", "iPerf3")]),
    ("System", [("health", "Network health"), ("advanced", "Advanced"), ("trouble", "Troubleshooter")]),
]


class NavItem(QFrame):
    clicked = pyqtSignal()

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setObjectName("navItem")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)
        self.label = QLabel(text)
        self.label.setFont(ui_font(13))
        # Reserve the bold width so the text is not clipped when the item becomes active
        self.label.setMinimumWidth(QFontMetrics(ui_font(13, 600)).horizontalAdvance(text) + 2)
        layout.addWidget(self.label)
        layout.addStretch(1)
        self.running_dot = PulseDot(Colors.BLUE, 6)
        self.running_dot.setVisible(False)
        layout.addWidget(self.running_dot)
        self.badge = Badge("", Colors.RED, filled=True)
        self.badge.setVisible(False)
        layout.addWidget(self.badge)
        self.set_active(False)

    def set_active(self, active):
        set_prop(self, "active", "true" if active else "false")
        self.label.setFont(ui_font(13, 600 if active else 500))
        self.label.setStyleSheet(f"color: {Colors.TEXT_STRONG if active else '#c8ccd4'}; background: transparent;")
        self.active = active
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.active:
            # 2px blue inset on the left edge, following the rounded corner
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), 6, 6)
            p.setClipPath(path)
            p.fillRect(QRectF(0, 0, 2, self.height()), QColor(Colors.BLUE))

    def set_running(self, running):
        self.running_dot.setVisible(running)

    def set_count(self, count):
        self.badge.setText(str(count))
        self.badge.setVisible(count > 0)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class StatusCard(QFrame):
    STATES = {
        "online": ("Online", Colors.GREEN),
        "local": ("Local only", Colors.YELLOW),
        "offline": ("Offline", Colors.RED),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.dot = StatusDot(Colors.TEXT_FAINT, 6)
        self.label = Label("Checking…", 12.5, 600, Colors.TEXT_MUTED)
        row.addWidget(self.dot)
        row.addWidget(self.label)
        row.addStretch(1)
        layout.addLayout(row)
        self.detail = Label("", 11, color=Colors.TEXT_MUTED, mono=True)
        layout.addWidget(self.detail)

    def set_status(self, status, iface, ip):
        text, color = self.STATES.get(status, self.STATES["offline"])
        self.dot.set_state(color)
        self.label.setText(text)
        self.label.set_color(color)
        self.detail.setText(" · ".join(part for part in (iface, ip) if part) or "no connection")
        set_prop(self, "status", status)


class Sidebar(QFrame):
    page_selected = pyqtSignal(str)
    ask_ai = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(212)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 10)
        layout.setSpacing(0)

        title = QHBoxLayout()
        title.setContentsMargins(15, 0, 15, 0)
        title.setSpacing(8)
        title.addWidget(Label("Network Test", 14, 600, Colors.TEXT_STRONG))
        version = Label(f"v{__version__}", 10.5, color=Colors.TEXT_MUTED, mono=True)
        title.addWidget(version, 0, Qt.AlignBottom)
        title.addStretch(1)
        layout.addLayout(title)
        layout.addSpacing(10)

        self.items = {}
        for index, (group, entries) in enumerate(NAV_GROUPS):
            # Group headings are labels, not links: small caps text with a rule, never highlighted
            if index:
                rule = QFrame()
                rule.setFixedHeight(1)
                rule.setStyleSheet(f"background: {Colors.BORDER}; border: none;")
                rule_row = QHBoxLayout()
                rule_row.setContentsMargins(15, 10, 15, 0)
                rule_row.addWidget(rule)
                layout.addLayout(rule_row)
            heading = section_label(group, Colors.TEXT_MUTED, px=10)
            heading.setContentsMargins(15, 10 if index else 4, 15, 4)
            layout.addWidget(heading)
            for key, text in entries:
                item = NavItem(text)
                item.clicked.connect(lambda k=key: self.page_selected.emit(k))
                wrapper = QHBoxLayout()
                wrapper.setContentsMargins(5, 1, 8, 1)
                wrapper.addWidget(item)
                layout.addLayout(wrapper)
                self.items[key] = item

        layout.addStretch(1)
        ask = button("Ask AI agent", "ghost", 32)
        ask.setToolTip("Prepare your system information and test results for your own AI assistant")
        ask.clicked.connect(self.ask_ai)
        ask_row = QHBoxLayout()
        ask_row.setContentsMargins(7, 0, 9, 8)
        ask_row.addWidget(ask)
        layout.addLayout(ask_row)
        self.status_card = StatusCard()
        card_row = QHBoxLayout()
        card_row.setContentsMargins(7, 0, 9, 0)
        card_row.addWidget(self.status_card)
        layout.addLayout(card_row)

    def set_active(self, key):
        for item_key, item in self.items.items():
            item.set_active(item_key == key)
