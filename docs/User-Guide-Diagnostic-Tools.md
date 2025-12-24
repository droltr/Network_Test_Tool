# User Guide: Diagnostic Tools

## 📡 Ping Test
A graphical ping tool to test connectivity to a specific host.
*   **Target Host**: Enter a domain (e.g., `google.com`) or IP (e.g., `1.1.1.1`).
*   **Count**: Number of ping packets to send.
*   **Results**: Shows Min/Max/Avg latency and packet loss percentage.

## 🔍 Port Scanner
Scans a target IP for open ports.
*   **Presets**: Choose from common presets (Web, Mail, Gaming) or define a custom range.
*   **Multi-threaded**: Scans quickly without freezing the UI.
*   **Export**: Save scan results to a text file.

## 🚀 Speed Test
Measures your internet connection speed.
*   **Full Test**: Measures Download, Upload, and Ping.
*   **Latency Test**: Quickly checks ping to a reliable server without consuming bandwidth.

## 🛣️ Trace Route
Visualizes the path packets take to reach a destination.
*   **Hop-by-Hop**: Lists every router (hop) between you and the target.
*   **Status**:
    *   **OK (Green)**: Router responded quickly.
    *   **Timeout (Red)**: Router did not respond (Packet loss or firewall).
*   **Latency**: Shows the time taken for each hop.

## 🛠️ Advanced Tools
*   **ARP Table**: Lists all devices discovered on your local network (IP and MAC addresses).
*   **Active Connections**: Shows all apps currently connected to the network/internet.
*   **NetBIOS Lookup**: Query a local IP to find its computer name (Windows only).

## 🤖 Troubleshooter
An automated script that runs a sequence of tests:
1.  Checks Network Adapter status.
2.  Pings the Default Gateway.
3.  Pings DNS Servers.
4.  Pings an External Host (8.8.8.8).
5.  Runs a Trace Route to 1.1.1.1.
6.  **Analysis**: Provides specific suggestions based on failures (e.g., "Check physical cable", "Change DNS").
