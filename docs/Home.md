# Network Test Tool

## What this tool is for

Network Test Tool helps you find **where** a network connection breaks and **why** — on your
own computer, in your local network, at your internet provider, or at the service you are
trying to reach. It is a desktop app for Linux, Windows and macOS that puts the usual
command-line tools (ping, traceroute, port checks, speed tests, iperf3) behind one
interface, adds checks those tools cannot do on their own, and explains the results.

Use it when:

- the internet is slow, drops for a few seconds, or works for some sites but not others;
- you want to measure your real line speed, or the speed between two computers;
- you removed a VPN or changed network settings and something stopped working;
- you need a clear report to send to your internet provider, IT support or an AI assistant.

Tests only read and measure. Nothing on your system changes unless you press an action
button such as Renew IP or Flush DNS, and those ask for your password first.

## Where to start

1. Open the **Dashboard**. The connection path (This PC → Gateway → DNS → Internet)
   shows at a glance which link is failing.
2. If a link fails or the connection feels unstable, run the **Network health** scan, then
   start the **Connection monitor** and record a session while the problem happens.
3. To check one service or address, use **Diagnose host**.
4. To measure throughput, use **Speed test** (internet) or **iPerf3** (any two points).
5. Press **Ask AI agent** to package everything for the AI assistant you already use.

## User guide

- [Installation and setup](Installation.md)
- [Dashboard](User-Guide-Network-Status.md)
- [Diagnostic tools: Diagnose host, Port scanner, Speed test, Advanced, Troubleshooter](User-Guide-Diagnostic-Tools.md)
- [iPerf3 client and server](User-Guide-iPerf3.md)
- [Network health: scan and connection monitor](User-Guide-Network-Health.md)
- [Ask AI agent](User-Guide-Ask-AI.md)
- [Reports, exports and log files](Reporting.md)
- [Troubleshooting and FAQ](Troubleshooting.md)
- [Privacy and security](Security.md)

## Using the interface

- The menu on the left lists every page. Group titles (Overview, Tools, System) are labels;
  the entries under them open pages. A dot or tag next to an entry means a test is running
  there; tests keep running when you switch pages.
- Results of Diagnose host, Port scanner, Speed test, iPerf3 and monitor sessions are kept
  under **Recent tests** on the Dashboard; **Open** shows them again.
- **View → Theme** switches between the available themes (applied after a restart).
- **Help → User guide** (F1) opens this guide inside the app.

## Download

Ready-made single-file apps for Windows, Linux and macOS are on the
[Releases page](https://github.com/droltr/Network_Test_Tool/releases). To build one yourself,
see [Installation and setup](Installation.md).
