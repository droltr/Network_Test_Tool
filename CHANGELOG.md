# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-10-10

### Added
- **UI redesign:** Sidebar layout with Dashboard, Diagnose host (ping and trace in parallel), Port scanner, Speed test, iPerf3, Network health, Advanced and Troubleshooter pages; idle, running, results and error states; custom-painted latency chart, speed gauge, hop list and port map; bundled IBM Plex Sans and JetBrains Mono fonts.
- **iPerf3:** Built-in iperf3-compatible TCP client and server written in Python (download, upload, both, parallel streams), a bundled list of public iperf3 servers with online refresh, and the equivalent iperf3 command for every test.
- **Network health scan:** Detects leftover VPN routes and adapters, unanswered DNS servers, proxies, MTU black holes, broken IPv6 and a resolv.conf written by VPN tools.
- **Connection monitor:** Probes gateway, DNS and internet continuously, records each outage with its layer and duration, logs interface and IP changes, and writes CSV logs.
- **Ask AI agent:** Packages system information, test results and logs with instructions as Markdown + JSON for the user's own AI assistant; copy to clipboard or save to a folder; masks MAC addresses, public IPs and the computer name.
- **Live latency test** on the Speed test page.
- **Build:** `python build.py` creates a single-file app on Windows, Linux and macOS; GitHub Actions builds all three.
- `THIRD_PARTY_NOTICES.md` and `licenses/` with credits and license texts for bundled components.

### Fixed
- **Linux:** Ping results were counted as timeouts under non-English locales (system tools now run with `LC_ALL=C`).
- **Linux:** ARP table, default gateway (without netifaces), DNS servers behind systemd-resolved, interface state, Renew/Release IP (NetworkManager) and Flush DNS (resolvectl, polkit) now work.
- **Speed test:** Picks the nearest server from speedtest.net's current server list instead of the legacy list (which offered servers 1,400 km away), uses 8 upload threads, and Stop now aborts the test.
- **Speed test:** Running without a progress callback crashed speedtest-cli's worker threads.
- Ping and trace route can be stopped; logs are written to the user state directory instead of the working directory.

## [0.6.2] - 2025-12-24

### Fixed
- **UI:** Fixed white background in Trace Route table rows to match dark theme.
- **Build:** Enabled console output in Windows executable for better error reporting.

### Changed
- **Cleanup:** Moved temporary test logs and reports to cleanup directory.
- **Documentation:** Finalized roadmap and project status.

## [0.6.0] - 2025-12-24

### Added
- **Intelligent Diagnostics:** Automatic detection of APIPA, DNS failures, and gateway issues.
- **Quick Actions:** Added "Renew IP", "Flush DNS", and "Release IP" buttons with adapter selection.
- **Trace Route:** New tab for visual trace route with latency analysis.
- **Advanced Tools:** New tab with ARP Table, Active Connections, and NetBIOS Lookup.
- **Reporting:** Added "Generate Report" feature (Text, JSON, CSV export).
- **Status Indicator:** Visual Online/Local/Offline indicator in the main window header.
- **Export Features:** Added timestamped file export to Ping Test, Port Scanner, Speed Test, and Troubleshooter.
- **UI Improvements:** 
    - Compact Diagnostics panel.
    - APIPA warnings moved to adapter cards.
    - Improved sorting (Active/APIPA first).
    - Modernized Quick Action buttons.

## [0.5.0] - 2024-12-22

### Added
- **Network Status:** Real-time monitoring of adapters with card layout.
- **Ping Test:** Graphical ping tool with history.
- **Port Scanner:** Multi-threaded scanner with export.
- **Troubleshooter:** Automated diagnostics (Ping Gateway/DNS/8.8.8.8, Trace 1.1.1.1).
- **UI:** Modern dark theme with responsive design.
- **Security:** Global exception handling.

### Changed
- Renamed project to "Network Test Tool".
- Updated UI to be cleaner and more professional.
- Removed Speed Test from automated troubleshooter.
- Improved Speed Test reliability (fixed 403 Forbidden error).
- Updated documentation with GitHub links.
