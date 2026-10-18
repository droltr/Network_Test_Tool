"""Sidebar navigation: grouped nav items, running dots, issue badge and the status card.

Group headings are labels, never links: they look different from the clickable items in
every theme (One Dark: small muted caps under a rule; Bauhaus: a numbered yellow tag).
"""
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QPainter, QPainterPath, QColor, QFontMetrics, QPen
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget

from version import __version__
from gui.styles.modern_theme import Colors, Theme, ui_font, mono_font, section_font
from gui.widgets.common import Label, section_label, PulseDot, StatusDot, Badge, set_prop, button

NAV_GROUPS = [
    ("Overview", [("dashboard", "Dashboard")]),
    ("Tools", [("diagnose", "Diagnose host"), ("port", "Port scanner"), ("speed", "Speed test"),
               ("iperf", "iPerf3")]),
    ("System", [("health", "Network health"), ("advanced", "Advanced"), ("trouble", "Troubleshooter")]),
]


class AppMark(QWidget):
    """The app mark: two nodes (circle and square) joined by the connection line."""

    def __init__(self, size=28, ground=None, parent=None):
        super().__init__(parent)
        self.ground = ground
        self.setFixedSize(size, size)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width() / 512
        p.scale(s, s)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.ground or "#F1ECE2"))
        p.drawRect(0, 0, 512, 512)
        p.setBrush(QColor("#C8322A"))
        p.drawEllipse(QPointF(196, 196), 112, 112)
        p.setBrush(QColor("#1D4E9E"))
        p.drawRect(276, 276, 160, 160)
        p.setPen(QPen(QColor("#141414"), 30))
        p.drawLine(196, 196, 356, 356)


