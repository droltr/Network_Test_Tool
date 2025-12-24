# Development Guidelines & Project Standards

This document outlines the development standards, user preferences, and workflow requirements established during the development of the Network Test Tool. Use this as a reference for all future coding tasks to ensure consistency.

## 1. Core Philosophy & Security
*   **Privacy First:** NEVER include hardcoded secrets, passwords, API keys, or personal IP addresses in the source code.
*   **Gitignore:** Strictly maintain `.gitignore` to exclude `*.log`, `*.txt` (reports), `*.csv`, `*.json`, and build artifacts (`dist/`, `build/`).
*   **Clean Repository:** Temporary files (test results, logs) should be moved to a `.deleted/` directory or deleted, never left in the root.

## 2. UI/UX Standards (PyQt5)
*   **Theme:** Strict **Dark Theme**. Ensure no white backgrounds appear in tables, lists, or inputs (e.g., `QTableWidget` rows must alternate between dark shades).
*   **Compactness:** UI elements (especially buttons and panels) should be compact. Avoid wasting screen space.
*   **Sorting Logic:**
    1.  **Active & APIPA** adapters MUST appear at the top.
    2.  Inactive adapters at the bottom.
    3.  Secondary sort: Alphabetical by name.
*   **Visual Feedback:**
    *   Use color-coded indicators (Green=Online, Yellow=Local/APIPA, Red=Offline).
    *   APIPA (169.254.x.x) must be clearly flagged (e.g., Yellow badge) inside the adapter card.
*   **Interaction:**
    *   "Quick Actions" must allow selecting a specific target adapter (ComboBox) or "All Adapters".

## 3. Functional Requirements
*   **Exporting:**
    *   ALL export features must suggest an auto-generated filename with a timestamp.
    *   Format: `filename_YYYYMMDD_HHMMSS.txt`.
    *   User must be able to change the filename via a File Dialog.
*   **Troubleshooter:**
    *   Must not only detect errors but provide **[SUGGESTION]** lines in the log explaining how to fix them (e.g., "Check physical cable").
*   **Cross-Platform:**
    *   Code must handle Windows (`ipconfig`) and Linux (`ip`, `ifconfig`) command differences gracefully.

## 4. Development Workflow
1.  **Start:** Use `run.bat` (Windows) for quick application launch and testing.
2.  **Testing:** Run `test_suite.py` to verify core logic (Network Detector, Ping, Trace, etc.) before UI integration.
3.  **Version Control:**
    *   Commit changes before starting a major refactor.
    *   Keep `CHANGELOG.md`, `ROADMAP.md`, and `README.md` updated with every feature release.
4.  **Documentation:**
    *   Maintain a `docs/` directory for detailed Wiki-style documentation.
    *   Link these docs in the main `README.md`.

## 5. Build & Release
*   **Tool:** Use `PyInstaller`.
*   **Configuration:**
    *   Windows: `--noconsole` (unless debugging is needed), `--onefile`.
    *   Linux: `--noconsole`, `--onefile`.
*   **Automation:** Use GitHub Actions (`.github/workflows/build.yml`) to auto-generate releases on tag push (`v*`).

## 6. Specific "Do Not Forget" Items
*   **Trace Route:** Ensure table rows are not white.
*   **Quick Actions:** Ensure buttons are distinct and modern (transparent background with colored borders).
*   **Logs:** Ensure `network_detector_debug.log` is generated for debugging but ignored by git.
