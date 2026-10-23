import math
import platform
import re
import subprocess
import time
import statistics
from datetime import datetime

from utils.paths import run_command

# Ping output is translated on Windows ("time=21ms" is "süre=21ms" on Turkish systems, an unreachable
# reply reads "Hedef ana bilgisayara ulaşılamıyor"), so replies are recognised by structure instead of
# words: a label glued to '=' or '<', a number and "ms" ("time<1ms", "süre=21ms", "temps=21 ms",
# Linux "time=1.23 ms"). The statistics line ("Minimum = 17ms") has a space before '=' and never matches.
# Error replies (unreachable, TTL expired) carry no time and count as lost.
_TIME_RE = re.compile(r'\S([=<])\s?(\d+(?:[.,]\d+)?)\s*ms\b', re.IGNORECASE)
_TTL_RE = re.compile(r'\bttl=(\d+)', re.IGNORECASE)
# Fallback for locales whose unit is not "ms" (Russian "время=21мс TTL=118"): last value before TTL=
_TTL_TIME_RE = re.compile(r'\S([=<])\s?(\d+(?:[.,]\d+)?)\D*\bttl=', re.IGNORECASE)


def parse_ping_line(line):
    """(ms, ttl) when the line is an echo reply, else None. "<1ms" counts as 0.5 ms."""
    match = _TIME_RE.search(line) or _TTL_TIME_RE.search(line)
    if not match:
        return None
    ms = float(match.group(2).replace(',', '.'))
    if match.group(1) == '<':
        ms = min(ms, 1.0) / 2
    ttl = _TTL_RE.search(line)
    return ms, int(ttl.group(1)) if ttl else None


def parse_ping_output(output):
    """All echo replies in a ping output as a list of (ms, ttl)."""
    return [reply for reply in map(parse_ping_line, output.splitlines()) if reply]


def ping_command(host, timeout=1.0, count=1, extra=()):
    """Platform ping command; timeout is the wait per reply in seconds."""
    if platform.system().lower() == "windows":
        return ["ping", "-n", str(count), "-w", str(int(timeout * 1000)), *extra, host]
    return ["ping", "-c", str(count), "-W", str(max(1, math.ceil(timeout))), *extra, host]


def ping_reply(host, timeout=1.0):
    """Ping once: (ms, ttl) of the reply, or None when nothing answered (timeout, unreachable, error)."""
    try:
        result = run_command(ping_command(host, timeout), timeout=timeout + 2)
    except (OSError, subprocess.SubprocessError):
        return None
    replies = parse_ping_output(result.stdout)
    return replies[0] if replies else None


class PingTester:
    def __init__(self):
        self.platform = platform.system().lower()
        self.is_running = False

    def stop(self):
        """Stop an ongoing ping_host() after the current echo request."""
        self.is_running = False
        
    def ping_host(self, host, count=4, timeout=3, progress_callback=None, reply_callback=None):
        """Ping a host and return detailed results.

        reply_callback, if given, receives each response dict (sequence, time, status, ttl)
        as soon as it arrives.
        """
        self.is_running = True
        try:
            results = {
                'host': host,
                'count': count,
                'responses': [],
                'statistics': {},
                'timestamp': datetime.now().isoformat()
            }
            
            times = []
            sent = 0
            received = 0
            
            for i in range(count):
                if not self.is_running:
                    results['stopped'] = True
                    break
                sent += 1
                ping_data = self._single_ping(host, timeout)
                
                ttl = None
                if ping_data and ping_data.get('time') is not None:
                    received += 1
                    response_time = ping_data['time']
                    ttl = ping_data.get('ttl')
                    times.append(response_time)
                    status = "Reply"
                    message = f"Reply from {host}: time={response_time:.1f}ms"
                    if ttl:
                        message += f" TTL={ttl}"
                else:
                    response_time = None
                    status = "Timeout"
                    message = f"Request timeout for {host}"
                
                response = {
                    'sequence': i + 1,
                    'time': response_time,
                    'status': status,
                    'ttl': ttl
                }
                results['responses'].append(response)
                
                if progress_callback:
                    progress_callback(message)
                if reply_callback:
                    reply_callback(response)
                
                if i < count - 1:  # Don't sleep after last ping
                    # Sleep in small steps so stop() takes effect quickly
                    deadline = time.monotonic() + 1
                    while self.is_running and time.monotonic() < deadline:
                        time.sleep(0.05)
            
            # Calculate statistics
            lost = sent - received
            success_rate = (received / sent) * 100 if sent > 0 else 0
            
            stats = {
                'sent': sent,
                'received': received,
                'lost': lost,
                'success_rate': success_rate,
                'times': times
            }
            
            if times:
                stats.update({
                    'min_time': min(times),
                    'max_time': max(times),
                    'avg_time': statistics.mean(times),
                    'std_dev': statistics.stdev(times) if len(times) > 1 else 0
                })
            
            results['statistics'] = stats
            return results
            
        except Exception as e:
            return {'error': str(e), 'host': host}
        finally:
            self.is_running = False
    
    def _single_ping(self, host, timeout):
        """Perform a single ping and return response time and TTL, or None without a reply."""
        reply = ping_reply(host, timeout)
        return {"time": reply[0], "ttl": reply[1]} if reply else None
