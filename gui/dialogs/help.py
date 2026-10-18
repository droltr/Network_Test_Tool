"""Help window and About dialog.

The user guide is the Markdown in docs/, the same files the repository documents with,
so the in-app help and the online documentation never drift apart.
"""
import os

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QPalette, QColor
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem, QTextBrowser,
                             QFrame, QLabel, QGridLayout, QWidget, QScrollArea)

from version import __version__
from gui.styles.modern_theme import Colors, Theme, ui_font, section_font
from gui.widgets.common import Label, button, section_label
from gui.widgets.sidebar import AppMark
from utils.paths import resource_path

TOPICS = [
    ("Purpose of this tool", "Home.md"),
    ("Installation and setup", "Installation.md"),
    ("Dashboard", "User-Guide-Network-Status.md"),
    ("Diagnostic tools", "User-Guide-Diagnostic-Tools.md"),
    ("iPerf3", "User-Guide-iPerf3.md"),
    ("Network health", "User-Guide-Network-Health.md"),
    ("Ask AI agent", "User-Guide-Ask-AI.md"),
    ("Reports and logs", "Reporting.md"),
    ("Troubleshooting and FAQ", "Troubleshooting.md"),
    ("Privacy and security", "Security.md"),
]

REPOSITORY = "https://github.com/droltr/Network_Test_Tool"

# Third-party parts: name, what it does in this app, license, link
CREDITS = [
    ("speedtest-cli", "Speed test engine (bundled, unmodified)", "Apache 2.0",
     "https://github.com/sivel/speedtest-cli", "Matt Martz"),
    ("iperf3 protocol", "The built-in iPerf3 client and server speak this protocol; written from scratch, "
     "no iperf3 code included", "BSD-3-Clause (iperf3)", "https://github.com/esnet/iperf", "ESnet"),
    ("Public iPerf3 Serverlist", "List of public iPerf3 servers (bundled snapshot and online refresh)", "MIT",
     "https://github.com/R0GGER/public-iperf3-servers", "R0GGER"),
    ("Qt 5 / PyQt5", "User interface toolkit", "LGPL v3 (Qt) / GPL v3 (PyQt5)",
     "https://www.riverbankcomputing.com/software/pyqt/", "The Qt Company, Riverbank Computing"),
    ("psutil", "Network interfaces, connections and counters", "BSD-3-Clause",
     "https://github.com/giampaolo/psutil", "Giampaolo Rodola"),
    ("Jost", "Interface font of the Bauhaus themes", "SIL OFL 1.1",
     "https://github.com/indestructible-type/Jost", "The Jost Project Authors"),
    ("IBM Plex Sans", "Interface font of the One Dark theme", "SIL OFL 1.1", "https://github.com/IBM/plex",
     "IBM Corp."),
    ("JetBrains Mono", "Font for numbers, addresses and logs", "SIL OFL 1.1",
     "https://github.com/JetBrains/JetBrainsMono", "The JetBrains Mono Project Authors"),
]


def _docs_dir():
    return resource_path("docs")


