# Office apps

Finds where problems with **Microsoft 365, Teams and Zoom** come from: your Wi-Fi, the local
network and router, your internet provider, the company network (VPN, proxy, firewall) or the
service itself. Nothing on your computer is changed; the page only measures.

The page has two actions: a **quick check** for "something is wrong now" and a **meeting
recording** for problems that come and go.

## Organization domain (optional)

Your company's Microsoft 365 name, for example `contoso` or `contoso.sharepoint.com`. It adds
your SharePoint site (`<name>.sharepoint.com`) and OneDrive (`<name>-my.sharepoint.com`) to the
checks. Without it those two checks are not run, and the HTML report lists them as not tested. The
name is saved on this computer only. An invalid name is refused before anything starts.

Under the field the page shows the connection: `Connection: Wi-Fi · Wi-Fi is checked too`, or
`Connection: Ethernet (cable)`. On a cable the Wi-Fi card gets the badge **Not used** and the note
"This computer is on a network cable, so Wi-Fi is not part of the path."

## Quick check

About 10 seconds. **Run quick check** measures:

- the Wi-Fi link (signal, band, channel, link rate, how crowded the channel is);
- 20 pings, one every 0.5 seconds, to your router and to the internet (1.1.1.1, or 8.8.8.8
  when 1.1.1.1 does not answer);
- a name lookup of `login.microsoftonline.com`, through your system and against your DNS server;
- the Network health scan checks (adapters, routes, DNS, proxy and so on, see
  [Network health](User-Guide-Network-Health.md));
- every Microsoft 365, Teams and Zoom address once (see the table below);
- 20 STUN probes to the Teams media relay, the way Teams checks its call path.

**Stop** ends it early; the results are then marked partial.

## Record a meeting

Start before a call and stop after it. A label (for example "weekly team call") is optional.
Click **Start recording**; the button then reads **Stop recording**. Once per second the page
pings your router and the internet, sends one STUN probe to the Teams media relay and reads the
Wi-Fi status. Every 60 seconds it repeats the service checks.

While it runs, the live view shows five figures: **Wi-Fi signal**, **Router**, **Internet** (the
latency and loss of each target), **Call relays** and **Outages**. An **outage** is two or more
lost probes in a row. The **Events** table lists each event with its time, what happened and the
layer: roams between access points, disconnects, signal drops, link-rate drops, outages, service
failures and recoveries (for example the signal recovering or a reconnect).

The timeline and the loss-over-time strips (one per target) are not on the page. They are in the
HTML report, which **Open report** saves and opens. After you stop, the page shows the verdict,
the cards, the **What happened at the same time** card (outages and loss that lined up with a
Wi-Fi event or a weak signal, within 5 seconds) and the findings. The report covers at most the
last 8 hours; older samples stay in the CSV log only. While a recording runs, the quick check and
the organization field are locked, so only one measurement runs at a time.

If you close the app while recording, the recording is stopped and its report files are saved
for you.

## What is probed

| Check | What it does |
|---|---|
| DNS | One name lookup. |
| TCP | One connection attempt to the port. |
| TLS | One secure handshake; no request is sent. |
| HTTPS | One GET of a public page through your system proxy. The answer body is not read, and nothing is signed in. |
| STUN (UDP) | One 20-byte STUN Binding Request, the standard way to test a call path. |

| Service | Hosts |
|---|---|
| Microsoft 365 | `login.microsoftonline.com`, `outlook.office365.com`, `microsoft.sharepoint.com`, `oneclient.sfx.ms`, `www.microsoft365.com`; with an organization domain also `<name>.sharepoint.com` and `<name>-my.sharepoint.com` |
| Teams | `teams.microsoft.com`, `teams.cloud.microsoft`, `worldaz.tr.teams.microsoft.com` (media relay, UDP 3478 and TCP 443) |
| Zoom | `zoom.us` (name, HTTPS, TLS, and TCP/UDP 8801) |

The list is a data file (`assets/data/office_services.json`) that names a Microsoft or Zoom
source for every check.

## Wi-Fi information

On Windows the app reads the network name (SSID), access point (BSSID), signal in dBm, band,
channel, link rates and the access points that are nearby from what Windows already knows. It
never connects, disconnects or starts a scan. On Linux it uses `nmcli` or `iw`, on macOS
`system_profiler`.

The signal (dBm) is a **Check** at -70 or lower and a **Problem** at -80 or lower. The link rate
(the slower of receive and transmit) is a **Check** below 24 Mbps and a **Problem** at 6.5 Mbps or
lower. Three or more roams are a **Check**. Disconnects are a **Check** for one or two and a
**Problem** from three.

### Windows Location permission

Windows 11 24H2 and later hide the network name, access point, link rate and nearby networks from
desktop apps while location access is off. The page then shows a notice and the Wi-Fi card says
**Details blocked**. Turn on *Settings > Privacy & security > Location > Let desktop apps access
your location* (the notice has an **Open location settings** button) and run the check again.
Until then roaming and channel congestion cannot be checked.

## VPN and proxy detection

For the Microsoft addresses Microsoft calls "Optimize" (Exchange, SharePoint, the Teams media
relay), the page asks the system which network adapter would carry the traffic and whether it
looks like a VPN tunnel. It also reads the proxy settings and notes whether the HTTPS checks
went through a proxy (proxy addresses are shown without user names or passwords). Microsoft
recommends that these addresses bypass VPNs and proxies, so Optimize traffic through either is
reported as a company network finding.

