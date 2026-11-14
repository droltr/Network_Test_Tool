# PyInstaller spec: one self-contained executable for the OS it is built on.
# Build with:  python build.py   (PyInstaller cannot cross-compile; run it on each OS.)
import platform
import sys

from version import __version__

OS_NAMES = {"win32": "windows", "darwin": "macos"}
os_name = OS_NAMES.get(sys.platform, "linux")
arch = platform.machine().lower().replace("amd64", "x86_64")
app_name = f"NetworkTestTool-{__version__}-{os_name}-{arch}"

# Everything the app reads at runtime, plus the license texts that must ship with it
datas = [
    ("assets", "assets"),
    ("licenses", "licenses"),
    ("docs", "docs"),            # in-app user guide
    ("LICENSE", "."),
    ("THIRD_PARTY_NOTICES.md", "."),
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=["utils.speedtest"],
    excludes=["tkinter", "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngineCore", "PyQt5.QtQml", "PyQt5.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=app_name,
    console=False,          # GUI app: no terminal window
    upx=False,
    strip=False,
    debug=False,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Network Test Tool.app",
        bundle_identifier="io.github.droltr.networktesttool",
        info_plist={"CFBundleShortVersionString": __version__, "NSHighResolutionCapable": True},
    )
