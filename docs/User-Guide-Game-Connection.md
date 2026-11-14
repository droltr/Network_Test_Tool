# Game connection

Finds the Counter-Strike 2 server you are playing on and shows **where** on the way to it
lag, rubber-banding or packet loss comes from: your home network, your internet provider,
the networks between your provider and Valve, or Valve's own server network.

The page has three steps. Step 1 or step 2 picks the server; step 3 measures the path to it.

## Safe with Valve Anti-Cheat

The page is built so that it cannot look like a cheat:

- It reads only Windows network tables (which program owns which network port, the same
  list `netstat` shows) and the headers of packets passing the network card, passively.
- It never opens, reads or changes the game process, its memory, its files, its console or
  its logs, and never writes into the Steam or Counter-Strike 2 folders.
- It draws nothing over the game, uses no hotkeys or keyboard hooks and takes no screenshots.
- It never blocks, delays or reroutes game traffic. Its own probes are ordinary pings and a
  traceroute, sent next to the game traffic.

## 1. Your game

The card shows whether Counter-Strike 2 is running. It is checked when you open the page;
**Refresh** checks again.

**Detect server** works while you are in a match:

1. Windows asks for administrator permission (a UAC prompt). Reading packet headers needs
   it; Windows does not let normal programs watch network traffic. If you decline, nothing
   happens and the page tells you so.
2. For 10 seconds the app watches the packets that arrive on the game's network ports and
   picks the address that sends the most of them: that is the match server.
3. It shows the server address and port, the Valve location it belongs to (for example
   *Vienna (Austria)*), and how steady the game stream is:

| Value | Meaning |
|---|---|
| Inbound / s | Update bursts per second that arrived from the server. |
| Expected / s | What the server sends when everything is fine (64 for Counter-Strike 2). |
| Max gap | The longest pause between two updates. Above 40 ms you can feel it. |
| Gaps > 40 ms | How many such pauses happened in the 10 seconds. |

The tag next to the address sums this up: **Smooth**, **Hiccups** (a few late updates or a
slightly low rate) or **Unstable** (much lower rate or long pauses).

Detection works on Windows only. On Linux and macOS the button shows a message instead;
steps 2 and 3 still work there.

## 2. No game running? Scan Valve servers

**Scan Valve servers** loads Valve's public server list and pings every location for about
20 seconds. It needs no administrator permission. The table is ranked by loss first, then
by average latency, so the best location is at the top. Press **Use** on a row to make it
the target of the path diagnosis.

You can also type a server address you already know (for example from the game console of
a community server) and press **Use address**.

## 3. Path diagnosis

1. Choose how long to measure: 2, 5 or 10 minutes. Longer runs catch problems that only
   come and go. Play while it runs, so the problem has a chance to show up.
2. Press **Start diagnosis**. The app first traces the route to the server (this can take
   about 25 seconds), then pings every hop on the route once a second. The table updates every round:

| Column | Meaning |
|---|---|
| Hop | Position on the route; 1 is usually your router. |
| Address | The router that answered. `* no reply` = no router answered at this hop during the trace. |
| Owner / ASN | The network that owns the router: your provider, a transit carrier or Valve. |
| Loss % | Pings to this hop that got no answer. `no ping reply` = the router forwards traffic but never answers pings itself; that is normal. |
| Avg, p95 | Average latency, and the latency 95 % of answers were faster than. |
| Jitter | How much the latency jumps from one ping to the next. |

3. **Stop** ends the run early; what was measured so far still gets a verdict.

## Reading the verdict

When the run ends, a banner names the part of the path where packet loss to the server starts.
It is based on loss; latency and jitter are shown in the table for you to judge.

