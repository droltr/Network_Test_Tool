"""Vertical hop list for the Diagnose host route pane."""
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor, QFontMetricsF
from PyQt5.QtWidgets import QWidget, QSizePolicy

from gui.styles.modern_theme import Colors, mono_font
from gui.widgets.common import PulseClock

ROW_HEIGHT = 40
BAR_WIDTH = 90


class HopList(QWidget):
    """Rows: node on a 2px connector, hop number, IP, latency bar (purple), ms value."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hops = []          # dicts: hop, ip, ms, status (ok/timeout), destination
        self.probing = None     # hop number currently being probed
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._resize()

    def reset(self):
        self.hops, self.probing = [], None
        PulseClock.unsubscribe(self)
        self._resize()

    def add_hop(self, hop):
        self.hops.append(hop)
        self._resize()

    def set_probing(self, hop_number):
        self.probing = hop_number
        if hop_number is None:
            PulseClock.unsubscribe(self)
        else:
            PulseClock.subscribe(self)
        self._resize()

    def _rows(self):
        rows = list(self.hops)
        if self.probing is not None:
            rows.append({'hop': self.probing, 'ip': 'probing…', 'ms': None, 'status': 'probing'})
        return rows

    def _resize(self):
        self.setFixedHeight(max(1, len(self._rows())) * ROW_HEIGHT + 8)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rows = self._rows()
        if not rows:
            return
        node_x = 8
        scale = max([16.0] + [h['ms'] for h in rows if h.get('ms') is not None])

        top_y = ROW_HEIGHT / 2
        bottom_y = (len(rows) - 0.5) * ROW_HEIGHT
        p.setPen(QPen(QColor(Colors.BORDER), 2))
        p.drawLine(QPointF(node_x, top_y - 12), QPointF(node_x, bottom_y + 12))

        num_font, ip_font, ms_font = mono_font(11), mono_font(12.5), mono_font(11.5)
        ms_metrics = QFontMetricsF(ms_font)
        ms_right = self.width() - 4
        bar_right = ms_right - 72
        bar_left = bar_right - BAR_WIDTH

        for index, hop in enumerate(rows):
            y = index * ROW_HEIGHT + ROW_HEIGHT / 2
            status = hop.get('status')
            # node
            if status == 'probing':
                p.setOpacity(PulseClock.opacity())
                p.setPen(QPen(QColor(Colors.PURPLE), 2))
                p.setBrush(QColor(Colors.BG))
                p.drawEllipse(QPointF(node_x, y), 5.5, 5.5)
                p.setOpacity(1.0)
            elif status == 'timeout':
                pen = QPen(QColor(Colors.RED), 1.4)
                pen.setStyle(Qt.CustomDashLine)
                pen.setDashPattern([1.6, 1.6])
                p.setPen(pen)
                p.setBrush(QColor(Colors.SURFACE))
                p.drawEllipse(QPointF(node_x, y), 4.5, 4.5)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(Colors.BLUE if hop.get('destination') else Colors.GREEN))
                radius = 6 if hop.get('destination') else 5
                p.drawEllipse(QPointF(node_x, y), radius, radius)

            p.setFont(num_font)
            p.setPen(QColor(Colors.TEXT_MUTED))
            p.drawText(QRectF(22, y - 10, 22, 20), Qt.AlignLeft | Qt.AlignVCenter, str(hop.get('hop', '')))

            p.setFont(ip_font)
            p.setPen(QColor(Colors.TEXT_STRONG))
            p.drawText(QRectF(48, y - 10, bar_left - 56, 20), Qt.AlignLeft | Qt.AlignVCenter, hop.get('ip', ''))

            # latency bar
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(Colors.BG_SUNKEN))
            p.drawRoundedRect(QRectF(bar_left, y - 2.5, BAR_WIDTH, 5), 2.5, 2.5)
            ms = hop.get('ms')
            if ms is not None:
                p.setBrush(QColor(Colors.PURPLE))
                p.drawRoundedRect(QRectF(bar_left, y - 2.5, max(4, BAR_WIDTH * min(ms / scale, 1)), 5), 2.5, 2.5)

            p.setFont(ms_font)
            if status == 'timeout':
                p.setPen(QColor(Colors.RED))
                text = "timeout"
            elif ms is not None:
                p.setPen(QColor(Colors.TEXT_MUTED))
                text = f"{ms:.1f} ms"
            else:
                text = ""
            width = ms_metrics.horizontalAdvance(text)
            p.drawText(QPointF(ms_right - width, y + ms_metrics.ascent() / 2 - 1), text)