class HelpDialog(QDialog):
    def __init__(self, topic_file="Home.md", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Network Test Tool help")
        self.resize(1080, 760)
        self.setStyleSheet(f"QDialog {{ background: {Colors.BG}; }}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(250)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 18, 0, 12)
        side_layout.setSpacing(8)
        title = QLabel("HELP" if Theme.BAUHAUS else "Help")
        title.setFont(section_font(14) if Theme.BAUHAUS else ui_font(15, 600))
        title.setStyleSheet(f"color: {Colors.SIDEBAR_TEXT}; background: transparent; padding-left: 16px;")
        side_layout.addWidget(title)
        self.topics = QListWidget()
        self.topics.setFont(ui_font(13.5 if Theme.BAUHAUS else 12.5))
        self.topics.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; color: {Colors.SIDEBAR_TEXT}; outline: none; }}"
            f"QListWidget::item {{ padding-left: 16px; height: 36px; border: none; }}"
            f"QListWidget::item:hover {{ background: {Colors.NAV_HOVER_BG}; }}"
            f"QListWidget::item:selected {{ background: {Colors.NAV_ACTIVE_BG}; color: {Colors.NAV_ACTIVE_TEXT}; }}")
        for name, filename in TOPICS:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, filename)
            self.topics.addItem(item)
        self.topics.currentItemChanged.connect(lambda item, _prev: item and self.load(item.data(Qt.UserRole)))
        side_layout.addWidget(self.topics, 1)
        online = button("Open online documentation", "ghost", 36)
        online.setStyleSheet(f"QPushButton {{ background: transparent; color: {Colors.HEADING_BADGE_BG}; "
                             f"border: 2px solid {Colors.HEADING_BADGE_BG}; border-radius: {Theme.RADIUS_CONTROL}px; }}"
                             f"QPushButton:hover {{ background: {Colors.HEADING_BADGE_BG}; "
                             f"color: {Colors.HEADING_BADGE_TEXT}; }}")
        online.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"{REPOSITORY}/tree/master/docs")))
        online_row = QHBoxLayout()
        online_row.setContentsMargins(12, 0, 12, 0)
        online_row.addWidget(online)
        side_layout.addLayout(online_row)
        layout.addWidget(side)

        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self.follow)
        self.view.setFont(ui_font(13.5))
        self.view.document().setDocumentMargin(28)
        palette = self.view.palette()
        palette.setColor(QPalette.Base, QColor(Colors.BG))
        palette.setColor(QPalette.Text, QColor(Colors.TEXT))
        palette.setColor(QPalette.Link, QColor(Colors.BLUE))
        self.view.setPalette(palette)
        self.view.setStyleSheet(f"QTextBrowser {{ border: none; background: {Colors.BG}; color: {Colors.TEXT}; }}")
        layout.addWidget(self.view, 1)
        self.select(topic_file)

    def select(self, filename):
        for row in range(self.topics.count()):
            if self.topics.item(row).data(Qt.UserRole) == filename:
                self.topics.setCurrentRow(row)
                return
        self.load(filename)

    def load(self, filename):
        path = os.path.join(_docs_dir(), filename)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = f"# Not found\n\nThe help page `{filename}` is missing from this build."
        self.view.setMarkdown(text)
        self.view.verticalScrollBar().setValue(0)

    def follow(self, url):
        target = url.toString()
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
        elif target.endswith(".md") and "/" not in target:
            self.select(target)
        elif target.startswith("../"):
            QDesktopServices.openUrl(QUrl(f"{REPOSITORY}/blob/master/{target[3:]}"))


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Network Test Tool")
        self.resize(820, 680)
        self.setStyleSheet(f"QDialog {{ background: {Colors.BG}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(AppMark(64, ground="#141414"))
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(Label("Network Test Tool", 22, 700, Colors.TEXT_STRONG))
        names.addWidget(Label(f"Version {__version__}", 12.5, color=Colors.TEXT_MUTED, mono=True))
        head.addLayout(names)
        head.addStretch(1)
        outer.addLayout(head)

        purpose = Label("A desktop tool for finding where a network connection breaks and why: diagnostics, speed "
                        "and iPerf3 tests, a health scan for leftover VPN settings, a connection monitor and "
                        "reports you can hand to your own AI assistant.", 13, color=Colors.TEXT)
        purpose.setWordWrap(True)
        outer.addWidget(purpose)

        facts = QGridLayout()
        facts.setHorizontalSpacing(18)
        facts.setVerticalSpacing(6)
        for row, (key, value, link) in enumerate((
                ("Author", "droltr", None),
                ("License", "MIT — free to use, change and share", None),
                ("Source code", REPOSITORY, REPOSITORY))):
            facts.addWidget(Label(key, 12.5, 600, Colors.TEXT_MUTED), row, 0)
            value_label = Label(f'<a href="{link}" style="color:{Colors.BLUE}">{value}</a>' if link else value,
                                12.5, color=Colors.TEXT)
            value_label.setOpenExternalLinks(True)
            facts.addWidget(value_label, row, 1)
        facts.setColumnStretch(1, 1)
        outer.addLayout(facts)

        outer.addWidget(section_label("Built with and includes"))
        intro = Label("This app stands on other people's work. Each part keeps its own license; the full texts "
                      "are in the licenses folder and THIRD_PARTY_NOTICES.md.", 12, color=Colors.TEXT_MUTED)
        intro.setWordWrap(True)
        outer.addWidget(intro)

        table = QWidget()
        grid = QGridLayout(table)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        for column, title in enumerate(("Component", "Used for", "License")):
            header = QLabel(title.upper())
            header.setFont(section_font(10.5))
            header.setStyleSheet(f"color: {Colors.TEXT_MUTED}; background: transparent;")
            grid.addWidget(header, 0, column)
        for row, (name, use, license_name, link, author) in enumerate(CREDITS, start=1):
            name_label = Label(f'<a href="{link}" style="color:{Colors.BLUE}">{name}</a><br>'
                               f'<span style="color:{Colors.TEXT_MUTED}; font-weight:400">'
                               f'{author}</span>', 12.5, 600, Colors.TEXT_STRONG)
            name_label.setOpenExternalLinks(True)
            use_label = Label(use, 12, color=Colors.TEXT)
            use_label.setWordWrap(True)
            license_label = Label(license_name, 11.5, color=Colors.TEXT, mono=True)
            license_label.setWordWrap(True)
            for column, widget in enumerate((name_label, use_label, license_label)):
                widget.setAlignment(Qt.AlignTop | Qt.AlignLeft)
                grid.addWidget(widget, row, column)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 190)
        grid.setColumnMinimumWidth(2, 170)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(table)
        outer.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        licenses = button("Open license texts", "secondary", 32)
        licenses.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(resource_path("licenses"))))
        notices = button("Third-party notices", "secondary", 32)
        notices.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(resource_path("THIRD_PARTY_NOTICES.md"))))
        close = button("Close", "primary", 32)
        close.clicked.connect(self.accept)
        buttons.addWidget(licenses)
        buttons.addWidget(notices)
        buttons.addStretch(1)
        buttons.addWidget(close)
        outer.addLayout(buttons)
