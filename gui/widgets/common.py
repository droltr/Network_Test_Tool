"""Shared building blocks for the redesigned pages."""
import re
from datetime import datetime

from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QRectF, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QTextCharFormat, QTextBlockFormat, QTextCursor, QFontMetrics
from PyQt5.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
                             QGraphicsOpacityEffect, QPlainTextEdit, QTableWidget, QHeaderView,
                             QAbstractItemView, QSizePolicy, QCheckBox, QLineEdit, QButtonGroup)

from gui.styles.modern_theme import Colors, ui_font, mono_font, section_font, rgba


# ---------------------------------------------------------------- helpers

def repolish(widget):
    """Re-apply the stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_prop(widget, name, value):
    if widget.property(name) != value:
        widget.setProperty(name, value)
        repolish(widget)


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def hbox(*items, spacing=8, margins=(0, 0, 0, 0)):
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for item in items:
        if item == "stretch":
            layout.addStretch(1)
        elif isinstance(item, int):
            layout.addSpacing(item)
        elif isinstance(item, QWidget):
            layout.addWidget(item)
        else:
            layout.addLayout(item)
    return layout


def vbox(*items, spacing=8, margins=(0, 0, 0, 0)):
    layout = QVBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for item in items:
        if item == "stretch":
            layout.addStretch(1)
        elif isinstance(item, int):
            layout.addSpacing(item)
        elif isinstance(item, QWidget):
            layout.addWidget(item)
        else:
            layout.addLayout(item)
    return layout


def relative_time(iso_time):
    """'18 min ago', 'yesterday', '3 days ago' for an ISO timestamp."""
    try:
        then = datetime.fromisoformat(iso_time)
    except (TypeError, ValueError):
        return ""
    seconds = (datetime.now() - then).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} h ago"
    days = int(seconds // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


def fmt_ms(value, digits=1):
    return "—" if value is None else f"{value:.{digits}f} ms"


# ---------------------------------------------------------------- text

class Label(QLabel):
    def __init__(self, text="", px=12.5, weight=400, color=Colors.TEXT, mono=False, parent=None):
        super().__init__(text, parent)
        self.setFont(mono_font(px, weight) if mono else ui_font(px, weight))
        self.set_color(color)

    def set_color(self, color):
        self.setStyleSheet(f"color: {color}; background: transparent;")


def section_label(text, color=Colors.TEXT_MUTED, px=10.5):
    label = QLabel(text.upper())
    label.setFont(section_font(px))
    label.setStyleSheet(f"color: {color}; background: transparent;")
    return label


# ---------------------------------------------------------------- buttons

def button(text, variant="secondary", height=30, width=None, weight=None):
    btn = QPushButton(text)
    btn.setProperty("variant", variant)
    btn.setCursor(Qt.PointingHandCursor)
    if weight is None:
        weight = 600 if variant in ("primary", "stop", "danger", "warn") else 500
    btn.setFont(ui_font(12.5, weight))
    btn.setFixedHeight(height)
    if width:
        btn.setFixedWidth(width)
    btn.setFocusPolicy(Qt.TabFocus)
    return btn


def link_button(text):
    btn = button(text, "link", height=22, weight=500)
    btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return btn


# ---------------------------------------------------------------- chips

def chip_group(parent, options, default):
    group = QButtonGroup(parent)
    group.setExclusive(True)
    layout = QHBoxLayout()
    layout.setSpacing(4)
    for key, text in options:
        chip = button(text, "chip", 26)
        chip.setMinimumWidth(QFontMetrics(ui_font(12.5, 600)).horizontalAdvance(text) + 28)
        chip.setCheckable(True)
        chip.setProperty("key", key)
        chip.setChecked(key == default)
        group.addButton(chip)
        layout.addWidget(chip)
    return group, layout


def selected_key(group):
    checked = group.checkedButton()
    return checked.property("key") if checked else None


# ---------------------------------------------------------------- frames

class Card(QFrame):
    """Flat surface with a 1px border. kind: card, sunken, dashed, error, issues, banner, checks, note."""

    def __init__(self, kind="card", margins=(16, 14, 16, 14), spacing=10, parent=None):
        super().__init__(parent)
        self.setProperty("card", kind)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(*margins)
        self.body.setSpacing(spacing)

    def set_kind(self, kind):
        set_prop(self, "card", kind)


def divider():
    line = QFrame()
    line.setProperty("divider", "h")
    return line


class LineInput(QLineEdit):
    """Mono text input with the error ring used by the design."""

    def __init__(self, placeholder="", height=36, mono=True, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(height)
        self.setFont(mono_font(12.5) if mono else ui_font(12.5))
        self.textEdited.connect(lambda _text: self.set_error(False))

    def set_error(self, error):
        set_prop(self, "error", "true" if error else "false")


# ---------------------------------------------------------------- status dots

class StatusDot(QWidget):
    """Small round indicator. style: filled, hollow, dashed, ring."""

    def __init__(self, color=Colors.GREEN, size=8, style="filled", parent=None):
        super().__init__(parent)
        self._color = color
        self._style = style
        self._size = size
        self.setFixedSize(size + 4, size + 4)

    def set_state(self, color, style="filled"):
        self._color, self._style = color, style
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(2, 2, self._size, self._size)
        color = QColor(self._color)
        if self._style == "filled":
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(rect)
        else:
            pen = QPen(color, 1.6 if self._style != "ring" else 2)
            if self._style == "dashed":
                pen.setStyle(Qt.CustomDashLine)
                pen.setDashPattern([1.5, 1.5])
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(rect.adjusted(0.8, 0.8, -0.8, -0.8))


class Pulse:
    """Opacity 1 -> .35 -> 1 over 1.2 s, looped (QPropertyAnimation on a QGraphicsOpacityEffect)."""

    def __init__(self, widget):
        self.effect = QGraphicsOpacityEffect(widget)
        self.effect.setOpacity(1.0)
        widget.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", widget)
        self.anim.setDuration(1200)
        self.anim.setStartValue(1.0)
        self.anim.setKeyValueAt(0.5, 0.35)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.InOutSine)
        self.anim.setLoopCount(-1)

    def start(self):
        if self.anim.state() != QPropertyAnimation.Running:
            self.anim.start()

    def stop(self):
        self.anim.stop()
        self.effect.setOpacity(1.0)


class PulseDot(StatusDot):
    def __init__(self, color=Colors.BLUE, size=7, style="filled", parent=None):
        super().__init__(color, size, style, parent)
        self.pulse = Pulse(self)

    def setVisible(self, visible):
        super().setVisible(visible)
        if visible:
            self.pulse.start()
        else:
            self.pulse.stop()


class PulseClock:
    """Shared 25 fps clock for custom-painted widgets that draw a pulsing element."""
    _timer = None
    _listeners = set()

    @classmethod
    def subscribe(cls, widget):
        if cls._timer is None:
            cls._timer = QTimer()
            cls._timer.setInterval(40)
            cls._timer.timeout.connect(cls._tick)
        cls._listeners.add(widget)
        cls._timer.start()

    @classmethod
    def unsubscribe(cls, widget):
        cls._listeners.discard(widget)
        if not cls._listeners and cls._timer:
            cls._timer.stop()

    @classmethod
    def _tick(cls):
        for widget in list(cls._listeners):
            try:
                widget.update()
            except RuntimeError:  # widget deleted
                cls._listeners.discard(widget)

    @staticmethod
    def opacity():
        import math, time
        phase = (time.monotonic() % 1.2) / 1.2
        return 0.675 + 0.325 * math.cos(phase * 2 * math.pi)


# ---------------------------------------------------------------- composite widgets

class Badge(QLabel):
    """Tinted pill: 11.5px/600, padding 3px 8px."""

    def __init__(self, text, color=Colors.BLUE, filled=False, parent=None):
        super().__init__(text, parent)
        self.setFont(ui_font(11, 600))
        self.set_tone(color, filled)

    def set_tone(self, color, filled=False):
        if filled:
            style = f"background: {color}; color: {Colors.CHROME};"
        else:
            style = f"background: {rgba(color, 0.14)}; color: {color};"
        self.setStyleSheet(f"QLabel {{ {style} border-radius: 8px; padding: 1px 7px; }}")


class StatStrip(QFrame):
    """Row of stat cells: muted label above a mono value; '—' in faint when empty."""

    def __init__(self, fields, value_px=14, parent=None):
        super().__init__(parent)
        self.setProperty("card", "card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.values = {}
        for index, (key, title) in enumerate(fields):
            cell = QFrame()
            cell.setProperty("cell", "true")
            cell.setProperty("first", "true" if index == 0 else "false")
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(14, 9, 14, 9)
            cl.setSpacing(2)
            cl.addWidget(Label(title, 11.5, color=Colors.TEXT_MUTED))
            value = Label("—", value_px, color=Colors.TEXT_FAINT, mono=True)
            cl.addWidget(value)
            layout.addWidget(cell, 1)
            self.values[key] = value

    def set_embedded(self, embedded):
        """Inside another card: no outer border, only the bottom divider."""
        if embedded:
            self.setStyleSheet(f"QFrame[card=\"card\"] {{ border: none; border-bottom: 1px solid {Colors.BORDER};"
                               " border-radius: 0; background: transparent; }")
        else:
            self.setStyleSheet("")

    def set(self, key, text, color=Colors.TEXT_STRONG):
        label = self.values[key]
        if text in (None, "", "—"):
            label.setText("—")
            label.set_color(Colors.TEXT_FAINT)
        else:
            label.setText(str(text))
            label.set_color(color)

    def reset(self):
        for key in self.values:
            self.set(key, None)


class EmptyPane(Card):
    """Dashed placeholder: title 15/500 plus a muted description, centred."""

    def __init__(self, title="", description="", parent=None):
        super().__init__("dashed", margins=(24, 24, 24, 24), parent=parent)
        self.body.addStretch(1)
        self.title = Label(title, 14, 500, Colors.TEXT)
        self.title.setAlignment(Qt.AlignCenter)
        self.description = Label(description, 12.5, color=Colors.TEXT_MUTED)
        self.description.setAlignment(Qt.AlignCenter)
        self.description.setWordWrap(True)
        self.body.addWidget(self.title)
        self.body.addWidget(self.description)
        self.body.addStretch(1)

    def set_text(self, title, description=""):
        self.title.setText(title)
        self.description.setText(description)


class ErrorCard(QWidget):
    """Centred error card (560-580px) with optional checks box, help text and actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.card = Card("error", margins=(28, 26, 28, 26), spacing=12)
        self.card.setFixedWidth(620)
        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        self.kicker = section_label("", Colors.RED, px=11)
        self.message = Label("", 17, 600, Colors.TEXT_STRONG)
        self.message.setWordWrap(True)
        self.checks = Card("checks", margins=(14, 10, 14, 10), spacing=6)
        self.help = Label("", 12.5, color=Colors.TEXT)
        self.help.setWordWrap(True)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        for widget in (self.kicker, self.message, self.checks, self.help):
            self.card.body.addWidget(widget)
        self.card.body.addLayout(self.actions)

    def show_error(self, kicker, message, checks=None, help_text="", actions=()):
        self.kicker.setText(kicker.upper())
        self.message.setText(message)
        clear_layout(self.checks.body)
        for text, value, ok in checks or []:
            value_label = Label(value, 12.5, color=Colors.GREEN if ok else Colors.RED)
            value_label.setAlignment(Qt.AlignRight)
            self.checks.body.addLayout(hbox(Label(text, 12.5, color=Colors.TEXT), "stretch", value_label))
        self.checks.setVisible(bool(checks))
        self.help.setText(help_text)
        self.help.setVisible(bool(help_text))
        clear_layout(self.actions)
        for action in actions:
            self.actions.addWidget(action)
        self.actions.addStretch(1)


