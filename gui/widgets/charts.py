"""Custom-painted charts (QPainter)."""
import math

from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor, QPainterPath, QFontMetricsF
from PyQt5.QtWidgets import QWidget, QSizePolicy

from gui.styles.modern_theme import Colors, mono_font, ui_font, section_font, qcolor


def nice_ceiling(value):
    """Round up to 1/2/2.5/5 x 10^n so axis labels stay readable."""
    if value <= 0:
        return 1
    exponent = math.floor(math.log10(value))
    base = 10 ** exponent
    for step in (1, 2, 2.5, 3, 5, 10):
        if value <= step * base:
            return step * base
    return 10 * base


def axis_label(value):
    return f"{value:g}" if value >= 1 or value == 0 else f"{value:.1f}"


def _dashed_pen(color, width=1.0, dash=(4, 4)):
    pen = QPen(QColor(color), width)
    pen.setStyle(Qt.CustomDashLine)
    pen.setDashPattern(list(dash))
    return pen


class LatencyChart(QWidget):
    """ms per reply. Gridlines with mono y labels, optional dashed avg and lost markers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(160)
        self.replies = []        # list of (sequence, ms or None)
        self.expected = 20
        self.avg = None
        self.show_lost = True

    def reset(self, expected):
        self.replies, self.expected, self.avg = [], max(2, expected), None
        self.update()

    def add_reply(self, sequence, ms):
        self.replies.append((sequence, ms))
        self.update()

    def set_avg(self, avg):
        self.avg = avg
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        left, right, top, bottom = 38, 14, 12, 8
        plot = QRectF(left, top, self.width() - left - right, self.height() - top - bottom)

        values = [ms for _seq, ms in self.replies if ms is not None]
        peak = max(values) if values else 0
        # Three gridlines on a readable step (e.g. 10/20/30 or 5/10/15)
        step = nice_ceiling(max(peak * 1.15, 0.3) / 3) if peak else 10
        y_max = step * 3

        p.setFont(mono_font(11))
        metrics = QFontMetricsF(p.font())
        for i in range(0, 4):
            value = step * i
            y = plot.bottom() - plot.height() * value / y_max
            p.setPen(QPen(QColor(Colors.BORDER), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            if i > 0:
                p.setPen(QColor(Colors.TEXT_MUTED))
                text = axis_label(value)
                p.drawText(QPointF(4, y + metrics.ascent() / 2 - 1), text)

        def x_of(sequence):
            return plot.left() + plot.width() * (sequence - 1) / (self.expected - 1)

        def y_of(ms):
            return plot.bottom() - plot.height() * min(ms, y_max) / y_max

        if self.show_lost:
            p.setPen(_dashed_pen(Colors.RED, 1.2, (3, 3)))
            for sequence, ms in self.replies:
                if ms is None:
                    x = x_of(sequence)
                    p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        if self.avg is not None:
            p.setPen(_dashed_pen(Colors.TEXT_MUTED, 1.2, (4, 3)))
            y = y_of(self.avg)
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        path = QPainterPath()
        started = False
        for sequence, ms in self.replies:
            if ms is None:
                continue
            point = QPointF(x_of(sequence), y_of(ms))
            if not started:
                path.moveTo(point)
                started = True
            else:
                path.lineTo(point)
        pen = QPen(QColor(Colors.BLUE), 2)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if len(values) == 1:
            p.setBrush(QColor(Colors.BLUE))
            p.drawEllipse(path.currentPosition(), 2.5, 2.5)


class Sparkline(QWidget):
    """Gateway latency over time, blue 1.6px with a baseline."""

    def __init__(self, capacity=300, parent=None):
        super().__init__(parent)
        self.capacity = capacity
        self.values = []
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def add(self, value):
        self.values.append(value)
        if len(self.values) > self.capacity:
            self.values.pop(0)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 6, self.width() - 2, self.height() - 12)
        p.setPen(QPen(QColor(Colors.BORDER), 1))
        p.drawLine(QPointF(rect.left(), rect.bottom()), QPointF(rect.right(), rect.bottom()))
        data = [v for v in self.values if v is not None]
        if not data:
            p.setPen(QColor(Colors.TEXT_MUTED))
            p.setFont(ui_font(12))
            p.drawText(rect, Qt.AlignCenter, "Collecting samples…")
            return
        top = max(data) * 1.6 or 1
        count = max(len(self.values), 2)
        path = QPainterPath()
        started = False
        for i, value in enumerate(self.values):
            x = rect.left() + rect.width() * i / (count - 1)
            if value is None:
                p.setPen(_dashed_pen(Colors.RED, 1, (2, 2)))
                p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                started = False
                continue
            y = rect.bottom() - rect.height() * value / top
            if started:
                path.lineTo(x, y)
            else:
                path.moveTo(x, y)
                started = True
        pen = QPen(QColor(Colors.BLUE), 1.6)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)


class ThroughputChart(QWidget):
    """Mbps over seconds for one phase; dotted reference line at half the scale."""

    def __init__(self, color=Colors.BLUE, footer=True, parent=None):
        super().__init__(parent)
        self.color = color
        self.samples = []  # (seconds, mbps)
        self.footer = footer
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def reset(self, color=None):
        if color:
            self.color = color
        self.samples = []
        self.update()

    def add(self, seconds, mbps):
        self.samples.append((seconds, mbps))
        self.update()

    def set_samples(self, samples):
        self.samples = list(samples)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        footer_h = 22 if self.footer else 0
        plot = QRectF(0, 8, self.width(), self.height() - 8 - footer_h - 6)
        x_max = max(15.0, self.samples[-1][0] if self.samples else 0)
        peak = max((m for _t, m in self.samples), default=0)
        y_max = nice_ceiling(peak * 1.15) if peak > 0 else 300
        reference = y_max / 2

        p.setPen(QPen(QColor(Colors.BORDER), 1))
        p.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))
        ref_y = plot.bottom() - plot.height() * reference / y_max
        p.setPen(_dashed_pen(Colors.BORDER, 1, (2, 3)))
        p.drawLine(QPointF(plot.left(), ref_y), QPointF(plot.right(), ref_y))

        if self.footer:
            p.setFont(mono_font(11))
            p.setPen(QColor(Colors.TEXT_MUTED))
            footer = QRectF(0, self.height() - footer_h, self.width(), footer_h)
            p.drawText(footer, Qt.AlignLeft | Qt.AlignVCenter, "0 s")
            p.drawText(footer, Qt.AlignHCenter | Qt.AlignVCenter, f"{reference:g} Mbps line")
            p.drawText(footer, Qt.AlignRight | Qt.AlignVCenter, f"{x_max:.0f} s")

        if not self.samples:
            return
        path = QPainterPath(QPointF(plot.left(), plot.bottom()))
        for seconds, mbps in self.samples:
            x = plot.left() + plot.width() * seconds / x_max
            y = plot.bottom() - plot.height() * min(mbps, y_max) / y_max
            path.lineTo(x, y)
        pen = QPen(QColor(self.color), 1.8)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPath(path)


class SpeedGauge(QWidget):
    """270 degree arc gauge: track #323842, value in the phase colour, mono value in the centre."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = None
        self.color = Colors.BLUE
        self.phase = ""
        self.unit = "Mbps"
        self.setMinimumSize(240, 240)

    def set_value(self, value, color=None, phase=None, unit=None):
        self.value = value
        if color:
            self.color = color
        if phase is not None:
            self.phase = phase
        if unit:
            self.unit = unit
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height(), 300)
        radius = size * 0.4
        center = QPointF(self.width() / 2, self.height() / 2)
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)

        track = QPen(QColor(Colors.SURFACE_2), 14)
        track.setCapStyle(Qt.RoundCap)
        p.setPen(track)
        p.drawArc(rect, 225 * 16, -270 * 16)

        if self.value:
            scale = max(300, nice_ceiling(self.value))
            fraction = min(self.value / scale, 1.0)
            pen = QPen(QColor(self.color), 14)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 225 * 16, int(-270 * 16 * fraction))

        if self.phase:
            p.setFont(section_font(10.5))
            p.setPen(QColor(self.color))
            p.drawText(QRectF(0, center.y() - 52, self.width(), 18), Qt.AlignCenter, self.phase.upper())
        p.setFont(mono_font(38, 500))
        p.setPen(QColor(Colors.TEXT_STRONG if self.value is not None else Colors.TEXT_FAINT))
        text = "—" if self.value is None else f"{self.value:.1f}"
        p.drawText(QRectF(0, center.y() - 30, self.width(), 52), Qt.AlignCenter, text)
        p.setFont(ui_font(12.5))
        p.setPen(QColor(Colors.TEXT_MUTED))
        p.drawText(QRectF(0, center.y() + 22, self.width(), 20), Qt.AlignCenter, self.unit)


