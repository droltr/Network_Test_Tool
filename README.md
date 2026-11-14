# Network Test Tool

![Build Status](https://img.shields.io/github/actions/workflow/status/droltr/Network_Test_Tool/build.yml?branch=master)
![License](https://img.shields.io/github/license/droltr/Network_Test_Tool)
![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)
![Release](https://img.shields.io/github/v/release/droltr/Network_Test_Tool)

**Version:** 0.9.1
**GitHub:** [https://github.com/droltr/Network_Test_Tool](https://github.com/droltr/Network_Test_Tool)

A modern, comprehensive network diagnostic and troubleshooting utility built with Python and PyQt5.

## 📥 Download

**[Download Latest Release (Windows, Linux & macOS)](https://github.com/droltr/Network_Test_Tool/releases/latest)**

No installation required. Just download and run.

### Run without installing

Windows (PowerShell 5.1 or 7):
```powershell
irm https://droltr.github.io/Network_Test_Tool/run.ps1 | iex
```

Linux x86_64 / macOS Apple silicon:
```bash
curl -fsSL https://droltr.github.io/Network_Test_Tool/run.sh | sh
```

The command downloads the latest release into a per-user cache (`%LOCALAPPDATA%\NetworkTestTool\bin` or `~/.cache/network-test-tool/bin`), checks its SHA-256 against the release's `SHA256SUMS.txt`, and starts it. It needs no administrator rights and changes nothing else on the system. Read [run.ps1](site/run.ps1) or [run.sh](site/run.sh) first if you like. Optional environment variables: `NTT_VERSION=v0.9.1` pins a release, `NTT_NO_LAUNCH=1` only downloads and verifies, and `NTT_SKIP_HASH=1` runs a release that has no `SHA256SUMS.txt` without verification (not recommended). Company security policies may block `irm | iex`; use the download link above instead.

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
*   **Game connection (Counter-Strike 2):** Finds the Valve server the game is connected to (Windows, passive capture with administrator permission), scans Valve locations, and diagnoses the path hop by hop to show whether packet loss starts at home, at the internet provider, on the way to Valve or at Valve. Never touches the game process, its files or its traffic.
*   **Office apps (Microsoft 365, Teams, Zoom):** A quick check and a meeting recorder measure the Wi-Fi link, the router, the internet and every Microsoft 365, Teams and Zoom address, then say whether the problem is the Wi-Fi, the local network, the internet provider, the company network (VPN, proxy) or the service, with an estimated Teams call quality.
*   **Reporting:** Generate text, JSON and CSV reports, plus self-contained HTML reports for game diagnoses, Office apps checks and Network health recording sessions.
*   **Troubleshooter:** Automated network diagnostics to identify common connectivity issues.
*   **Modern UI:** Clean interface with light and dark themes that follow the system setting, designed for ease of use.

## 📚 Documentation

Full documentation is available in the [docs/](docs/) directory:

*   [Home](docs/Home.md)
*   [Installation & Setup](docs/Installation.md)
*   [User Guide: Network Status](docs/User-Guide-Network-Status.md)
*   [User Guide: Diagnostic Tools](docs/User-Guide-Diagnostic-Tools.md)
*   [User Guide: Network Health](docs/User-Guide-Network-Health.md)
*   [User Guide: Game Connection](docs/User-Guide-Game-Connection.md)
*   [User Guide: Office Apps](docs/User-Guide-Office-Apps.md)
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

## Security issues

Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## Third-Party Components

This project bundles [speedtest-cli](https://github.com/sivel/speedtest-cli) by Matt Martz
(Apache 2.0, unmodified, in `utils/speedtest.py`), the IBM Plex Sans, JetBrains Mono and Jost
fonts (SIL OFL 1.1) and a snapshot of the [public iPerf3 server list](https://github.com/R0GGER/public-iperf3-servers)
by R0GGER (MIT). The iPerf3 feature is an independent implementation of the iperf3 protocol
(no ESnet code included). It depends on PyQt5 (GPL v3) and psutil (BSD-3-Clause). See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the `licenses/` folder.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