class ToggleChip(QFrame):
    """Bordered checkbox chip such as  [x] Ping  x20."""

    toggled = pyqtSignal(bool)

    def __init__(self, label, detail, checked=True, parent=None):
        super().__init__(parent)
        self.setProperty("card", "sunken")
        self.setStyleSheet("QFrame[card=\"sunken\"] { border-radius: 6px; }")
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)
        self.check = QCheckBox(label)
        self.check.setFont(ui_font(12.5))
        self.check.setChecked(checked)
        self.check.toggled.connect(self.toggled)
        self.detail = Label(detail, 12, 500, Colors.TEXT_STRONG, mono=True)
        layout.addWidget(self.check)
        layout.addWidget(self.detail)

    def isChecked(self):
        return self.check.isChecked()


# ---------------------------------------------------------------- log pane

class LogPane(Card):
    """Sunken log with a 'LOG' header; colours success, failure and [SUGGESTION] lines."""

    def __init__(self, title="Log", parent=None):
        super().__init__("sunken", margins=(0, 0, 0, 0), spacing=0, parent=parent)
        header = QFrame()
        header.setObjectName("logHeader")
        header.setStyleSheet(f"QFrame#logHeader {{ border: none; border-bottom: 1px solid {Colors.BORDER};"
                             " background: transparent; }")
        header.setFixedHeight(34)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.addWidget(section_label(title))
        hl.addStretch(1)
        self.header_layout = hl
        self.body.addWidget(header)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(mono_font(11.5))
        self.text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.text.document().setDocumentMargin(12)
        self.body.addWidget(self.text, 1)

    @staticmethod
    def line_color(line):
        stripped = line.strip()
        if "[SUGGESTION]" in stripped:
            return Colors.YELLOW, rgba(Colors.YELLOW, 0.08)
        if re.match(r"^---.*Complete.*---$", stripped) or stripped.endswith("Complete ---"):
            return Colors.GREEN, None
        if stripped.startswith("---"):
            return Colors.TEXT_MUTED, None
        lowered = stripped.lower()
        if lowered.startswith(("success", "reply from")) or "open (" in lowered:
            return Colors.GREEN, None
        if lowered.startswith(("failed", "error", "request timeout", "no reply", "traceroute command not found")) \
                or "failed" in lowered:
            return Colors.RED, None
        return Colors.TEXT, None

    def append_line(self, line, color=None):
        for part in str(line).split("\n"):
            fg, bg = self.line_color(part)
            if color:
                fg = color
            cursor = self.text.textCursor()
            cursor.movePosition(QTextCursor.End)
            if not self.text.document().isEmpty():
                cursor.insertBlock()
            block = QTextBlockFormat()
            if bg:
                block.setBackground(QColor(bg_to_qcolor(bg)))
            cursor.setBlockFormat(block)
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(fg))
            cursor.insertText(part, fmt)
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    def clear(self):
        self.text.clear()

    def plain_text(self):
        return self.text.toPlainText()


