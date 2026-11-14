# Reports, exports and log files

## Exports from each tool

| Where | Button | File |
|---|---|---|
| Dashboard | Generate report | `network_report_<date>_<time>.txt`: system information, detected issues with solutions, adapters, gateway, DNS, first 10 ARP entries, number of connections |
| Diagnose host | Export | `ping_test_results_<date>_<time>.txt`: every reply and the route |
| Port scanner | Export | `port_scan_results_<date>_<time>.txt`: open ports and a summary |
| Speed test | Export | `speed_test_results_<date>_<time>.txt`: the test log and results |
| iPerf3 | Export | `iperf_results_<date>_<time>.txt`: settings, results and per-second rates |
| Troubleshooter | Export log | `troubleshoot_log_<date>_<time>.txt` |

You choose the place for each file when you save it.

## Files written automatically

| What | File | Default folder |
|---|---|---|
| Connection monitor | `connection-monitor-<date>-<time>.csv` (every probe) and `…-events.csv` (outages and changes) | `~/Documents/network-test-tool/` |
| Monitor session | `monitor-session-<date>-<time>.html` (report), `.md` (report as text) and `.csv` (samples) | same |
| Game connection | `game-connection-<date>-<time>.html` (report), `.md` (report as text) and `.json` (all measurements), when you press Save report | same as the monitor folder |
| Office apps | `office-quick-<date>-<time>` or `office-session-<date>-<time>` with `.html` (report), `.md` (report as text) and `.json` (all measurements), when you press Open report | same as the monitor folder |
| Office apps recording | `office-<date>-<time>.csv` (every sample) and `office-<date>-<time>-events.csv` (events), written while recording | `~/.local/state/network-test-tool/office-logs/` (Windows: `%LOCALAPPDATA%\NetworkTestTool\office-logs\`) |
| Ask AI agent | `network-diagnostics-<date>-<time>.md` | same, when you press Save to folder |
| Debug and crash logs | `network_detector_debug.log`, `crash_log.txt` | `~/.local/state/network-test-tool/` (Windows: `%LOCALAPPDATA%\NetworkTestTool\`) |

The monitor and AI folders can be changed in their pages. CSV files open in any
spreadsheet program; the `time` column is local time in ISO format.

## HTML reports

Monitor sessions, the Game connection diagnosis and the Office apps checks are also saved as an HTML page. It is
the report meant for reading and sharing: the result first, then key facts, a timeline,
loss over time, the detailed tables, what was and was not measured, and next steps.

- **One file, offline.** The page has its styles built in, contains no scripts and loads
  nothing from the internet. It opens in any browser, also without a connection.
- **Light and dark.** It follows the light or dark mode of your system.
- **Share or print.** Mail it or attach it to a support ticket as it is, or print it (or
  save it as PDF) from the browser; the print layout keeps sections together.
- **Open report** on the Game connection and Office apps pages and in the monitor session window opens it
  in your default browser.

The `.md` and `.csv` / `.json` files next to it hold the same results as text and the raw
measurements.

## Recent tests

The latest 30 results of Diagnose host, Port scanner, Speed test, iPerf3 and monitor
sessions are stored in the app settings and listed on the Dashboard. They stay on this
computer.
