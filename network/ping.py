import subprocess
import platform
import time
import socket
import statistics
from datetime import datetime

class PingTester:
    def __init__(self):
        self.platform = platform.system().lower()
        
    def ping_host(self, host, count=4, timeout=3, progress_callback=None):
        """Ping a host and return detailed results"""
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
                sent += 1
                ping_data = self._single_ping(host, timeout)
                
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
                
                results['responses'].append({
                    'sequence': i + 1,
                    'time': response_time,
                    'status': status,
                    'ttl': ttl if 'ttl' in locals() else None
                })
                
                if progress_callback:
                    progress_callback(message)
                
                if i < count - 1:  # Don't sleep after last ping
                    time.sleep(1)
            
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
    
    def _single_ping(self, host, timeout):
        """Perform a single ping and return response time and TTL."""
        try:
            if self.platform == "windows":
                cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), host]
            else:
                cmd = ["ping", "-c", "1", "-W", str(timeout), host]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 1)
            
            if result.returncode == 0:
                output = result.stdout.lower()
                response_time = None
                ttl = None

                # Parse time and TTL
                if self.platform == "windows":
                    if "time=" in output and "ttl=" in output:
                        time_str = output.split("time=")[1].split("ms")[0].strip()
                        ttl_str = output.split("ttl=")[1].split()[0].strip()
                        response_time = float(time_str)
                        ttl = int(ttl_str)
                else: # Linux/macOS
                    if "time=" in output and "ttl=" in output:
                        time_str = output.split("time=")[1].split("ms")[0].strip()
                        ttl_str = output.split("ttl=")[1].split()[0].strip()
                        response_time = float(time_str)
                        ttl = int(ttl_str)
                
                return {"time": response_time, "ttl": ttl}
            else:
                return None
                
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
            return None
        except Exception:
            return None