class NavItem(QFrame):
    clicked = pyqtSignal()

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setObjectName("navItem")
        self.setCursor(Qt.PointingHandCursor)
        bauhaus = Theme.BAUHAUS
        self.setFixedHeight(42 if bauhaus else 32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16 if bauhaus else 10, 0, 12 if bauhaus else 10, 0)
        layout.setSpacing(12 if bauhaus else 6)
        self.marker = QFrame()
        self.marker.setFixedSize(10, 10)
        self.marker.setVisible(bauhaus)
        layout.addWidget(self.marker)
        size = 15 if bauhaus else 13
        self.label = QLabel(text)
        self.label.setFont(ui_font(size))
        # Reserve the bold width so the text is not clipped when the item becomes active
        self.label.setMinimumWidth(QFontMetrics(ui_font(size, 700)).horizontalAdvance(text) + 2)
        layout.addWidget(self.label)
        layout.addStretch(1)
        self.running_dot = PulseDot(Colors.HEADING_BADGE_BG if bauhaus else Colors.BLUE, 6)
        self.running_dot.setVisible(False)
        layout.addWidget(self.running_dot)
        self.badge = Badge("", Colors.RED, filled=True)
        self.badge.setVisible(False)
        layout.addWidget(self.badge)
        self.arrow = QLabel("→")
        self.arrow.setFont(ui_font(size, 700))
        self.arrow.setVisible(False)
        layout.addWidget(self.arrow)
        self.set_active(False)

    def set_active(self, active):
        set_prop(self, "active", "true" if active else "false")
        bauhaus = Theme.BAUHAUS
        size = 15 if bauhaus else 13
        self.label.setFont(ui_font(size, 700 if active and bauhaus else 600 if active else 500))
        color = Colors.NAV_ACTIVE_TEXT if active else Colors.SIDEBAR_TEXT
        self.label.setStyleSheet(f"color: {color}; background: transparent;")
        if bauhaus:
            self.arrow.setVisible(active)
            self.arrow.setStyleSheet(f"color: {color}; background: transparent;")
            # Filled square for the current page, outlined square for the others
            self.marker.setStyleSheet(f"background: {color if active else 'transparent'}; "
                                      f"border: 2px solid {color};")
        self.active = active
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.active and not Theme.BAUHAUS:
            # 2px blue inset on the left edge, following the rounded corner
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), Theme.RADIUS_CONTROL, Theme.RADIUS_CONTROL)
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.states = {
            "online": ("Online", Colors.GREEN),
            "local": ("Local only", Colors.YELLOW),
            "offline": ("Offline", Colors.RED),
        }
        self.setObjectName("statusCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.dot = StatusDot(Colors.TEXT_FAINT, 8 if Theme.BAUHAUS else 6)
        self.label = Label("Checking…", 13.5 if Theme.BAUHAUS else 12.5, 700 if Theme.BAUHAUS else 600,
                           Colors.TEXT_MUTED)
        row.addWidget(self.dot)
        row.addWidget(self.label)
        row.addStretch(1)
        layout.addLayout(row)
        self.detail = Label("", 11, color=Colors.TEXT_MUTED, mono=True)
        layout.addWidget(self.detail)

    def set_status(self, status, iface, ip):
        text, color = self.states.get(status, self.states["offline"])
        self.dot.set_state(color)
        self.label.setText(text)
        self.label.set_color(color)
        self.detail.setText(" · ".join(part for part in (iface, ip) if part) or "no connection")
        set_prop(self, "status", status)


def _bauhaus_heading(number, text):
    row = QHBoxLayout()
    row.setContentsMargins(16, 14, 16, 6)
    row.setSpacing(8)
    tag = QLabel(f"{number:02d}")
    tag.setFont(mono_font(11, 500))
    tag.setStyleSheet(f"background: {Colors.HEADING_BADGE_BG}; color: {Colors.HEADING_BADGE_TEXT}; "
                      "padding: 1px 5px;")
    label = QLabel(text.upper())
    font = section_font(11)
    label.setFont(font)
    label.setStyleSheet(f"color: {Colors.SIDEBAR_MUTED}; background: transparent;")
    row.addWidget(tag)
    row.addWidget(label)
    row.addStretch(1)
    return row


class Sidebar(QFrame):
    page_selected = pyqtSignal(str)
    ask_ai = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(Theme.SIDEBAR_W)
        bauhaus = Theme.BAUHAUS
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16 if bauhaus else 14, 0, 10)
        layout.setSpacing(0)

        title = QHBoxLayout()
        title.setContentsMargins(16 if bauhaus else 15, 0, 15, 0)
        title.setSpacing(10 if bauhaus else 8)
        if bauhaus:
            title.addWidget(AppMark(30))
            name = QVBoxLayout()
            name.setSpacing(0)
            heading = QLabel("NETWORK TEST")
            heading.setFont(section_font(14))
            heading.setStyleSheet(f"color: {Colors.SIDEBAR_TEXT}; background: transparent;")
            name.addWidget(heading)
            name.addWidget(Label(f"v{__version__}", 10.5, color=Colors.SIDEBAR_MUTED, mono=True))
            title.addLayout(name)
        else:
            title.addWidget(Label("Network Test", 14, 600, Colors.TEXT_STRONG))
            version = Label(f"v{__version__}", 10.5, color=Colors.TEXT_MUTED, mono=True)
            title.addWidget(version, 0, Qt.AlignBottom)
        title.addStretch(1)
        layout.addLayout(title)
        layout.addSpacing(12 if bauhaus else 10)

        self.items = {}
        for index, (group, entries) in enumerate(NAV_GROUPS):
            if index or bauhaus:
                rule = QFrame()
                rule.setFixedHeight(2 if bauhaus else 1)
                rule.setStyleSheet(f"background: {Colors.SIDEBAR_RULE}; border: none;")
                rule_row = QHBoxLayout()
                rule_row.setContentsMargins(0 if bauhaus else 15, 10 if index else 0, 0 if bauhaus else 15, 0)
                rule_row.addWidget(rule)
                layout.addLayout(rule_row)
            if bauhaus:
                layout.addLayout(_bauhaus_heading(index + 1, group))
            else:
                heading = section_label(group, Colors.TEXT_MUTED, px=10)
                heading.setContentsMargins(15, 10 if index else 4, 15, 4)
                layout.addWidget(heading)
            for key, text in entries:
                item = NavItem(text)
                item.clicked.connect(lambda k=key: self.page_selected.emit(k))
                wrapper = QHBoxLayout()
                if bauhaus:
                    wrapper.setContentsMargins(0, 0, 0, 0)
                else:
                    wrapper.setContentsMargins(5, 1, 8, 1)
                wrapper.addWidget(item)
                layout.addLayout(wrapper)
                self.items[key] = item

        layout.addStretch(1)
        ask = button("ASK AI AGENT" if bauhaus else "Ask AI agent", "ghost", 40 if bauhaus else 32)
        if bauhaus:
            ask.setFont(section_font(13))
            ask.setStyleSheet(f"QPushButton {{ background: transparent; color: {Colors.HEADING_BADGE_BG}; "
                              f"border: 2px solid {Colors.HEADING_BADGE_BG}; border-radius: 0; }}"
                              f"QPushButton:hover {{ background: {Colors.HEADING_BADGE_BG}; "
                              f"color: {Colors.HEADING_BADGE_TEXT}; }}")
        ask.setToolTip("Prepare your system information and test results for your own AI assistant")
        ask.clicked.connect(self.ask_ai)
        ask_row = QHBoxLayout()
        ask_row.setContentsMargins(14 if bauhaus else 7, 0, 14 if bauhaus else 9, 10 if bauhaus else 8)
        ask_row.addWidget(ask)
        layout.addLayout(ask_row)
        self.status_card = StatusCard()
        card_row = QHBoxLayout()
        card_row.setContentsMargins(14 if bauhaus else 7, 0, 14 if bauhaus else 9, 4 if bauhaus else 0)
        card_row.addWidget(self.status_card)
        layout.addLayout(card_row)

    def set_active(self, key):
        for item_key, item in self.items.items():
            item.set_active(item_key == key)
