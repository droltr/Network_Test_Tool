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
                response_time = self._single_ping(host, timeout)
                
                if response_time is not None:
                    received += 1
                    times.append(response_time)
                    status = "Reply"
                    message = f"Reply from {host}: time={response_time:.1f}ms"
                else:
                    status = "Timeout"
                    message = f"Request timeout for {host}"
                
                results['responses'].append({
                    'sequence': i + 1,
                    'time': response_time,
                    'status': status
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
        """Perform a single ping and return response time in milliseconds"""
        try:
            if self.platform == "windows":
                cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), host]
            else:
                cmd = ["ping", "-c", "1", "-W", str(timeout), host]
            
            start_time = time.time()
            result = subprocess.run(cmd, capture_output=True, timeout=timeout + 1)
            end_time = time.time()
            
            if result.returncode == 0:
                # Parse response time from output
                output = result.stdout.decode('utf-8').decode('utf-8')
                if self.platform == "windows":
                    if "time=" in output:
                        time_str = output.split("time=")[1].split("ms")[0]
                        return float(time_str)
                else:
                    if "time=" in output:
                        time_str = output.split("time=")[1].split(" ")[0]
                        return float(time_str)
                
                # If parsing fails, calculate from execution time
                return (end_time - start_time) * 1000
            else:
                return None
                
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
            return None
        except Exception:
            return None