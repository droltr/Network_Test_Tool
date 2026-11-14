# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.9.1] - 2026-11-14

### Added
- **Follow system theme:** View > Theme now offers Follow system, One Dark, Bauhaus light and Bauhaus dark. A chosen theme is remembered and is used instead of the system setting. The Linux and macOS system-setting readers are tested against sample output only.
- **Theme switch without restart:** a theme change applies at once. If a test or recording is running, the app asks first because switching stops it.

### Changed
- **Office apps:** the checks use Microsoft's current Microsoft 365 address list (downloaded from endpoints.office.com at most once a day, cached, with the built-in list as fallback) to decide which addresses count as Optimize for the VPN and proxy findings; the reports show where the list came from.
- **First start follows the system:** the app starts with the operating system's light or dark setting (Bauhaus light or Bauhaus dark), and with Bauhaus dark if the setting cannot be read. Before, it always started with Bauhaus light.
- **Quick check duration:** the Office apps page and its help now say "About 10 to 30 seconds (longer when the router does not answer ping)" instead of "About 10 seconds".

### Fixed
- **Dashboard startup:** malformed saved recent-test entries without a `kind` no longer prevent the app from opening.
- **Office recordings:** gateway changes could leave measurements labelled with the old router for up to 30 seconds. This delay is fixed.
- **Office verdicts:** brief loss and service failures while connecting or disconnecting a VPN could wrongly blame the internet provider or service. This is fixed.
- **Office exit:** a hung recording probe could stall closing the app, and failed exit saves went unreported. Both problems are fixed.
- **Office apps page:** when the router does not answer ping but the path beyond it is fine, the router card looked like a failure or said the router was "not measured". It now shows "No ping reply" as information, and findings of severity information are labelled "information".
- **Office reports:** a change of the default gateway during a recording was not visible. The card shows the gateways seen, the HTML report has a "Default gateway" fact and the Markdown report a "Gateway note".
- **Bauhaus dark:** section titles and secondary text are easier to read.

## [0.9.0] - 2026-11-14

### Added
- **Office apps page:** finds where Microsoft 365, Teams and Zoom problems come from. A 30-second quick check and a meeting recording measure the Wi-Fi link, the router, the internet, name lookups and every Microsoft 365, Teams and Zoom address, then name the layer with the problem (Wi-Fi, local network, internet provider, company network, the service or this computer) with a fix. The recording logs Wi-Fi roams, disconnects, outages and service failures with their times and links loss to Wi-Fi events. Teams call quality is estimated as a MOS value from the media relay. It also notes whether Microsoft's "Optimize" traffic goes through a VPN or proxy. Zoom checks that cannot be verified are shown as untested, never as failed.
- **Wi-Fi information:** network name, access point, signal in dBm, band, channel, link rates, nearby networks and channel congestion, read-only (Windows Native Wifi API, `nmcli`/`iw` on Linux, `system_profiler` on macOS). Windows 11 24H2 and later hide these without the Location permission; the page says so and opens the setting. The Linux and macOS readers are tested against sample output only.
- **Office HTML report:** quick checks and recordings are saved as a self-contained HTML report (offline, light and dark, printable) plus Markdown and JSON, with findings, a timeline, loss strips, service checks and a list of what was and was not verified. Public IPs, MAC addresses and the computer name are masked in the HTML and Markdown files. Recordings also write CSV logs under the app's state folder.
- **Run without installing:** `irm https://droltr.github.io/Network_Test_Tool/run.ps1 | iex` (Windows) and `curl -fsSL https://droltr.github.io/Network_Test_Tool/run.sh | sh` (Linux, macOS) download the latest release, verify its SHA-256 and start it. Releases now include `SHA256SUMS.txt` and stable-named binaries.

### Fixed
- **Office apps page:** it no longer blames the router or Wi-Fi when the router simply does not answer ping while traffic beyond it gets through.
- **Office apps recording:** after a change of the default gateway, replies from the old router could be counted for the new one and show a false router outage or loss finding. This is fixed.
