# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.0] - 2026-11-14

### Added
- **Office apps page:** finds where Microsoft 365, Teams and Zoom problems come from. A 30-second quick check and a meeting recording measure the Wi-Fi link, the router, the internet, name lookups and every Microsoft 365, Teams and Zoom address, then name the layer with the problem (Wi-Fi, local network, internet provider, company network, the service or this computer) with a fix. The recording logs Wi-Fi roams, disconnects, outages and service failures with their times and links loss to Wi-Fi events. Teams call quality is estimated as a MOS value from the media relay. It also notes whether Microsoft's "Optimize" traffic goes through a VPN or proxy. Zoom checks that cannot be verified are shown as untested, never as failed.
- **Wi-Fi information:** network name, access point, signal in dBm, band, channel, link rates, nearby networks and channel congestion, read-only (Windows Native Wifi API, `nmcli`/`iw` on Linux, `system_profiler` on macOS). Windows 11 24H2 and later hide these without the Location permission; the page says so and opens the setting. The Linux and macOS readers are tested against sample output only.
- **Office HTML report:** quick checks and recordings are saved as a self-contained HTML report (offline, light and dark, printable) plus Markdown and JSON, with findings, a timeline, loss strips, service checks and a list of what was and was not verified. Public IPs, MAC addresses and the computer name are masked in the HTML and Markdown files. Recordings also write CSV logs under the app's state folder.
- **Run without installing:** `irm https://droltr.github.io/Network_Test_Tool/run.ps1 | iex` (Windows) and `curl -fsSL https://droltr.github.io/Network_Test_Tool/run.sh | sh` (Linux, macOS) download the latest release, verify its SHA-256 and start it. Releases now include `SHA256SUMS.txt` and stable-named binaries.

### Fixed
- **Office apps page:** it no longer blames the router or Wi-Fi when the router simply does not answer ping while traffic beyond it gets through.
- **Office apps recording:** after a change of the default gateway, replies from the old router could be counted for the new one and show a false router outage or loss finding. This is fixed.
