# Dashboard

The Dashboard is the overview page. It refreshes every 10 seconds.

## Connection path

**This PC → Gateway → DNS → Internet**, with the latency of each link above the line.

| What you see | Meaning |
|---|---|
| All nodes OK | The connection works up to the internet. |
| Gateway failed | This computer cannot reach the router: cable, Wi-Fi, adapter or router problem. |
| DNS failed, gateway OK | Names cannot be looked up; websites fail although the line works. |
| Internet failed, gateway OK | The router answers but the internet does not: internet provider or modem problem. |
| Hollow node | Not tested because an earlier link failed. |

The status card at the bottom of the menu summarises the same result: **Online**,
**Local only** (network but no internet) or **Offline**.

## Issues

When problems are found, an Issues card lists them with the evidence and a fix button:

- **APIPA address** (169.254.x.x): the adapter got no address from DHCP → **Renew IP**.
- **DNS resolution failed** → **Flush DNS**, or switch to 8.8.8.8 / 1.1.1.1.
- **Gateway unreachable** or **No default gateway** → **Troubleshoot** or **Renew IP**.
- **Multiple active adapters** (physical ones only): traffic may take the wrong one.

## Gateway latency

A live chart of the round-trip time to your router over the last 10 minutes, measured
every 2 seconds while the Dashboard is open. Spikes here point to a busy or failing local
network (Wi-Fi interference, an overloaded router).

## Adapters

Every network adapter except loopback, active ones first: name, state (**Active**,
**Limited** for APIPA, **Inactive**), IPv4 address and MAC address.

## Quick actions

Pick **All adapters** or one adapter, then:

- **Renew IP** asks DHCP for a new address (Linux: re-activates the NetworkManager
  connection).
- **Flush DNS** clears the DNS cache.
- **Release IP** gives the address back; the connection drops until you renew. The app
  asks before doing this.

These change your system, so they may ask for your password.

## Last speed test and recent tests

The last speed test result and the latest results of every tool. **Open** shows a stored
result on its page.

## Generate report

Saves a text report with system information, detected issues, adapters, gateway, DNS
and the ARP table. See [Reports, exports and log files](Reporting.md).
