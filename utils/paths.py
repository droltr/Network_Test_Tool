import os
import sys


def state_dir():
    """Per-user directory for logs and other runtime files (never the working directory)."""
    if sys.platform.startswith('win'):
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        path = os.path.join(base, 'NetworkTestTool')
    else:
        base = os.environ.get('XDG_STATE_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'state')
        path = os.path.join(base, 'network-test-tool')
    os.makedirs(path, exist_ok=True)
    return path


def log_file_path(name):
    return os.path.join(state_dir(), name)


def resource_path(*parts):
    """Absolute path to a bundled resource, also inside a PyInstaller build."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def command_env():
    """Environment for running system tools: forces English output on POSIX so it can be parsed
    (e.g. ping prints 'zaman=' instead of 'time=' under a Turkish locale)."""
    if sys.platform.startswith('win'):
        return None
    return {**os.environ, 'LC_ALL': 'C'}