| Verdict | What it means | What you can do |
|---|---|---|
| No notable packet loss | Less than 1 % of pings to the server were lost while measuring. | Problems that remain are on the server side or in the game itself. |
| Your home network | Loss already starts at your router or your own link. | Use a cable instead of Wi-Fi, restart the router, check other devices that download. |
| Your internet provider | The problem starts inside your provider's network. | Save the report and send it to your provider. |
| Between your provider and Valve | A transit network between them. | Usually temporary; your provider can sometimes route around it. Report it to them. |
| Valve server / its network | Only Valve's own hops show the problem. | Try another server location; nothing on your side will fix it. |
| Inconclusive | The path could not be judged: the server answers no pings, too few probes were made, or no hop replied. | Rely on the game-stream numbers from **Detect server** (rate, max gap, gaps over 40 ms), or run a longer diagnosis. |

The hop where the problem starts is highlighted in the table.

**Loss at a middle hop alone is not a problem.** Many routers answer pings only when they
have nothing better to do and ignore them under load, while they still forward your game
traffic at full speed. Such loss shows in the table but does not continue to the following
hops. Only loss that starts at a hop and continues all the way to the last hop (the server)
reaches your game, and only that is used for the verdict.

## Saving the report

**Save report** (top right) writes three files with the same name,
`game-connection-<date>-<time>`, to the folder the Network health page uses for its logs
(by default `Documents/network-test-tool`):

| File | What it is for |
|---|---|
| `.html` | The report to read and share (see below). |
| `.md` | The same findings as plain text, readable as is. |
| `.json` | All measurements, including the detection and the server scan, for tools and AI assistants. |

The page then shows the file names. **Open report** opens the HTML report in your browser;
**Open report folder** opens the folder.

### The HTML report

One page with these sections:

- **Result**: the verdict, in the colour of the problem area, with how long and how often
  was measured.
- **Key facts**: the server, its Valve location, your internet provider, and the server's
  loss and latency.
- **Timeline**: what happened during the run, and the detection when it found this same
  server.
- **Loss over time**: strips for the server, your router, the hop where the loss starts
  and each comparison server, showing when pings were lost. Each square is one ping; on
  long runs several pings share a square (at most 120 squares per strip).
- **Path to the server**: the hop table with owners, loss and latency.
- **Valve relay scan**: the scan results, when you ran a scan.
- **What we know, what we don't**: which conclusions are measured and which are not (for
  example routers that do not answer ping).
- **Next steps**: what to do for this verdict, and which raw files belong to the report.

The detection results (port and game-stream numbers) are included only when **Detect
server** found exactly the address that was diagnosed, and the scan only when it was done
before the diagnosis started; a later detection or scan never ends up in an earlier
report.

**Comparison servers.** If you ran **Scan Valve servers** before the diagnosis, the best
one or two other Valve locations from the scan are pinged in the same rounds as the
target. They appear only in the report, so you can see whether loss is specific to your
server or affects other Valve locations too.

The page is a single file that works offline: no scripts, nothing is loaded from the
internet, and it follows your system's light or dark mode. Mail it or attach it to a
support ticket as it is, or print it (or save it as PDF) from the browser; the print
layout keeps sections together.

The detection result, the server scan and the last diagnosis are also included in the
package that **Ask AI agent** prepares.

## Troubleshooting

- **Detect server says the permission was declined.** Press it again and choose **Yes** in
  the Windows prompt. Without it, use **Scan Valve servers** instead.
- **"No incoming game traffic was seen."** You were in the menu or between rounds. Join a match and
  try again while playing.
- **"Another packet capture (pktmon) is already in use."** Detection uses Windows' built-in
  packet monitor (`pktmon`), which has only one capture and one filter list for the whole
  system. If another capture is running, or pktmon filters are already set up (by you or
  another tool), Detect server refuses to start and leaves them untouched. Stop that capture
  or remove those filters yourself (`pktmon stop`, `pktmon filter remove` in an
  administrator terminal) if you no longer need them, then try again. Detect server removes
  only the filter it added itself.
- **The diagnosis sits at "Tracing the route…".** The trace waits for routers that do not
  answer; it can take about 25 seconds before probing starts.
- **Many hops show `no ping reply` or `* no reply`.** Those routers ignore pings. It does not
  affect your game as long as the later hops and the server answer.
