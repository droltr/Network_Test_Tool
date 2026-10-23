import os
import subprocess
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


def console_encoding():
    """Code page that Windows console tools (ipconfig, arp, ping, tracert, nbtstat) write to a pipe.

    They use the OEM code page (cp857 on Turkish systems, cp850 on Western European ones), not the
    ANSI code page Python assumes by default. Returns None on other platforms (locale default).
    """
    if not sys.platform.startswith('win'):
        return None
    try:
        import ctypes
        code_page = ctypes.windll.kernel32.GetOEMCP()
    except (AttributeError, OSError):
        code_page = 0
    return 'utf-8' if code_page == 65001 else (f'cp{code_page}' if code_page else 'cp850')


def decode_output(data):
    """Decode raw command output: UTF-8 when valid (newer netsh writes UTF-8 to a pipe),
    otherwise the console code page. Never raises."""
    if data is None:
        return ''
    if isinstance(data, str):
        return data
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode(console_encoding() or 'utf-8', errors='replace')


# Keeps console tools (ping, tracert, netsh) from flashing a window in the windowed .exe
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform.startswith('win') else 0


def run_command(command, timeout=10, **kwargs):
    """subprocess.run for system tools: captured output decoded with decode_output(), no console
    window, the parse-friendly environment and a timeout. Raises like subprocess.run
    (OSError, subprocess.TimeoutExpired)."""
    kwargs.setdefault('capture_output', True)
    kwargs.setdefault('env', command_env())
    kwargs.setdefault('creationflags', NO_WINDOW)
    result = subprocess.run(command, timeout=timeout, **kwargs)
    if kwargs['capture_output']:
        result.stdout, result.stderr = decode_output(result.stdout), decode_output(result.stderr)
    return result
