# Privacy and security

## What stays on your computer

Settings, recent results, reports, monitor logs and AI packages are stored only on this
computer (see [Reports, exports and log files](Reporting.md)). The app has no account, no
telemetry and no AI service of its own.

## What the app contacts

Only what you test, plus a few fixed addresses for reachability:

| Feature | Contacts |
|---|---|
| Dashboard, Troubleshooter, Connection monitor | your gateway, your DNS servers, 8.8.8.8, 1.1.1.1, google.com (name lookup and a small web request) |
| Diagnose host, Port scanner, Advanced | the host you enter |
| Speed test | speedtest.net (server list and the chosen test server) |
| iPerf3 | the iperf3 server you choose; `export.iperf3serverlist.net` when you press Refresh list |
| Ask AI agent | nothing — you copy or save the package yourself |

## Actions that change your system

Renew IP, Release IP and Flush DNS run system commands (NetworkManager, systemd-resolved,
`ipconfig`). They run only when you press their buttons, ask for confirmation where the
effect is disruptive (Release IP) and go through the system's own password prompt.
Everything else only reads and measures.

## Port scanning and iPerf3 server

- Only scan hosts you own or have permission to test.
- The iPerf3 server listens only while you run it and accepts one test at a time, like the
  official iperf3. Stop it when you are done, and close the firewall port if you opened it.

## Ask AI agent

MAC addresses, public IP addresses and the computer name are masked by default. Check the
preview before you share the package; process names and local addresses stay visible.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md) in the repository.