class ConnectionPath(QWidget):
    """This PC -> Gateway -> DNS -> Internet: nodes joined by lines with latency labels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes = [
            {'name': 'This PC', 'status': 'unknown', 'detail': '…', 'ms': None},
            {'name': 'Gateway', 'status': 'unknown', 'detail': '…', 'ms': None},
            {'name': 'DNS', 'status': 'unknown', 'detail': '…', 'ms': None},
            {'name': 'Internet', 'status': 'unknown', 'detail': '…', 'ms': None},
        ]
        self.setFixedHeight(40)

    def set_nodes(self, nodes):
        self.nodes = nodes
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        name_font, detail_font, label_font = ui_font(13, 600), mono_font(11), mono_font(11)
        name_m, detail_m = QFontMetricsF(name_font), QFontMetricsF(detail_font)

        widths = []
        for node in self.nodes:
            widths.append(max(16 + name_m.horizontalAdvance(node['name']),
                              16 + detail_m.horizontalAdvance(node['detail'])))
        count = len(self.nodes)
        span = self.width() - widths[-1]
        xs = [span * i / (count - 1) for i in range(count)]

        name_y, detail_y = 15, 33
        for i, node in enumerate(self.nodes):
            x = xs[i]
            status = node['status']
            color = {'ok': Colors.GREEN, 'fail': Colors.RED}.get(status, Colors.TEXT_MUTED)
            if status == 'unknown':
                p.setPen(QPen(QColor(Colors.TEXT_MUTED), 1.4))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(x + 5, name_y - 5), 4.3, 4.3)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(color))
                p.drawEllipse(QPointF(x + 5, name_y - 5), 5, 5)
            p.setFont(name_font)
            p.setPen(QColor({'fail': Colors.RED, 'unknown': Colors.TEXT_MUTED}.get(status, Colors.TEXT_STRONG)))
            p.drawText(QPointF(x + 17, name_y), node['name'])
            p.setFont(detail_font)
            p.setPen(QColor(Colors.TEXT_MUTED))
            p.drawText(QPointF(x + 17, detail_y), node['detail'])

            if i + 1 < count:
                nxt = self.nodes[i + 1]
                x1, x2 = x + widths[i] + 12, xs[i + 1] - 12
                if x2 - x1 < 20:
                    continue
                line_y = 21
                if nxt['status'] == 'ok':
                    p.setPen(QPen(qcolor(Colors.GREEN, 0.7), 1.6))
                    label, label_color = (f"{nxt['ms']:.1f} ms" if nxt.get('ms') is not None else ""), Colors.GREEN
                elif nxt['status'] == 'fail':
                    p.setPen(_dashed_pen(Colors.RED, 1.6, (3, 2.5)))
                    label, label_color = "timeout", Colors.RED
                else:
                    p.setPen(_dashed_pen(Colors.TEXT_FAINT, 1.2, (3, 3)))
                    label, label_color = "—", Colors.TEXT_FAINT
                p.drawLine(QPointF(x1, line_y), QPointF(x2, line_y))
                if label:
                    p.setFont(label_font)
                    p.setPen(QColor(label_color))
                    p.drawText(QRectF(x1, 0, x2 - x1, line_y - 3), Qt.AlignHCenter | Qt.AlignBottom, label)
