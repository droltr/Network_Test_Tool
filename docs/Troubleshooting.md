# Troubleshooting & FAQ

## Common Issues

### 1. "Renew IP" or "Flush DNS" fails
*   **Cause**: These commands require Administrator privileges on Windows.
*   **Solution**: Right-click the application (or `run.bat`) and select **"Run as Administrator"**.

### 2. Speed Test fails or shows error
*   **Cause**: Firewall blocking the connection or server unavailability.
*   **Solution**: Check your internet connection. Try the "Latency Test" first to see if basic connectivity works.

### 3. Port Scanner is slow
*   **Cause**: Scanning many ports with a high timeout value.
*   **Solution**: Reduce the timeout value (e.g., to 0.5s) or scan fewer ports.

### 4. Application doesn't start
*   **Cause**: Missing dependencies or Python version mismatch.
*   **Solution**: Ensure you have Python 3.8+ installed and run `pip install -r requirements.txt`. If using the executable, try downloading the latest version again.

## FAQ

**Q: Is this tool free?**
A: Yes, it is open-source and free to use under the MIT License.

**Q: Does it work on Mac?**
A: The Python source code should run on macOS, but some features like `ipconfig` commands are Windows-specific. The tool is primarily optimized for Windows and Linux.

**Q: Where are the reports saved?**
A: By default, reports are saved in the same directory as the application, but you can choose any location when saving.
