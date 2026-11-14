# Diagnostic tools

## Diagnose host

Checks one address or name with **ping** (20 replies) and **trace route** (up to 15 hops)
at the same time.

1. Type a host name or IP address (for example `8.8.8.8` or `example.com`) and press
   **Run**. Untick **Ping** or **Trace** to run only one of them.
2. While it runs, the latency chart fills in reply by reply and the route grows hop by hop.
   **Stop** ends both.
3. Results: sent / received / lost, min / avg / max latency, number of hops and hops that
   did not reply.

Reading the results:

- **Lost replies** (yellow) mean packet loss on the way to that host.
- A hop marked **timeout** followed by hops that answer is usually harmless: many routers
  do not answer trace probes. The note under the route says so when it happens.
- If the name cannot be resolved, the app checks your gateway and DNS server and offers
  **Flush DNS and retry**, **Run troubleshooter** or **Try 8.8.8.8 instead**.

**Export** saves the replies and the route as a text file.

## Port scanner

Checks which TCP ports accept connections on a host.

- Pick a preset (Common, Web, FTP, Mail, Database, Remote, All common 1–1024) or
  **Custom range**, and a timeout per port.
- Up to 64 ports are shown as tiles; larger scans as a port map (green = open).
- The table lists open ports with their usual service name; **Copy** copies `host:port`.

Only scan systems you own or are allowed to test.

## Speed test

Measures download, upload and ping to the nearest speedtest.net server.

- **Start speed test** runs the full test: server selection, ping, download, upload. The
  gauge and the throughput chart update live; **Stop** cancels.
- **Latency test** sends 10 pings to 8.8.8.8 and charts them live.
- After a test, **Run speed test again** / **Run latency test again** repeat the same test.

The live chart shows the traffic of your network interface (sampled every 0.5 s), so short
peaks can be higher than the final result, which is speedtest.net's own measurement. For
the most accurate throughput between two points, use [iPerf3](User-Guide-iPerf3.md).

## Advanced

- **ARP table:** devices this computer has talked to on the local network (IP, MAC,
  dynamic or static, interface). **Ping** opens Diagnose host for that address.
- **Connections:** open network connections with process, PID, protocol, local and remote
  address and state. Filter by text or by All / Established / Listening.
- **NetBIOS:** looks up the Windows name table of an IP address (needs `nmblookup` on Linux).

## Troubleshooter

Runs a fixed sequence in about 30 seconds: device and network information, ping to the
gateway, the primary DNS server and 8.8.8.8, and a trace route to 1.1.1.1. The checklist
shows each step's result; the log shows the raw output; **Suggestions** explain failed
steps with a button for the matching fix. **Export log** saves the log.
