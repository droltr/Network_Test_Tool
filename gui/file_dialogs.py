"""Open/save dialogs with useful defaults.

Windows and macOS keep the native dialog through Qt's static helpers: Qt's own dialog probes
every drive on the GUI thread and freezes the app while an unreachable mapped network drive
times out. Elsewhere a QFileDialog instance is used, which is still native when the desktop
provides one and otherwise gets a sidebar with the usual user folders.
"""
import os
import sys

from PyQt5.QtCore import QStandardPaths, QUrl
from PyQt5.QtWidgets import QFileDialog

_NATIVE_PLATFORMS = ("win32", "darwin")

_SIDEBAR_LOCATIONS = (QStandardPaths.DesktopLocation, QStandardPaths.DocumentsLocation,
                      QStandardPaths.DownloadLocation, QStandardPaths.HomeLocation)


def sidebar_urls():
    """Desktop, Documents, Downloads and Home that exist on this machine, without duplicates."""
    urls, seen = [], set()
    for location in _SIDEBAR_LOCATIONS:
        path = QStandardPaths.writableLocation(location)
        if path and os.path.isdir(path) and os.path.normcase(path) not in seen:
            seen.add(os.path.normcase(path))
            urls.append(QUrl.fromLocalFile(path))
    return urls


def default_save_dir():
    """Documents, else Desktop, else the home folder (never the working directory)."""
    for location in (QStandardPaths.DocumentsLocation, QStandardPaths.DesktopLocation):
        path = QStandardPaths.writableLocation(location)
        if path and os.path.isdir(path):
            return path
    return os.path.expanduser("~")


def build_dialog(parent, caption, start, name_filter="", directory_only=False, options=None):
    """A configured QFileDialog; start is a folder or a file path to preselect."""
    dialog = QFileDialog(parent, caption, "", name_filter)
    if options is not None:
        dialog.setOptions(options)
    if directory_only:
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        dialog.setDirectory(start)
    else:
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setDirectory(os.path.dirname(start))
        dialog.selectFile(os.path.basename(start))
    dialog.setSidebarUrls(sidebar_urls())
    return dialog


def _start_path(start):
    start = os.path.expanduser(start or "")
    if not os.path.isabs(start):
        start = os.path.join(default_save_dir(), start)
    return os.path.normpath(start)


def get_save_file_name(parent, caption, start, name_filter=""):
    """Like QFileDialog.getSaveFileName; a bare file name starts in default_save_dir(). Returns a path or ''."""
    start = _start_path(start)
    if sys.platform in _NATIVE_PLATFORMS:
        return QFileDialog.getSaveFileName(parent, caption, start, name_filter)[0]
    dialog = build_dialog(parent, caption, start, name_filter)
    return dialog.selectedFiles()[0] if dialog.exec_() and dialog.selectedFiles() else ""


def get_existing_directory(parent, caption, start=""):
    """Like QFileDialog.getExistingDirectory, starting at default_save_dir() when start is empty."""
    start = _start_path(start)
    # A folder that does not exist yet would open the dialog in the working directory
    while start and not os.path.isdir(start) and os.path.dirname(start) != start:
        start = os.path.dirname(start)
    if sys.platform in _NATIVE_PLATFORMS:
        return QFileDialog.getExistingDirectory(parent, caption, start)
    dialog = build_dialog(parent, caption, start, directory_only=True)
    return dialog.selectedFiles()[0] if dialog.exec_() and dialog.selectedFiles() else ""
