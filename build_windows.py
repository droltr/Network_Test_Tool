# Build script for Windows
# This script uses PyInstaller to create a standalone executable

import os
import subprocess
import sys

def build_windows():
    print("Building Windows Executable...")
    
    # PyInstaller command
    # --onefile: Create a single executable
    # --noconsole: Don't show console window (for GUI apps)
    # --name: Name of the executable
    # --add-data: Include necessary resources (if any)
    # --clean: Clean PyInstaller cache
    
    command = [
        "pyinstaller",
        "--noconsole",
        "--onefile",
        "--name=NetworkTestTool",
        "--clean",
        "main.py"
    ]
    
    try:
        subprocess.check_call(command)
        print("Windows build successful! Check 'dist' folder.")
    except subprocess.CalledProcessError as e:
        print(f"Build failed: {e}")

if __name__ == "__main__":
    build_windows()
