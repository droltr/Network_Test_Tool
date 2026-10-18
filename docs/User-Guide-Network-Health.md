# Network health

## Health scan

Looks for configuration problems that ping tests miss. It takes 5–15 seconds and changes
nothing. Each check shows **OK**, **Info**, **Check** (worth a look) or **Problem**, the
evidence, and a fix.

| Check | What it finds |
|---|---|
| Routing table | No default route; routes that point to an adapter that is down; `0.0.0.0/1` + `128.0.0.0/1` routes or extra routing rules left by a VPN. |
| DNS servers | Sends a real DNS query to every configured server and reports the ones that do not answer (a common VPN leftover that causes multi-second stalls). |
| VPN and virtual adapters | VPN adapters (tun, tap, WireGuard, Wintun…) and VPN profiles that are present but not connected. |
| Proxy settings | System or environment proxies; an unreachable proxy breaks web traffic while ping still works. |
| Packet size (MTU) | Large packets dropped silently (MTU black hole). A correctly reported path MTU such as 1492 (normal on PPPoE) is shown as Info. |
| IPv6 connectivity | An IPv6 route without working IPv6, which makes connections wait before falling back to IPv4. |
| resolv.conf (Linux) | A `/etc/resolv.conf` written by a VPN tool instead of the system resolver. |
| Winsock catalog (Windows) | Non-Windows network providers registered by VPN or security software. |

Checks with a fix offer a **Renew IP** or **Flush DNS** button. Run the scan again afterwards.

Typical case: a VPN was uninstalled, and the internet now drops for a few seconds every
now and then, and a DNS flush or IP renew helps for a while. The scan shows the leftover
route, DNS server or adapter that causes it.

## Connection monitor

Watches the connection continuously and records every outage.

- **Probe every** 1–10 seconds: the gateway (ping), the DNS server (a real DNS query) and
  the internet (ping to 1.1.1.1 or 8.8.8.8). An **Extra host** (for example a game or work
  server) can be added.
- **Outage after** 1–3 failed probes in a row. Single lost probes count as loss, not as an
  outage.
- Every outage is classified by layer:
  - **Local network**: the gateway did not answer (cable, Wi-Fi, adapter or router);
  - **Internet provider**: the gateway answered but the internet did not;
  - **DNS**: the internet answered but name lookups failed.
- Adapter state, IP address and default gateway changes are recorded as events.
- The availability chart shows the last 600 probes per target (green answered, red not).
- Everything is written to CSV files in the log folder
  (`connection-monitor-<date>-<time>.csv` and `…-events.csv`).

The monitor keeps running when you switch pages.

## Recording sessions

To get a report for a specific time, for example during a video call:

1. Optionally type a label, then press **Start recording**. If the monitor is not running,
   it starts and stops again with the session.
2. Press **Stop recording** when you are done.
3. The report opens: duration; per target the loss, min / average / p95 / max latency and
   jitter; every outage with start, end, duration and layer; adapter changes; and a
   verdict (stable, packet loss, latency spikes or unstable).

The report is saved as `monitor-session-<date>-<time>.md` with the samples in a `.csv`
next to it. Past sessions are listed in the **Sessions** table and under Recent tests on
the Dashboard. If you close the app during a recording, what was recorded so far is saved.
