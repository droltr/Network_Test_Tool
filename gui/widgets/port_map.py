"""Port map: a cell grid for large scans and labelled tiles for short presets."""
import math

from PyQt5.QtCore import Qt, QRectF, QSize
from PyQt5.QtGui import QPainter, QPen, QColor
from PyQt5.QtWidgets import QWidget, QSizePolicy

from gui.styles.modern_theme import Colors, mono_font, ui_font, qcolor
from gui.widgets.common import PulseClock

TILE_LIMIT = 64       # presets up to this size use tiles
MAX_CELLS = 4096      # larger ranges are bucketed so the map stays compact
COLUMNS = 64


class PortMap(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ports = []
        self.index = {}
        self.states = {}       # port -> 'Open' / 'Closed' / 'Error'
        self.services = {}
        self.probing = None
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    # ---- data
    def set_ports(self, ports):
        self.ports = list(ports)
        self.index = {port: i for i, port in enumerate(self.ports)}
        self.states, self.services, self.probing = {}, {}, None
        self._relayout()

    def set_result(self, port, state, service=None):
        self.states[port] = state
        if service:
            self.services[port] = service
        self.update()

    def set_probing(self, port):
        self.probing = port
        if port is None:
            PulseClock.unsubscribe(self)
        elif self.tile_mode:
            PulseClock.subscribe(self)
        self.update()

    @property
    def tile_mode(self):
        return 0 < len(self.ports) <= TILE_LIMIT

    def _bucket(self):
        return max(1, math.ceil(len(self.ports) / MAX_CELLS))

    # ---- geometry (height follows the width)
    @staticmethod
    def _tile_columns(width):
        return max(4, min(8, width // 120))

    @staticmethod
    def _pitch(width):
        return min(16.0, max(width, 200) / COLUMNS)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if self.tile_mode:
            rows = math.ceil(len(self.ports) / self._tile_columns(width))
            height = rows * 64 + (rows - 1) * 8
        else:
            cells = math.ceil(len(self.ports) / self._bucket())
            rows = max(1, math.ceil(cells / COLUMNS))
            height = rows * self._pitch(width)
        return int(math.ceil(max(height, 16)))

    def sizeHint(self):
        width = max(self.width(), 640)
        return QSize(width, self.heightForWidth(width))

    def _relayout(self):
        self.updateGeometry()
        self.update()

    # ---- painting
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.tile_mode:
            self._paint_tiles(p)
        else:
            self._paint_cells(p)

    def _paint_cells(self, p):
        pitch = self._pitch(self.width())
        cell = pitch - 3
        bucket = self._bucket()
        cells = math.ceil(len(self.ports) / bucket)
        for c in range(cells):
            group = self.ports[c * bucket:(c + 1) * bucket]
            states = [self.states.get(port) for port in group]
            rect = QRectF((c % COLUMNS) * pitch, (c // COLUMNS) * pitch, cell, cell)
            if 'Open' in states:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(Colors.GREEN))
            elif 'Error' in states:
                p.setPen(Qt.NoPen)
                p.setBrush(qcolor(Colors.RED, 0.55))
            elif any(states):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(Colors.SURFACE_2))
            else:
                p.setPen(QPen(QColor(Colors.SURFACE_2), 1))
                p.setBrush(Qt.NoBrush)
                rect.adjust(0.5, 0.5, -0.5, -0.5)
            p.drawRoundedRect(rect, 2, 2)

    def _paint_tiles(self, p):
        columns = self._tile_columns(self.width())
        gap = 8
        width = (self.width() - gap * (columns - 1)) / columns
        for i, port in enumerate(self.ports):
            rect = QRectF((i % columns) * (width + gap), (i // columns) * (64 + gap), width, 64)
            state = self.states.get(port)
            service = self.services.get(port, "")
            if port == self.probing:
                p.setPen(QPen(QColor(Colors.BLUE), 2))
                p.setBrush(QColor(Colors.SURFACE))
                p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)
                caption, caption_color, number_color = "Probing", Colors.BLUE, Colors.TEXT_STRONG
            elif state == 'Open':
                p.setPen(QPen(qcolor(Colors.GREEN, 0.5), 1))
                p.setBrush(qcolor(Colors.GREEN, 0.1))
                p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
                caption, caption_color, number_color = service or "open", Colors.GREEN, Colors.TEXT_STRONG
            elif state in ('Closed', 'Error'):
                p.setPen(QPen(QColor(Colors.BORDER), 1))
                p.setBrush(QColor(Colors.SURFACE))
                p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
                caption = "error" if state == 'Error' else "closed"
                caption_color = Colors.RED if state == 'Error' else Colors.TEXT_FAINT
                number_color = Colors.TEXT_MUTED
            else:
                pen = QPen(QColor(Colors.BORDER), 1)
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
                caption, caption_color, number_color = "pending", Colors.TEXT_FAINT, Colors.TEXT_FAINT

            p.setFont(mono_font(15, 500))
            p.setPen(QColor(number_color))
            p.drawText(rect.adjusted(12, 10, -8, -30), Qt.AlignLeft | Qt.AlignVCenter, str(port))
            p.setFont(ui_font(11.5, 500))
            if port == self.probing:
                p.setOpacity(PulseClock.opacity())
            p.setPen(QColor(caption_color))
            p.drawText(rect.adjusted(12, 34, -8, -8), Qt.AlignLeft | Qt.AlignVCenter, caption)
            p.setOpacity(1.0)
