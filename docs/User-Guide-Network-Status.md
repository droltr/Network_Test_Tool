# User Guide: Network Status

The **Network Status** tab is the main dashboard of the application. It provides an immediate overview of your computer's network health.

## 🖥️ Interface Overview

### 1. Status Indicator
Located in the top-right corner, this round indicator shows your global connectivity state:
*   🟢 **Online**: Connected to the internet (Ping to 8.8.8.8 successful).
*   🟡 **Local Only**: Connected to a gateway but no internet access.
*   🔴 **Offline**: No network connection detected.

### 2. Diagnostics Panel
This panel appears at the top of the window and displays:
*   **System Health**: "✓ System Healthy" if no issues are found.
*   **Warnings/Critical Issues**: Lists detected problems (e.g., "APIPA address detected", "Gateway unreachable") with suggested solutions.

### 3. Quick Actions
Perform common network maintenance tasks with one click:
*   **Adapter Selection**: Choose "All Adapters" or a specific interface from the dropdown.
*   **Renew IP**: Runs `ipconfig /renew`. Useful for DHCP issues.
*   **Flush DNS**: Runs `ipconfig /flushdns`. Useful for website loading errors.
*   **Release IP**: Runs `ipconfig /release`. Disconnects the adapter from the current IP.
*   **Generate Report**: Creates a comprehensive status report.

### 4. Adapter Cards
Each network interface (Wi-Fi, Ethernet, etc.) is displayed as a card.
*   **Sorting**: Active and problematic (APIPA) adapters are always shown at the top.
*   **Information**: Displays Name, Status, IP Address, MAC Address, Gateway, and DNS Servers.
*   **APIPA Warning**: If an adapter has an IP starting with `169.254.x.x`, it is flagged with a yellow "⚠ APIPA" badge.
