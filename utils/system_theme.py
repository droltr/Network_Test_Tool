"""Reads the operating system's light/dark setting.

system_prefers_dark() returns True (dark), False (light) or None (unknown). It never
raises. The parse_* helpers are pure so they can be tested with sample output.
"""
import os
import subprocess
import sys

_TIMEOUT = 1.0


def parse_windows_apps_use_light(value):
    """AppsUseLightTheme registry value: 0 = dark, anything else = light."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value == 0


def parse_macos_style(returncode, stdout):
    """`defaults read -g AppleInterfaceStyle`: prints "Dark" in dark mode, fails in light mode."""
    if returncode == 0:
        return (stdout or "").strip().lower() == "dark"
    return False


def parse_gnome_color_scheme(stdout):
    """gsettings color-scheme: 'prefer-dark' = dark, 'prefer-light' = light, 'default' = no preference."""
    text = (stdout or "").strip().strip("'\"").lower()
    if text == "prefer-dark":
        return True
    if text == "prefer-light":
        return False
    return None


def parse_gtk_theme(stdout):
    """gsettings gtk-theme name containing "dark" = dark, any other name = light."""
    text = (stdout or "").strip().strip("'\"").lower()
    if not text:
        return None
    return "dark" in text


def _run(args):
    """Run a command without a shell; returns (returncode, stdout) or None when it cannot run."""
    try:
        env = dict(os.environ, LC_ALL="C")
        proc = subprocess.run(args, capture_output=True, text=True, timeout=_TIMEOUT,
                              env=env, shell=False, stdin=subprocess.DEVNULL)
        return proc.returncode, proc.stdout
    except Exception:
        return None


def _windows():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return parse_windows_apps_use_light(value)
    except Exception:
        return None


def _macos():
    result = _run(["defaults", "read", "-g", "AppleInterfaceStyle"])
    if result is None:
        return None
    return parse_macos_style(*result)


def _linux():
    result = _run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"])
    if result and result[0] == 0:
        answer = parse_gnome_color_scheme(result[1])
        if answer is not None:
            return answer
    result = _run(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"])
    if result and result[0] == 0:
        return parse_gtk_theme(result[1])
    return None


def system_prefers_dark():
    """True = dark, False = light, None = the setting cannot be read."""
    try:
        if sys.platform.startswith("win"):
            return _windows()
        if sys.platform == "darwin":
            return _macos()
        return _linux()
    except Exception:
        return None
