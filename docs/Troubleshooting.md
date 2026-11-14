# Troubleshooting and FAQ

**Every ping shows "timeout" although the internet works.**
Ping may be blocked by a firewall on the path or on the target. Try another host (8.8.8.8,
1.1.1.1). On Linux the app runs system tools in English (`LC_ALL=C`) so their output can be
read on any system language; if you build your own version, keep that.

**Renew IP, Release IP or Flush DNS fails.**
These change system settings. On Linux they use NetworkManager and systemd-resolved and may
show a password dialog; without NetworkManager the app falls back to `dhclient`. On Windows,
run the app as administrator.

**"Traceroute command not found."**
Install it: `sudo dnf install traceroute` (Fedora), `sudo apt install traceroute`
(Debian/Ubuntu). On Windows `tracert` is always present.

**NetBIOS lookup is not available.**
Linux needs `nmblookup` from the `samba-client` package.

**The speed test result is much lower than my line speed.**
The app picks the nearest server from speedtest.net's current list. Lower results can come
from Wi-Fi, a busy server, or the speed test client itself on very fast lines. Compare with
an [iPerf3](User-Guide-iPerf3.md) test to a nearby server with 4 or more streams.

**iPerf3 says the server is busy.**
Public servers run one test at a time. The app tries the next port of the server's range
automatically; if all are busy, pick another server or try again later.

**Other devices cannot reach my iPerf3 server.**
Open the port in the firewall (for example `sudo firewall-cmd --add-port=5201/tcp`) and use
this computer's local IP address shown on the Server tab.

**The internet drops for a few seconds and a DNS flush or IP renew helps for a while.**
Run the [Network health](User-Guide-Network-Health.md) scan. Leftovers of a removed VPN
(routes, DNS servers, adapters) are a common cause. Then record a monitor session while the
problem happens to see which layer fails.

**Where are my logs and settings?**
See [Reports, exports and log files](Reporting.md) and the file table in
[Installation and setup](Installation.md).

**The window does not fit my screen.**
The minimum window size is 1200 × 760 pixels; on a smaller or portrait screen, use a
landscape monitor or a higher screen resolution.
