# Ask AI agent

**Ask AI agent** (bottom of the menu) prepares your results for the AI assistant you
already use: ChatGPT, Claude, Gemini or any other. The app has no AI of its own and sends
nothing anywhere; you paste or attach the package yourself.

## What goes into the package

- **System, network information and detected issues:** operating system, adapters,
  gateway, DNS servers, the connection path with latencies and the Dashboard issues.
- **Recent test results** you tick: Diagnose host, Port scan, Speed test, iPerf3 and
  monitor sessions.
- **Logs from this session:** the Troubleshooter log, the Network health scan, the
  Connection monitor summary and the last session report, when they exist.
- **Instructions for the assistant:**
  - **Simple explanation:** a verdict in plain language, the problems with their evidence,
    step-by-step fixes (easiest first) and which test to run next.
  - **Expert analysis:** a layer-by-layer review, root-cause candidates ranked with
    evidence, anomalies (VPN leftovers, dead DNS, retransmits, MTU) and exact commands.
- **Your question** (optional) and the **language** the answer should be in.

The package is Markdown with the full data in a JSON block, which every major assistant
reads well.

## Privacy

On by default:

- **Mask MAC addresses** → `MAC_1`, `MAC_2`…
- **Mask public IP addresses** → `PUBLIC_IP_1`… Local addresses (192.168.x.x, 10.x.x.x)
  and well-known public DNS servers (8.8.8.8, 1.1.1.1…) stay visible because they matter
  for the analysis.
- **Mask the computer name** → `HOSTNAME`.

The preview shows exactly what will be shared.

## Sending it

- **Copy to clipboard**, then paste into your assistant.
- **Save to folder** writes `network-diagnostics-<date>-<time>.md` into the save folder.
- **Save as…** lets you choose the file name and place.

Then attach the file or paste the text in your assistant and send it. Check the answer
against the data: the instructions ask the assistant to separate evidence from assumptions,
but it can still be wrong.
