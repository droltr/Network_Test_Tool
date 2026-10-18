# Third-Party Notices

Network Test Tool is licensed under the MIT License (see `LICENSE`). It includes or
depends on the third-party components below. Each keeps its own license; the full
license texts are in `licenses/`.

## Bundled in this repository

### speedtest-cli

- File: `utils/speedtest.py` (version 2.1.4b1)
- Source: https://github.com/sivel/speedtest-cli (copied from the `master` branch,
  unmodified)
- Copyright 2012 Matt Martz
- License: Apache License 2.0 — `licenses/speedtest-cli-apache-2.0.txt`
- Used by `network/speed_test.py` to run the download, upload and ping test against
  speedtest.net servers.

### IBM Plex Sans

- Files: `assets/fonts/IBMPlexSans-*.ttf`
- Source: https://github.com/IBM/plex
- Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"
- License: SIL Open Font License 1.1 — `licenses/ibm-plex-ofl-1.1.txt`

### JetBrains Mono

- Files: `assets/fonts/JetBrainsMono-*.ttf`
- Source: https://github.com/JetBrains/JetBrainsMono
- Copyright 2020 The JetBrains Mono Project Authors
- License: SIL Open Font License 1.1 — `licenses/jetbrains-mono-ofl-1.1.txt`

### Jost

- Files: `assets/fonts/Jost-400-Book.ttf`, `Jost-500-Medium.ttf`, `Jost-600-Semi.ttf`,
  `Jost-700-Bold.ttf` (UI font of the Bauhaus themes; font family name "Jost*")
- Source: https://github.com/indestructible-type/Jost
- Copyright 2020 The Jost Project Authors
- License: SIL Open Font License 1.1 — `licenses/jost-ofl-1.1.txt`

### Public iPerf3 server list

- File: `assets/data/iperf3-servers.json` (snapshot of 2026-10-10, normalized to this app's
  field names); the in-app "Refresh list" downloads the current export.
- Source: "Public iPerf3 Serverlist" by R0GGER — https://github.com/R0GGER/public-iperf3-servers,
  export https://export.iperf3serverlist.net/listed_iperf3_servers.json
- Copyright (c) 2022 R0GGER
- License: MIT — `licenses/public-iperf3-servers-mit.txt`

> **⚠️ ASSUMPTION:** the JSON export is covered by the repository's MIT license.
> Based on: the repository README links to the export as part of the project. To verify:
> ask the maintainer or find a license statement on iperf3serverlist.net.

## Protocol compatibility (no code included)

### iperf3

- `network/iperf.py` is an independent Python implementation of the iperf3 control
  protocol (TCP). It was written by reading ESnet's iperf3 source
  (https://github.com/esnet/iperf, BSD-3-Clause, `src/iperf_api.c`, `iperf_client_api.c`,
  `iperf_server_api.c`, `iperf_tcp.c`); no iperf3 code is copied. "iperf" is credited to
  ESnet / The Regents of the University of California.

## Installed as dependencies (not bundled in the source tree)

| Package | License | Source |
|---|---|---|
| PyQt5 | GPL v3 (or a commercial Riverbank license) | https://www.riverbankcomputing.com/software/pyqt/ |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |

Note: binaries built with PyInstaller include PyQt5. Distributing such a binary means
following the GPL v3 terms for that binary (or holding a commercial PyQt license).