## Reading the result

The banner at the top names the layer where the problem is, with a short explanation:

| Layer | What it covers |
|---|---|
| Wi-Fi | Weak signal, slow link, roaming, disconnects, a crowded channel. |
| Local network / router | Loss or delay between this computer and the router, or slow or failing name lookups when the DNS server is on your local network. |
| Internet provider | Loss or delay beyond the router, or slow or failing name lookups through a public DNS server. |
| Company network (VPN, proxy, firewall) | Optimize traffic through a VPN or proxy, blocked UDP for calls, proxy settings. |
| Service (Microsoft 365, Teams, Zoom) | A Microsoft 365, Teams or Zoom address that fails while the rest of the path is fine. |
| This computer | Findings from the Network health scan (adapters, routes, DNS settings). |
| No problem found / Inconclusive | Everything measured was fine, or too little could be measured to say. |

The layer names are the labels above. The headline starts with **Problem:** when the layer has a
measured problem, or **Probably:** when every finding in that layer is a best guess. The
headlines **No problem found** and **Inconclusive** have no prefix.

Below the banner:

- **Cards** for Wi-Fi, Local network, Internet and each service, with a status light and the
  key numbers. Check rows show the time, `failed`, or `untested`.
- **Findings**, grouped by layer: what was seen, the evidence and a **Fix**. Each finding has a
  severity badge: **Problem**, **Check** or **Info**. A finding marked **Best guess** also
  names the most likely layer because a measurement upstream of it is missing. Findings that
  passed (badge **OK**) are collected under **Looks fine**.
- **What happened at the same time** (recordings): outages and loss that lined up with Wi-Fi
  events.

For each service with a verified media relay check (Teams today) the page estimates call quality
as a MOS value (Good, Fair, Poor, Bad) from the delay, jitter and loss to the media relay. Zoom has
no verified relay check, so it gets no MOS value. This is an estimate from network numbers only
(a simplified ITU-T G.107 model); the codec, CPU load and audio devices are not included.

When relay probes were sent, the service card gets these extra rows: **Call relay RTT**, **Call
relay jitter**, **Call relay loss** and **Call quality (estimate)** with the label and the MOS
value. If the relay did not answer, the row **Call relay** shows "no answer".

## Reports, logs and copying

- **Open report** saves three files with the same name, `office-quick-<date>-<time>` or
  `office-session-<date>-<time>`, and opens the HTML in your browser. The files are written
  once per result.

  | File | What it is for |
  |---|---|
  | `.html` | The report to read and share. One offline file, no scripts, light and dark mode, printable. |
  | `.md` | The same findings as text. |
  | `.json` | All measurements, for tools and AI assistants. |

  They go to the folder the Network health page uses for its logs (by default
  `Documents/network-test-tool`). The HTML and Markdown reports replace public IP addresses,
  MAC addresses (access point BSSIDs) and the computer name with placeholders such as
  `PUBLIC_IP_1`, `MAC_1` and `HOSTNAME`. The network name (SSID) is kept. The `.json` file is not masked, so
  look at it before you share it.
- **Open log folder** opens the folder of the recording's CSV logs (or the report folder).
- **Copy summary** copies the report as Markdown, for example for a ticket to IT.
- While a recording runs, two CSV files are written row by row to the app's state folder under
  `office-logs`: `office-<date>-<time>.csv` (every sample, including the BSSID) and
  `office-<date>-<time>-events.csv`. On Linux and macOS that folder is
  `~/.local/state/network-test-tool/office-logs/`; on Windows it is
  `%LOCALAPPDATA%\NetworkTestTool\office-logs\`. They are not masked.
- The last result is also included in the package **Ask AI agent** prepares.

## Limits and what is not verified

- **Zoom port 8801 checks are not verifiable.** `zoom.us` accepts TCP connections on any port,
  and no public Zoom host answered a STUN request. These two checks are shown as `untested`,
  never as failed, and Zoom call quality is not measured.
- **Only the Teams media relay is probed for calls.** Real calls may use other relays and ports;
  the probes show the path at the time of the test only.
- **Your own SharePoint and OneDrive are tested only** when you enter an organization domain.
- **Loss to a router that ignores pings** (some do) can look like a local problem. Findings
  with too few probes (under 10) are not drawn from them.
- **Wi-Fi on Linux and macOS** was tested against sample output only, not against real
  adapters. Treat it as best effort and compare with `nmcli dev wifi`, `iw dev <if> link` or
  the Wi-Fi menu.
- **The rules are rules of thumb** for office calls, not standards, apart from the Teams
  targets (delay under 100 ms, loss under 1 %, jitter under 30 ms) that Microsoft publishes.
- Windows hides Wi-Fi details without the Location permission (see above).

## Troubleshooting

- **The Wi-Fi card says "Details blocked".** Turn on the Windows location setting above.
- **Buttons are disabled.** Only one measurement runs at a time; stop the recording or wait for
  the quick check.
- **A check shows `failed` for one address only.** Open the tooltip on the row for the exact
  error. If it says the certificate is not trusted, a proxy or security product probably
  inspects secure connections.
