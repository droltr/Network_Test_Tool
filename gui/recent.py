"""Recent test results, persisted with QSettings so the Dashboard can list them."""
import json
import uuid
from datetime import datetime

from PyQt5.QtCore import QObject, QSettings, pyqtSignal

MAX_ENTRIES = 30


class RecentStore(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = QSettings("NetworkTools", "NetworkTestTool")
        try:
            self.entries = json.loads(self.settings.value("recent_results", "[]", type=str))
        except (TypeError, ValueError):
            self.entries = []
        # QSettings can contain records written by older versions or left
        # incomplete by an interrupted write. Keep valid records so one bad
        # entry cannot prevent the dashboard from opening.
        entries = self.entries
        if isinstance(entries, list):
            self.entries = [entry for entry in entries
                            if isinstance(entry, dict)
                            and isinstance(entry.get('kind'), str)
                            and entry['kind'].strip()]
        else:
            self.entries = []
        if self.entries != entries:
            self.settings.setValue("recent_results", json.dumps(self.entries))

    def add(self, kind, target, summary, data=None):
        """kind: 'diagnose', 'port', 'speed' or 'iperf'. Returns the stored entry."""
        entry = {
            'id': uuid.uuid4().hex,
            'kind': kind,
            'target': target,
            'summary': summary,
            'time': datetime.now().isoformat(timespec='seconds'),
            'data': data or {},
        }
        self.entries.insert(0, entry)
        del self.entries[MAX_ENTRIES:]
        self.settings.setValue("recent_results", json.dumps(self.entries))
        self.changed.emit()
        return entry

    def items(self, kind=None):
        return [e for e in self.entries
                if isinstance(e, dict) and e.get('kind') and (kind is None or e.get('kind') == kind)]

    def latest(self, kind):
        return next(iter(self.items(kind)), None)

    def get(self, entry_id):
        return next((e for e in self.entries if isinstance(e, dict) and e.get('id') == entry_id), None)


_store = None


def recent_store():
    global _store
    if _store is None:
        _store = RecentStore()
    return _store


KIND_TITLES = {'diagnose': "Diagnose host", 'port': "Port scan", 'speed': "Speed test", 'iperf': "iPerf3",
               'monitor': "Monitor session"}
