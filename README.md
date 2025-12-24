# Network Test Tool

![Build Status](https://img.shields.io/github/actions/workflow/status/droltr/Network_Test_Tool/build.yml?branch=master)
![License](https://img.shields.io/github/license/droltr/Network_Test_Tool)
![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)
![Release](https://img.shields.io/github/v/release/droltr/Network_Test_Tool)

**Version:** 0.6.2 (Stable)
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
*   **Speed Test:** Integrated internet speed test (Download, Upload, Ping).
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

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Usage

Run the application:
```bash
python main.py
```

## Requirements

*   Python 3.8+
*   PyQt5
*   psutil
*   speedtest-cli

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct, and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
