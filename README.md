# Network Test Tool

![Build Status](https://img.shields.io/github/actions/workflow/status/droltr/Network_Test_Tool/build.yml?branch=master)
![License](https://img.shields.io/github/license/droltr/Network_Test_Tool)
![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)
![Release](https://img.shields.io/github/v/release/droltr/Network_Test_Tool)

**Version:** 0.7.0
**GitHub:** [https://github.com/droltr/Network_Test_Tool](https://github.com/droltr/Network_Test_Tool)

A modern, comprehensive network diagnostic and troubleshooting utility built with Python and PyQt5.

## 📥 Download

**[Download Latest Release (Windows & Linux)](https://github.com/droltr/Network_Test_Tool/releases/latest)**

No installation required. Just download and run.

## 📸 Screenshots

*(Add screenshots of the application here)*

## Features

*   **Network Status:** Real-time monitoring of network adapters with intelligent sorting (Active/APIPA first).
*   **Intelligent Diagnostics:** Automatic detection of common issues (APIPA, DNS failure, Gateway unreachable) with solution suggestions.
*   **Quick Actions:** One-click IP renewal, DNS flush, and IP release with specific adapter selection.
*   **Trace Route:** Visual trace route tool with hop-by-hop latency and status.
*   **Advanced Tools:** ARP table viewer, active connections monitor, and NetBIOS lookup.
*   **Ping Test:** Advanced ping tool with customizable parameters and graphical results.
*   **Port Scanner:** Multi-threaded port scanner to identify open ports on target hosts.
*   **Speed Test:** Integrated internet speed test (Download, Upload, Ping) against the nearest speedtest.net server, plus a live latency test.
*   **iPerf3:** Built-in iperf3-compatible client and server (no iperf3 install needed). Pick from a list of public iperf3 servers or enter your own; the equivalent iperf3 command is shown for every test.
*   **Reporting:** Generate professional text, JSON, and CSV reports of network status and tests.
*   **Troubleshooter:** Automated network diagnostics to identify common connectivity issues.
*   **Modern UI:** Clean, dark-themed interface designed for ease of use.

## 📚 Documentation

Full documentation is available in the [docs/](docs/) directory:

*   [Home](docs/Home.md)
*   [Installation & Setup](docs/Installation.md)
*   [User Guide: Network Status](docs/User-Guide-Network-Status.md)
*   [User Guide: Diagnostic Tools](docs/User-Guide-Diagnostic-Tools.md)
*   [Reporting & Exporting](docs/Reporting.md)
*   [Troubleshooting & FAQ](docs/Troubleshooting.md)
*   [Security & Privacy](docs/Security.md)

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/droltr/Network_Test_Tool.git
    cd Network_Test_Tool
    ```

2.  **Install dependencies** (a virtual environment is recommended):
    ```bash
    python -m venv .venv
    .venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
    ```

## Usage

Run the application:
```bash
python main.py
```

On Linux, `./run.sh` creates the virtual environment on first start and launches the app.

### Linux notes

*   Uses `ip`, `ping`, `traceroute`, NetworkManager (`nmcli`) and systemd-resolved (`resolvectl`)
    when available. Renew/Release IP and Flush DNS may show a polkit password prompt.
*   NetBIOS lookups need `nmblookup` (package `samba-client`).
*   To accept iPerf3 clients from other devices, open the server port in the firewall,
    e.g. `sudo firewall-cmd --add-port=5201/tcp`.

## Building a single-file app

PyInstaller builds for the operating system it runs on (it cannot cross-compile).
Run the same command on each OS:

```bash
pip install -r requirements.txt pyinstaller
python build.py            # add --clean to start from scratch
```

| OS | Output in `dist/` |
|---|---|
| Linux | `NetworkTestTool-<version>-linux-x86_64` (make it executable and run it) |
| Windows | `NetworkTestTool-<version>-windows-x86_64.exe` |
| macOS | `Network Test Tool.app` |

The fonts, the iPerf3 server list, `THIRD_PARTY_NOTICES.md` and the license texts are bundled
into the executable. Pushing a `v*` tag runs the GitHub Actions workflow, which builds all
three and attaches them to a release.

## Requirements

*   Python 3.9+
*   PyQt5
*   psutil

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct, and the process for submitting pull requests.

## Third-Party Components

This project bundles [speedtest-cli](https://github.com/sivel/speedtest-cli) by Matt Martz
(Apache 2.0, unmodified, in `utils/speedtest.py`), the IBM Plex Sans and JetBrains Mono
fonts (SIL OFL 1.1) and a snapshot of the [public iPerf3 server list](https://github.com/R0GGER/public-iperf3-servers)
by R0GGER (MIT). The iPerf3 feature is an independent implementation of the iperf3 protocol
(no ESnet code included). It depends on PyQt5 (GPL v3) and psutil (BSD-3-Clause). See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the `licenses/` folder.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
