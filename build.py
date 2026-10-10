"""Build a single-file Network Test Tool executable for the current OS.

Usage:
    python build.py            # build into dist/
    python build.py --clean    # remove build/ and dist/ first

PyInstaller cannot cross-compile: run this on Windows for the .exe, on Linux for the
Linux binary and on macOS for the .app. The GitHub Actions workflow does all three.
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(ROOT, "network-test-tool.spec")


def ensure_dependencies():
    missing = []
    for module, package in (("PyQt5", "PyQt5"), ("psutil", "psutil"), ("PyInstaller", "pyinstaller")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        print("Missing build dependencies: " + ", ".join(missing))
        print(f"Install them with:  {sys.executable} -m pip install -r requirements.txt pyinstaller")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clean", action="store_true", help="remove previous build output first")
    args = parser.parse_args()

    ensure_dependencies()
    if args.clean:
        for folder in ("build", "dist"):
            shutil.rmtree(os.path.join(ROOT, folder), ignore_errors=True)

    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", SPEC]
    print("Running:", " ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)

    dist = os.path.join(ROOT, "dist")
    built = sorted(name for name in os.listdir(dist) if name.startswith(("NetworkTestTool", "Network Test Tool")))
    print("\nBuild finished. Output in dist/:")
    for name in built:
        print("  " + os.path.join("dist", name))


if __name__ == "__main__":
    main()