def bg_to_qcolor(css_rgba):
    numbers = [float(n) for n in re.findall(r"[\d.]+", css_rgba)]
    color = QColor(int(numbers[0]), int(numbers[1]), int(numbers[2]))
    color.setAlphaF(numbers[3])
    return color


# ---------------------------------------------------------------- tables

def make_table(columns, stretch_column=None, row_height=32, embedded=False):
    """Design table: section-label header, fixed 32px rows, no grid or vertical header."""
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([c.upper() for c in columns])
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.setShowGrid(False)
    table.setAlternatingRowColors(False)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setFocusPolicy(Qt.NoFocus)
    table.setWordWrap(False)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    header = table.horizontalHeader()
    header.setFont(section_font())
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    header.setHighlightSections(False)
    header.setFixedHeight(30)
    header.setSectionResizeMode(QHeaderView.Interactive)
    if stretch_column is not None:
        header.setSectionResizeMode(stretch_column, QHeaderView.Stretch)
    else:
        header.setStretchLastSection(True)
    if embedded:
        table.setProperty("embedded", "true")
    return table


def fit_table_height(table, max_rows=None):
    """Fix the table height to its rows so it does not scroll inside a page."""
    rows = table.rowCount() if max_rows is None else min(table.rowCount(), max_rows)
    height = table.horizontalHeader().height() + rows * table.verticalHeader().defaultSectionSize() + 4
    table.setFixedHeight(height)


def cell_widget(*widgets, margins=(14, 0, 8, 0)):
    """Wrap widgets so they sit left-aligned inside a table cell."""
    holder = QWidget()
    holder.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(*margins)
    layout.setSpacing(6)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return holder


def elide(text, font, width):
    return QFontMetrics(font).elidedText(text, Qt.ElideRight, width)
