"""Page shell: a 48px header (title, subtitle, actions) above the page body."""
import html

from PyQt5 import sip
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QWidget, QFrame, QHBoxLayout, QVBoxLayout, QScrollArea

from gui.file_dialogs import get_save_file_name
from gui.styles import modern_theme
from gui.styles.modern_theme import Colors, mono_font, ui_font
from gui.widgets.common import Label


# Threads that did not finish in time; referenced here so they are never destroyed while running
_detached_threads = []


def finish_thread(thread, timeout_ms):
    """Wait at most timeout_ms for a QThread to finish; never blocks the GUI thread longer.

    A thread that is still running (e.g. stuck in a DNS lookup that cannot be interrupted) is detached:
    unparented, owned by C++ and kept referenced at module level, so neither its parent nor Python
    destroys the QThread object while it runs ("QThread: Destroyed while thread is still running" aborts
    the app). It finishes on its own, or the process exits without waiting for it.
    Returns True if the thread has finished."""
    if thread is None or not thread.isRunning() or thread.wait(timeout_ms):
        return True
    thread.setParent(None)
    sip.transferto(thread, None)
    _detached_threads.append(thread)
    return False


class PageHeader(QFrame):
    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        self.setObjectName("pageHeader")
        self.setFixedHeight(48)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(10)
        self.title = Label(title, 15, 600, Colors.TEXT_STRONG)
        self.subtitle = Label(subtitle, 12.5, color=Colors.TEXT_MUTED)
        layout.addWidget(self.title)
        layout.addSpacing(2)
        self.tabs = QHBoxLayout()
        self.tabs.setSpacing(18)
        layout.addLayout(self.tabs)
        layout.addWidget(self.subtitle)
        layout.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def set_subtitle(self, text, mono=False):
        self.subtitle.setFont(mono_font(12) if mono else ui_font(12.5))
        self.subtitle.setText(text)

    def set_subtitle_parts(self, mono_text, text):
        """Mono host or address followed by muted UI text, e.g. '8.8.8.8 · completed 19:04'."""
        self.subtitle.setFont(ui_font(12.5))
        self.subtitle.setText(f'<span style="font-family: \'{modern_theme.MONO_FAMILY}\'; font-size: 9pt;">'
                              f'{html.escape(mono_text)}</span>&nbsp;&nbsp;· {html.escape(text)}')

    def set_actions(self, *buttons):
        """Show exactly these action buttons (others added before are hidden)."""
        for i in range(self.actions.count()):
            widget = self.actions.itemAt(i).widget()
            if widget:
                widget.setVisible(widget in buttons)
        for btn in buttons:
            if self.actions.indexOf(btn) < 0:
                self.actions.addWidget(btn)
            btn.setVisible(True)


class Page(QWidget):
    """Base class for sidebar pages."""

    running_changed = pyqtSignal(bool)
    navigate = pyqtSignal(str, object)   # page key, payload

    def __init__(self, title, subtitle="", scroll=False, parent=None):
        super().__init__(parent)
        self.setObjectName("pageBody")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = PageHeader(title, subtitle)
        outer.addWidget(self.header)

        self.body_widget = QWidget()
        self.body = QVBoxLayout(self.body_widget)
        self.body.setContentsMargins(20, 18, 20, 18)
        self.body.setSpacing(12)
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            area.setWidget(self.body_widget)
            outer.addWidget(area, 1)
        else:
            outer.addWidget(self.body_widget, 1)
        self._running = False

    def set_running(self, running):
        if running != self._running:
            self._running = running
            self.running_changed.emit(running)

    @property
    def running(self):
        return self._running

    def handle_request(self, payload):
        """Called when another page navigates here with a payload."""

    def cleanup(self):
        """Stop threads and timers before the window closes."""

    def save_text(self, title, default_name, text):
        """Ask where to save text (native dialog where available). Returns the chosen path or None."""
        path = get_save_file_name(self, title, default_name, "Text Files (*.txt);;All Files (*)")
        if not path:
            return None
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        return path
