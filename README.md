# Network Test Tools

A comprehensive network diagnostic tool built with PyQt5 for Windows. Provides network status monitoring, ping testing, port scanning, and speed testing capabilities.

![Platform](https://img.shields.io/badge/platform-Windows-blue.svg)
![Python](https://img.shields.io/badge/python-3.x-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Features

- **Network Status Monitoring** - Real-time network adapter status, connection details, and automatic refresh
- **Ping Testing** - Test network connectivity with customizable ping count and target history
- **Port Scanner** - Scan target hosts for open ports with export functionality
- **Speed Testing** - Full speed tests (download/upload/ping) and latency-only tests
- **Automated Troubleshooting** - Comprehensive network diagnostics with log export
- **Network Adapter Management** - Enable/disable network adapters (requires admin privileges)

## Prerequisites

- Windows 10/11
- Python 3.x
- Administrator privileges (for adapter management features)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/droltr/network_tools_Worked.git
cd network_tools_Worked
```

2. Create a virtual environment (recommended):
```bash
python -m venv .venv
.venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install PyQt5
```

## Usage

Run the application:
```bash
python main.py
```

For adapter management features, run as administrator:
```bash
# Right-click on Command Prompt -> Run as Administrator
python main.py
```

## Features Overview

### Network Status
- Display hostname, IP address, gateway, DNS servers, and MAC address
- List all network adapters with enable/disable controls
- Auto-refresh capability
- Connection status monitoring

### Ping Test
- Test connectivity to any host
- Configurable ping count
- TTL information display
- Target history tracking

### Port Scanner
- Scan ports on target hosts
- Export scan results to text file
- Target history tracking

### Speed Test
- Full speed test (download/upload/ping)
- Latency-only test option
- Export results to text file

### Automated Troubleshooting
- Comprehensive network diagnostics
- Integrated speed testing
- Detailed logging with export capability

## Technical Stack

- **GUI Framework**: PyQt5
- **Language**: Python 3.x
- **Platform**: Windows

## Project Structure

```
network_tools_Worked/
├── main.py              # Application entry point
├── gui/                 # GUI components
├── network/             # Network operations
├── utils/               # Utility functions
└── test_plan.md         # Testing documentation
```

## Contributing

Contributions are welcome. Please submit issues or pull requests.

## License

MIT License - see LICENSE file for details.

## Links

- [GitHub Repository](https://github.com/droltr/network_tools_Worked)
- [Report Issues](https://github.com/droltr/network_tools_Worked/issues)
