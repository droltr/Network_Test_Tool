# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2025-12-23

### Added
- **Intelligent Diagnostics:** Automatic detection of APIPA, DNS failures, and gateway issues.
- **Quick Actions:** Added "Renew IP", "Flush DNS", and "Release IP" buttons to Network Status.
- **Trace Route:** New tab for visual trace route with latency analysis.
- **Advanced Tools:** New tab with ARP Table, Active Connections, and NetBIOS Lookup.
- **Reporting:** Added "Generate Report" feature (Text, JSON, CSV export).
- **Status Indicator:** Visual Online/Local/Offline indicator in the main window header.
- **Export Features:** Added timestamped file export to Ping Test, Port Scanner, Speed Test, and Troubleshooter.

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
