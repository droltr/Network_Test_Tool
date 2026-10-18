# Installation and setup

## Option 1: download the app

Download the file for your system from the
[Releases page](https://github.com/droltr/Network_Test_Tool/releases) and run it. No
installation is needed.

- **Linux:** make the file executable (`chmod +x NetworkTestTool-*-linux-x86_64`) and run it.
- **Windows:** run `NetworkTestTool-*-windows-x86_64.exe`.
- **macOS:** unzip and open `Network Test Tool.app`.

## Option 2: run from source

Requirements: Python 3.9 or newer.

```bash
git clone https://github.com/droltr/Network_Test_Tool.git
cd Network_Test_Tool
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
.venv/bin/python main.py                         # Windows: .venv\Scripts\python main.py
```

On Linux, `./run.sh` does all of this: it creates `.venv` on the first start and launches
the app.

## Option 3: build a single-file app

PyInstaller builds for the system it runs on; it cannot build a Windows app on Linux or the
other way round. Run the same command on each system:

```bash
pip install -r requirements.txt pyinstaller
python build.py              # add --clean to start from scratch
```

| System | Output in `dist/` |
|---|---|
| Linux | `NetworkTestTool-<version>-linux-x86_64` |
| Windows | `NetworkTestTool-<version>-windows-x86_64.exe` |
| macOS | `Network Test Tool.app` |

Fonts, the iPerf3 server list, the user guide, `THIRD_PARTY_NOTICES.md` and the license
texts are bundled into the app. Pushing a tag such as `v0.7.0` runs the GitHub Actions
workflow, which builds all three and attaches them to a release.

## System tools the app uses

The app calls the tools your system already has. Missing tools only disable the feature
that needs them.

| Feature | Linux | Windows | macOS |
|---|---|---|---|
| Ping, latency | `ping` | `ping` | `ping` |
| Trace route | `traceroute` | `tracert` | `traceroute` |
| Gateway, DNS servers | `/proc/net/route`, `resolvectl` | `ipconfig` | `/etc/resolv.conf`; the gateway needs the optional `netifaces` package |
| ARP table | `ip neigh` | `arp -a` | `arp -an` |
| Renew / Release IP | NetworkManager (`nmcli`) or `dhclient` | `ipconfig` | `ipconfig set` |
| Flush DNS | `resolvectl flush-caches` | `ipconfig /flushdns` | `killall -HUP mDNSResponder` |
| NetBIOS lookup | `nmblookup` (package `samba-client`) | `nbtstat` | `nmblookup` |

iPerf3 and the speed test are built in; you do not need to install `iperf3` or
`speedtest-cli`.

### Permissions

- **Linux:** Renew IP, Release IP and Flush DNS may show a polkit password dialog.
- **Windows:** these actions need an administrator account; run the app as administrator
  if they fail.
- **iPerf3 server:** other devices can only connect if the port (default 5201) is open in
  the firewall, for example `sudo firewall-cmd --add-port=5201/tcp` on Fedora.

## Where the app keeps its files

| What | Linux | Windows |
|---|---|---|
| Settings and recent results | `~/.config/NetworkTools/` | Registry: `HKCU\Software\NetworkTools` |
| Debug and crash logs | `~/.local/state/network-test-tool/` | `%LOCALAPPDATA%\NetworkTestTool\` |
| Monitor logs, session reports, AI packages | `~/Documents/network-test-tool/` (changeable) | `Documents\network-test-tool\` |
