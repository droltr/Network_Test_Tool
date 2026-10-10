"""'Ask AI agent': prepare a diagnostic package for the user's own AI assistant."""
import os

from PyQt5.QtCore import Qt, QThread, QSettings, QStandardPaths, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QWidget, QCheckBox, QComboBox, QPlainTextEdit,
                             QListWidget, QListWidgetItem, QFileDialog, QApplication, QAbstractItemView)

from gui.recent import recent_store, KIND_TITLES
from gui.styles.modern_theme import Colors, mono_font, ui_font
from gui.widgets.common import (Card, Label, LineInput, section_label, button, link_button, hbox, chip_group,
                                selected_key, relative_time)
from network import ai_handoff


class SnapshotThread(QThread):
    done = pyqtSignal(object)

    def run(self):
        try:
            self.done.emit(ai_handoff.collect_system_snapshot())
        except Exception as e:
            self.done.emit(e)


def default_folder():
    documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
    return os.path.join(documents, "network-test-tool")


class AskAiDialog(QDialog):
    def __init__(self, logs_provider, parent=None):
        """logs_provider() returns {log name: text} for logs collected in this session."""
        super().__init__(parent)
        self.setWindowTitle("Ask AI agent")
        self.resize(1120, 720)
        self.setMinimumSize(980, 640)
        self.setStyleSheet(f"QDialog {{ background: {Colors.BG}; }}")
        self.settings = QSettings("NetworkTools", "AskAi")
        self.logs_provider = logs_provider
        self.snapshot = None
        self.thread = None
        self.last_saved = None

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        # ---------------------------------------------------------------- options
        options = QVBoxLayout()
        options.setSpacing(10)
        intro = Label("Collects this computer's network information and your test results into one file, "
                      "with instructions for an AI assistant. Paste it into ChatGPT, Claude, Gemini or any "
                      "other assistant you use. Nothing is sent by this app.", 12, color=Colors.TEXT)
        intro.setWordWrap(True)
        options.addWidget(intro)

        include = Card(margins=(14, 12, 14, 12), spacing=6)
        include.body.addWidget(section_label("Include"))
        self.include_system = QCheckBox("System, network information and detected issues")
        self.include_system.setChecked(True)
        include.body.addWidget(self.include_system)
        include.body.addWidget(Label("Recent test results", 12, color=Colors.TEXT_MUTED))
        self.results_list = QListWidget()
        self.results_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.results_list.setFixedHeight(130)
        self.results_list.setStyleSheet(f"QListWidget {{ background: {Colors.BG_SUNKEN}; border: 1px solid "
                                        f"{Colors.BORDER}; border-radius: 6px; }}")
        include.body.addWidget(self.results_list)
        self.log_checks = {}
        self.logs_box = QVBoxLayout()
        self.logs_box.setSpacing(4)
        include.body.addLayout(self.logs_box)
        options.addWidget(include)

        analysis = Card(margins=(14, 12, 14, 12), spacing=8)
        analysis.body.addWidget(section_label("Analysis"))
        self.mode_group, mode_row = chip_group(self, list(ai_handoff.MODES.items()), "simple")
        analysis.body.addLayout(hbox(Label("Mode", 12, color=Colors.TEXT_MUTED), mode_row, "stretch", spacing=8))
        self.language = QComboBox()
        self.language.addItems(ai_handoff.ANSWER_LANGUAGES)
        self.language.setFont(ui_font(12))
        self.language.setFixedHeight(30)
        analysis.body.addLayout(hbox(Label("Answer in", 12, color=Colors.TEXT_MUTED), self.language, "stretch",
                                     spacing=8))
        self.question = QPlainTextEdit()
        self.question.setPlaceholderText("Your question (optional), e.g. \"My internet drops for a few seconds "
                                         "every hour. Why?\"")
        self.question.setFont(ui_font(12.5))
        self.question.setFixedHeight(70)
        self.question.setStyleSheet(f"QPlainTextEdit {{ border: 1px solid {Colors.BORDER}; border-radius: 6px; }}")
        analysis.body.addWidget(self.question)
        options.addWidget(analysis)

        privacy = Card(margins=(14, 12, 14, 12), spacing=6)
        privacy.body.addWidget(section_label("Privacy"))
        self.mask_mac = QCheckBox("Mask MAC addresses")
        self.mask_ip = QCheckBox("Mask public IP addresses (local addresses stay visible)")
        self.mask_host = QCheckBox("Mask the computer name")
        for box in (self.mask_mac, self.mask_ip, self.mask_host):
            box.setChecked(True)
            privacy.body.addWidget(box)
        options.addWidget(privacy)
        options.addStretch(1)

        left = QWidget()
        left.setLayout(options)
        left.setFixedWidth(400)
        root.addWidget(left)

        # ---------------------------------------------------------------- preview and output
        right = QVBoxLayout()
        right.setSpacing(10)
        self.preview_info = Label("", 11.5, color=Colors.TEXT_MUTED)
        refresh = link_button("Collect again")
        refresh.clicked.connect(self.collect)
        right.addLayout(hbox(section_label("Preview"), 8, self.preview_info, "stretch", refresh))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(mono_font(11.5))
        self.preview.setStyleSheet(f"QPlainTextEdit {{ border: 1px solid {Colors.BORDER}; border-radius: 8px; }}")
        self.preview.document().setDocumentMargin(10)
        right.addWidget(self.preview, 1)

        self.folder_input = LineInput("Save folder", height=32)
        self.folder_input.setText(self.settings.value("folder", default_folder(), type=str))
        browse = button("Browse…", "secondary", 32)
        browse.clicked.connect(self.choose_folder)
        right.addLayout(hbox(Label("Save folder", 12, color=Colors.TEXT_MUTED), self.folder_input, browse,
                             spacing=8))

        self.copy_btn = button("Copy to clipboard", "primary", 34)
        self.copy_btn.clicked.connect(self.copy)
        self.save_btn = button("Save to folder", "secondary", 34)
        self.save_btn.clicked.connect(self.save_to_folder)
        self.save_as_btn = button("Save as…", "secondary", 34)
        self.save_as_btn.clicked.connect(self.save_as)
        self.status = Label("", 12, color=Colors.TEXT_MUTED)
        self.status.setWordWrap(True)
        self.open_folder = link_button("Open folder")
        self.open_folder.setVisible(False)
        self.open_folder.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.dirname(self.last_saved))))
        close = button("Close", "secondary", 34)
        close.clicked.connect(self.accept)
        right.addLayout(hbox(self.copy_btn, self.save_btn, self.save_as_btn, 10, self.status, self.open_folder,
                             "stretch", close, spacing=8))
        hint = Label("Then open your AI assistant and paste (Ctrl+V), or attach the saved .md file.", 11.5,
                     color=Colors.TEXT_MUTED)
        right.addWidget(hint)
        root.addLayout(right, 1)

        # Rebuild the preview whenever an option changes
        for box in (self.include_system, self.mask_mac, self.mask_ip, self.mask_host):
            box.toggled.connect(self.render)
        self.mode_group.buttonClicked.connect(self.render)
        self.language.currentTextChanged.connect(self.render)
        self.question.textChanged.connect(self.render)
        self.results_list.itemChanged.connect(self.render)

        self.fill_sources()
        self.collect()

    # ---------------------------------------------------------------- sources
    def fill_sources(self):
        self.results_list.blockSignals(True)
        self.results_list.clear()
        for index, entry in enumerate(recent_store().items()[:15]):
            text = (f"{KIND_TITLES.get(entry['kind'], entry['kind'])} · {entry['target']} · {entry['summary']} · "
                    f"{relative_time(entry['time'])}")
            item = QListWidgetItem(text)
            item.setFont(ui_font(12))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if index < 5 else Qt.Unchecked)
            item.setData(Qt.UserRole, entry['id'])
            self.results_list.addItem(item)
        if not self.results_list.count():
            item = QListWidgetItem("No tests yet in this profile.")
            item.setFlags(Qt.NoItemFlags)
            self.results_list.addItem(item)
        self.results_list.blockSignals(False)

        for name, text in self.logs_provider().items():
            box = QCheckBox(f"{name} ({len(text.splitlines())} lines)")
            box.setChecked(True)
            box.toggled.connect(self.render)
            self.logs_box.addWidget(box)
            self.log_checks[name] = (box, text)

    def collect(self):
        if self.thread and self.thread.isRunning():
            return
        self.preview_info.setText("Collecting network information…")
        self.copy_btn.setEnabled(False)
        self.thread = SnapshotThread(self)
        self.thread.done.connect(self.on_snapshot)
        self.thread.start()

    def on_snapshot(self, result):
        self.copy_btn.setEnabled(True)
        if isinstance(result, Exception):
            self.snapshot = {"error": str(result)}
        else:
            self.snapshot = result
        self.render()

    # ---------------------------------------------------------------- package
    def package(self):
        recent = []
        for row in range(self.results_list.count()):
            item = self.results_list.item(row)
            entry_id = item.data(Qt.UserRole)
            if entry_id and item.checkState() == Qt.Checked:
                entry = recent_store().get(entry_id)
                if entry:
                    recent.append(ai_handoff.recent_result_for_ai(entry))
        logs = {name: text for name, (box, text) in self.log_checks.items() if box.isChecked()}
        return ai_handoff.build_package(
            self.snapshot if self.include_system.isChecked() else None,
            recent, logs,
            mode=selected_key(self.mode_group) or "simple",
            question=self.question.toPlainText(),
            answer_language=self.language.currentText(),
            privacy={"mac": self.mask_mac.isChecked(), "public_ip": self.mask_ip.isChecked(),
                     "hostname": self.mask_host.isChecked()})

    def render(self, *_):
        if self.snapshot is None:
            return
        text = self.package()
        scroll = self.preview.verticalScrollBar().value()
        self.preview.setPlainText(text)
        self.preview.verticalScrollBar().setValue(scroll)
        self.preview_info.setText(f"{len(text):,} characters · Markdown with a JSON data block")

    # ---------------------------------------------------------------- output
    def copy(self):
        QApplication.clipboard().setText(self.package())
        self.show_status("Copied. Paste it into your AI assistant.", Colors.GREEN)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose save folder", self.folder_input.text())
        if folder:
            self.folder_input.setText(folder)
            self.settings.setValue("folder", folder)

    def write(self, path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.package())
        except OSError as e:
            self.show_status(f"Could not save: {e}", Colors.RED)
            return
        self.last_saved = path
        self.settings.setValue("folder", os.path.dirname(path))
        self.show_status(f"Saved {path}", Colors.GREEN)
        self.open_folder.setVisible(True)

    def save_to_folder(self):
        folder = self.folder_input.text().strip() or default_folder()
        self.write(os.path.join(os.path.expanduser(folder), ai_handoff.default_filename()))

    def save_as(self):
        start = os.path.join(self.folder_input.text().strip() or default_folder(), ai_handoff.default_filename())
        path, _ = QFileDialog.getSaveFileName(self, "Save diagnostics for AI", start,
                                              "Markdown (*.md);;Text Files (*.txt);;All Files (*)")
        if path:
            self.folder_input.setText(os.path.dirname(path))
            self.write(path)

    def show_status(self, text, color):
        self.status.setText(text)
        self.status.set_color(color)

    def done(self, result):
        if self.thread and self.thread.isRunning():
            self.thread.wait(10000)
        super().done(result)
