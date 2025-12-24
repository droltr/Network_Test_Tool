import subprocess
import platform
import logging

class SystemTools:
    def __init__(self):
        self.platform = platform.system().lower()

    def _run_command(self, command):
        """Execute a system command and return the output."""
        try:
            # Windows commands often need shell=True
            use_shell = self.platform == "windows"
            result = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                shell=use_shell,
                encoding='cp850' if self.platform == "windows" else 'utf-8'
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            logging.error(f"Command execution failed: {e}")
            return False, str(e)

    def renew_ip(self, adapter_name=None):
        """Renew IP address lease. Optionally for a specific adapter."""
        if self.platform == "windows":
            cmd = ["ipconfig", "/renew"]
            if adapter_name:
                cmd.append(f'"{adapter_name}"')
            # Join command for shell execution to handle quotes properly
            return self._run_command(" ".join(cmd))
        else:
            return self._run_command(["sudo", "dhclient", "-v"])

    def release_ip(self, adapter_name=None):
        """Release IP address lease. Optionally for a specific adapter."""
        if self.platform == "windows":
            cmd = ["ipconfig", "/release"]
            if adapter_name:
                cmd.append(f'"{adapter_name}"')
            return self._run_command(" ".join(cmd))
        else:
            return self._run_command(["sudo", "dhclient", "-r"])

    def flush_dns(self):
        """Flush DNS resolver cache."""
        if self.platform == "windows":
            return self._run_command(["ipconfig", "/flushdns"])
        elif self.platform == "darwin": # macOS
            return self._run_command(["sudo", "killall", "-HUP", "mDNSResponder"])
        else: # Linux (systemd-resolve)
            return self._run_command(["sudo", "systemd-resolve", "--flush-caches"])

    def reset_winsock(self):
        """Reset Winsock catalog (Windows only)."""
        if self.platform == "windows":
            return self._run_command(["netsh", "winsock", "reset"])
        else:
            return False, "This feature is only available on Windows."
