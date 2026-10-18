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
| Monitor session | `monitor-session-<date>-<time>.md` (report) and `.csv` (samples) | same |
| Ask AI agent | `network-diagnostics-<date>-<time>.md` | same, when you press Save to folder |
| Debug and crash logs | `network_detector_debug.log`, `crash_log.txt` | `~/.local/state/network-test-tool/` (Windows: `%LOCALAPPDATA%\NetworkTestTool\`) |

The monitor and AI folders can be changed in their pages. CSV files open in any
spreadsheet program; the `time` column is local time in ISO format.

## Recent tests

The latest 30 results of Diagnose host, Port scanner, Speed test, iPerf3 and monitor
sessions are stored in the app settings and listed on the Dashboard. They stay on this
computer.
