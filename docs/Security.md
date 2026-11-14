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
| Office apps | your gateway, 1.1.1.1 (8.8.8.8 if that does not answer), your DNS server, and the Microsoft 365, Teams and Zoom hosts: `login.microsoftonline.com`, `outlook.office365.com`, `microsoft.sharepoint.com`, `oneclient.sfx.ms`, `www.microsoft365.com`, `teams.microsoft.com`, `teams.cloud.microsoft`, `worldaz.tr.teams.microsoft.com` (STUN on UDP 3478 and TCP 443) and `zoom.us` (ports 443, 8801); with an organization domain also `<name>.sharepoint.com` and `<name>-my.sharepoint.com` |
| Office apps, Microsoft's address list | `endpoints.office.com`, at most once a day (see [Office apps](#office-apps)) |
| Ask AI agent | nothing — you copy or save the package yourself |

## Office apps

The checks are one name lookup, one connection, one handshake, one page request (through your
system proxy, no sign-in, no cookies, response body not read) or one 20-byte STUN request per
address; a recording sends at most one probe per second per target and repeats the service
checks every 60 seconds. Your organization domain is only used to form the two SharePoint host
names and is saved on this computer. The Wi-Fi information is read from Windows, `nmcli`/`iw` or
`system_profiler`; the app never connects, disconnects or scans. Report files go to the report
folder; a recording also writes CSV logs to `office-logs` in the app's state folder (see
[Reports, exports and log files](Reporting.md)). The HTML and Markdown reports mask public IPs,
MAC addresses and the computer name; the JSON file and the CSV logs do not.

To know which Microsoft 365 addresses Microsoft currently marks as "Optimize", the Office apps page
downloads Microsoft's public endpoint list once per quick test or recording, and at most once a day:
a single HTTPS GET to `https://endpoints.office.com/endpoints/worldwide?clientrequestid=<GUID>`
with the header `User-Agent: network-test-tool`, a 5-second time limit and no cookies, no body and
no sign-in. The GUID is random, is created once on this computer (file `m365-client-request-id.txt`
in the app's state folder) and is the request id Microsoft's web service asks for; it is not
derived from your name, computer, network or organization, and the organization domain is not
sent. The answer is cached in the state folder (`m365-endpoints.json`). The page works without
it: when the download fails, the last cached copy or the list bundled with the app is used and the
report says which one was used.

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

See [SECURITY.md](../SECURITY.md).
