# iPerf3 client and server

iPerf3 measures the maximum throughput between two computers. Unlike a speed test, you
choose both ends: a public server on the internet, another computer in your home or
office, or this computer acting as the server.

The app contains its own iperf3-compatible client and server (TCP), so you do not need
to install iperf3. It works with the official `iperf3` program on the other side.

## Client

1. **Pick a server.** The list shows public iperf3 servers by location, provider and link
   speed (Gb/s). Filter by text or region, or type your own server under **Server**.
   **Refresh list** downloads the current list.
2. **Port.** One port (`5201`) or a range (`5201-5209`). Public servers allow one test at
   a time; when a port is busy the app moves to the next one in the range by itself.
3. **Direction.**
   - **Download**: the server sends to you (`iperf3 -R`).
   - **Upload**: you send to the server.
   - **Both**: download first, then upload.
4. **Streams.** Parallel TCP connections. 4 or more fill fast lines (1 Gbps and up) better.
5. **Duration.** 5–60 seconds per direction.
6. Press **Run test**. The gauge and chart show Mbps per second; the result cards show the
   **receiver** rate (what actually arrived), the sender rate, the amount of data and, when
   the server reports them, TCP retransmits.

Under the settings, **Same test in a terminal** shows the matching `iperf3` command;
**Copy command** copies it.

Tips:

- Pick a server close to you and at least as fast as your line.
- Results far below your line speed on several servers point to your own line or Wi-Fi;
  results that differ a lot between servers point to the route to those servers.

## Server

The **Server** tab turns this computer into an iperf3 server so you can test between two
devices on your own network (for example a laptop on Wi-Fi and this PC on cable).

1. Choose the TCP port (default 5201) and press **Start server**.
2. On the other device run one of the commands shown under **Connect from another device**:
   - `iperf3 -c <this PC's IP>`: the other device uploads to this one;
   - `iperf3 -c <this PC's IP> -R`: this computer sends.
3. Each finished test appears in the sessions table with its rate.

If nothing connects, open the port in the firewall (for example
`sudo firewall-cmd --add-port=5201/tcp`).

Supported: TCP, upload and download (`-R`), parallel streams (`-P`), duration (`-t`).
Not supported yet: UDP (`-u`), bidirectional (`--bidir`) and authentication; a client that
asks for them gets a "not implemented" error.
