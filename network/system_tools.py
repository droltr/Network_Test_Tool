import os
import shutil
import subprocess
import platform
import logging

from utils.paths import command_env, decode_output



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
                shell=use_shell,
                env=command_env(),
                timeout=60
            )
            # Raw bytes: netsh writes UTF-8, ipconfig the OEM code page; decode_output handles both
            return result.returncode == 0, decode_output(result.stdout) + decode_output(result.stderr)
        except Exception as e:
            logging.error(f"Command execution failed: {e}")
            return False, str(e)

    def _privileged(self, command):
        """Prefix a command with pkexec so a GUI session gets a polkit password prompt."""
        if os.geteuid() == 0 or not shutil.which('pkexec'):
            return command
        return ['pkexec'] + command

    # --- NetworkManager helpers (Linux) ---

    def _nm_devices(self, adapter_name=None):
        """Connected NetworkManager devices as (device, connection) pairs."""
        ok, output = self._run_command(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device'])
        if not ok:
            return []
        devices = []
        for line in output.splitlines():
            parts = line.split(':', 3)
            if len(parts) < 4:
                continue
            device, dev_type, state, connection = parts
            if dev_type in ('loopback', 'wifi-p2p', 'bridge', 'tun') or not state.startswith('connected'):
                continue
            if adapter_name and device != adapter_name:
                continue
            devices.append((device, connection.replace('\\:', ':')))
        return devices

    def _nm_for_each(self, adapter_name, make_command):
        devices = self._nm_devices(adapter_name)
        if not devices:
            target = adapter_name or "any adapter"
            return False, f"No connected NetworkManager device found for {target}."
        outputs, all_ok = [], True
        for device, connection in devices:
            ok, out = self._run_command(make_command(device, connection))
            all_ok = all_ok and ok
            outputs.append(f"{device}: {out.strip() or ('done' if ok else 'failed')}")
        return all_ok, "\n".join(outputs)

    def renew_ip(self, adapter_name=None):
        """Renew IP address lease. Optionally for a specific adapter."""
        if self.platform == "windows":
            cmd = ["ipconfig", "/renew"]
            if adapter_name:
                cmd.append(f'"{adapter_name}"')
            # Join command for shell execution to handle quotes properly
            return self._run_command(" ".join(cmd))
        elif self.platform == "darwin":
            iface = adapter_name or "en0"
            return self._run_command(self._privileged(["ipconfig", "set", iface, "DHCP"]))
        elif shutil.which('nmcli'):
            # Re-activating the connection requests a fresh DHCP lease
            return self._nm_for_each(adapter_name, lambda dev, con: ['nmcli', 'connection', 'up', con, 'ifname', dev])
        elif shutil.which('dhclient'):
            cmd = ["dhclient", "-v"] + ([adapter_name] if adapter_name else [])
            return self._run_command(self._privileged(cmd))
        return False, "Neither NetworkManager (nmcli) nor dhclient was found."

    def release_ip(self, adapter_name=None):
        """Release IP address lease. Optionally for a specific adapter."""
        if self.platform == "windows":
            cmd = ["ipconfig", "/release"]
            if adapter_name:
                cmd.append(f'"{adapter_name}"')
            return self._run_command(" ".join(cmd))
        elif self.platform == "darwin":
            iface = adapter_name or "en0"
            return self._run_command(self._privileged(["ipconfig", "set", iface, "NONE"]))
        elif shutil.which('nmcli'):
            return self._nm_for_each(adapter_name, lambda dev, con: ['nmcli', 'device', 'disconnect', dev])
        elif shutil.which('dhclient'):
            cmd = ["dhclient", "-r"] + ([adapter_name] if adapter_name else [])
            return self._run_command(self._privileged(cmd))
        return False, "Neither NetworkManager (nmcli) nor dhclient was found."

    def flush_dns(self):
        """Flush DNS resolver cache."""
        if self.platform == "windows":
            return self._run_command(["ipconfig", "/flushdns"])
        elif self.platform == "darwin": # macOS
            return self._run_command(self._privileged(["killall", "-HUP", "mDNSResponder"]))
        elif shutil.which('resolvectl'): # Linux (systemd-resolved)
            ok, output = self._run_command(["resolvectl", "flush-caches"])
            if not ok and 'access denied' in output.lower():
                ok, output = self._run_command(self._privileged(["resolvectl", "flush-caches"]))
            return ok, output or "DNS cache flushed."
        elif shutil.which('systemd-resolve'):
            return self._run_command(self._privileged(["systemd-resolve", "--flush-caches"]))
        elif shutil.which('nscd'):
            return self._run_command(self._privileged(["nscd", "-i", "hosts"]))
        return False, "No DNS cache service (systemd-resolved or nscd) was found. Nothing to flush."

    def reset_winsock(self):
        """Reset Winsock catalog (Windows only)."""
        if self.platform == "windows":
            return self._run_command(["netsh", "winsock", "reset"])
        else:
            return False, "This feature is only available on Windows."

    def privilege_note(self):
        """Short UI hint about what the quick actions need."""
        if self.platform == "windows":
            return "Requires administrator privileges"
        return "May ask for your password (polkit)"
