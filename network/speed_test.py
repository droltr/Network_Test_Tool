import json
import socket
import threading
import time
import urllib.request
from typing import Optional, Callable, Dict

import psutil

from utils.paths import command_env, console_encoding

try:
    # Bundled, unmodified copy of speedtest-cli by Matt Martz (Apache 2.0),
    # https://github.com/sivel/speedtest-cli - see THIRD_PARTY_NOTICES.md
    from utils import speedtest
except ImportError:
    import speedtest


class SpeedTester:
    """Internet speed test with progress tracking and detailed results."""
    
    def __init__(self):
        self.download_speed = 0.0
        self.upload_speed = 0.0
        self.ping_latency = 0.0
        self.server_info = {}
        self.is_testing = False
        self._shutdown_event = threading.Event()
        
    def perform_speed_test(self, progress_callback: Optional[Callable] = None,
                           info_callback: Optional[Callable] = None) -> Dict:
        """Perform a complete speed test with progress tracking.

        info_callback(kind, value), if given, receives intermediate data as it becomes known:
        ('server', dict), ('ping', ms), ('download', Mbps), ('upload', Mbps) and
        ('sample', (phase, seconds_since_phase_start, Mbps)) about every half second.
        """
        self.is_testing = True
        self._shutdown_event.clear()
        info = info_callback or (lambda kind, value: None)
        results = {
            'download_speed': 0.0,
            'upload_speed': 0.0,
            'ping': 0.0,
            'server': {},
            'error': None
        }
        
        try:
            if progress_callback:
                progress_callback(10, "Initializing speed test...")
            
            # Initialize speedtest
            st = speedtest.Speedtest(shutdown_event=self._shutdown_event)
            
        except speedtest.SpeedtestException as e:
            results['error'] = f"Speedtest Error: {str(e)}"
            if progress_callback:
                progress_callback(100, f"Speedtest Error: {str(e)}")
            self.is_testing = False
            return results
        except Exception as e:
            results['error'] = f"An unexpected error occurred: {str(e)}"
            if progress_callback:
                progress_callback(100, f"Error: {str(e)}")
            self.is_testing = False
            return results
        
        try:
            
            if progress_callback:
                progress_callback(20, "Finding best server...")
            
            # Get best server. speedtest-cli's legacy server list can miss every nearby
            # server (from Istanbul its closest entry was 1412 km away), so prefer the
            # location-sorted list from speedtest.net's newer server API.
            nearby = self._nearby_servers()
            if nearby:
                st.get_best_server(nearby)
            else:
                st.get_best_server()
            server_info = st.results.server
            
            results['server'] = {
                'name': server_info.get('name', 'Unknown'),
                'sponsor': server_info.get('sponsor', 'Unknown'),
                'country': server_info.get('country', 'Unknown'),
                'distance': round(server_info.get('d', 0), 2)
            }
            self.server_info = results['server']
            info('server', results['server'])
            
            if not self.is_testing:
                return results
            
            if progress_callback:
                progress_callback(30, "Testing ping...")
            
            # Test ping
            ping_result = st.results.ping
            results['ping'] = round(ping_result, 2)
            self.ping_latency = results['ping']
            info('ping', results['ping'])
            
            if not self.is_testing:
                return results
            
            if progress_callback:
                progress_callback(40, "Testing download speed...")
            
            # Test download with progress tracking
            with self._throughput_sampler('download', info):
                download_result = st.download(callback=self._create_progress_callback(
                    progress_callback, 40, 70, "Testing download speed..."
                ))
            results['download_speed'] = round(download_result / 1_000_000, 2)  # Convert to Mbps
            self.download_speed = results['download_speed']
            info('download', results['download_speed'])
            
            if not self.is_testing:
                return results
            
            if progress_callback:
                progress_callback(70, "Testing upload speed...")
            
            # Test upload with progress tracking
            with self._throughput_sampler('upload', info):
                # speedtest.net suggests 2 upload threads, too few for gigabit lines;
                # use at least as many as the download (8)
                upload_threads = max(8, st.config['threads']['upload'])
                upload_result = st.upload(callback=self._create_progress_callback(
                    progress_callback, 70, 95, "Testing upload speed..."
                ), threads=upload_threads)
            results['upload_speed'] = round(upload_result / 1_000_000, 2)  # Convert to Mbps
            self.upload_speed = results['upload_speed']
            info('upload', results['upload_speed'])

            if not self.is_testing:
                return results
            
            if progress_callback:
                progress_callback(100, "Speed test completed!")
                
        except speedtest.SpeedtestException as e:
            results['error'] = f"Speedtest Error: {str(e)}"
            if progress_callback:
                progress_callback(100, f"Speedtest Error: {str(e)}")
        except Exception as e:
            results['error'] = f"An unexpected error occurred: {str(e)}"
            if progress_callback:
                progress_callback(100, f"Error: {str(e)}")
        
        self.is_testing = False
        return results

    def _throughput_sampler(self, phase: str, info: Callable):
        """Context manager that reports interface throughput (Mbps) while a phase runs.

        speedtest-cli only reports the final rate, so the live value is measured from the byte
        counters of the interface that carries the default route. Other traffic on that
        interface during the test is included.
        """
        tester = self
        iface = self._primary_interface()

        def counter(field):
            if iface:
                stats = psutil.net_io_counters(pernic=True).get(iface)
                if stats is not None:
                    return getattr(stats, field)
            return getattr(psutil.net_io_counters(), field)

        class Sampler:
            def __enter__(self):
                self.stop = threading.Event()
                self.thread = threading.Thread(target=self.run, daemon=True)
                self.thread.start()
                return self

            def run(self):
                field = 'bytes_recv' if phase == 'download' else 'bytes_sent'
                start = time.monotonic()
                # Rate over a sliding one-second window, sampled every half second
                window = [(start, counter(field))]
                while not self.stop.wait(0.5) and tester.is_testing:
                    now = time.monotonic()
                    window.append((now, counter(field)))
                    while len(window) > 3:
                        window.pop(0)
                    (t0, b0), (t1, b1) = window[0], window[-1]
                    mbps = (b1 - b0) * 8 / (t1 - t0) / 1_000_000
                    info('sample', (phase, round(now - start, 2), round(mbps, 2)))

            def __exit__(self, *exc):
                self.stop.set()
                self.thread.join(timeout=1)
                return False

        return Sampler()
    
    @staticmethod
    def _nearby_servers(limit=10):
        """Closest servers from speedtest.net's server API, in speedtest-cli's format.

        > **⚠️ ASSUMPTION:** this endpoint is the one the speedtest.net web client uses;
        > it is not a documented public API and may change. Based on: its JSON response
        > (2026-10-10). Returns None on any failure so the caller falls back.
        """
        url = f"https://www.speedtest.net/api/js/servers?engine=js&limit={limit}&https_functional=true"
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 network-test-tool'})
            with urllib.request.urlopen(request, timeout=6) as response:
                data = json.loads(response.read().decode('utf-8'))
        except (OSError, ValueError):
            return None
        servers = []
        for entry in data if isinstance(data, list) else []:
            if not entry.get('url'):
                continue
            servers.append({
                'url': entry['url'],
                'lat': str(entry.get('lat', 0)),
                'lon': str(entry.get('lon', 0)),
                'name': entry.get('name', 'Unknown'),
                'country': entry.get('country', 'Unknown'),
                'cc': entry.get('cc', ''),
                'sponsor': entry.get('sponsor', 'Unknown'),
                'id': str(entry.get('id', '')),
                'host': entry.get('host', ''),
                'd': float(entry.get('distance', 0) or 0),
            })
        return servers or None

    @staticmethod
    def _primary_interface():
        """Name of the interface used to reach the internet, or None."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 53))
                local_ip = s.getsockname()[0]
        except OSError:
            return None
        for name, addrs in psutil.net_if_addrs().items():
            if any(a.family == socket.AF_INET and a.address == local_ip for a in addrs):
                return name
        return None

    def _create_progress_callback(self, main_callback: Optional[Callable], 
                                start_progress: int, end_progress: int, message: str):
        """Create a progress callback for download/upload operations."""
        if not main_callback:
            # speedtest-cli calls the callback unconditionally, so never hand it None
            return lambda *args, **kwargs: None
        
        last_progress = [start_progress]
            
        def callback(i, request_count, **kwargs):
            if not self.is_testing:
                return
            progress = start_progress + int((i / request_count) * (end_progress - start_progress))
            # Only update if progress has changed significantly (at least 5% difference)
            if abs(progress - last_progress[0]) >= 5:
                main_callback(min(progress, end_progress), message)
                last_progress[0] = progress
        
        return callback
    
    def perform_speed_test_threaded(self, progress_callback: Optional[Callable] = None,
                                  complete_callback: Optional[Callable] = None):
        """Perform speed test in a separate thread."""
        def test_worker():
            results = self.perform_speed_test(progress_callback)
            if complete_callback:
                complete_callback(results)
        
        thread = threading.Thread(target=test_worker, daemon=True)
        thread.start()
        return thread
    
    def stop_test(self):
        """Stop the current speed test."""
        self.is_testing = False
        # Makes speedtest-cli abort its download/upload threads
        self._shutdown_event.set()
    
    def get_results(self) -> Dict:
        """Get the last test results."""
        return {
            "download_speed": self.download_speed,
            "upload_speed": self.upload_speed,
            "ping": self.ping_latency,
            "server": self.server_info
        }
    
    def test_latency(self, host: str = "8.8.8.8", count: int = 4) -> Dict:
        """Test network latency to a specific host."""
        import subprocess
        import platform
        import re
        
        try:
            # Determine ping command based on OS
            if platform.system().lower() == 'windows':
                cmd = ['ping', '-n', str(count), host]
            else:
                cmd = ['ping', '-c', str(count), host]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=command_env(),
                                    encoding=console_encoding(), errors='replace')
            
            if result.returncode == 0:
                output = result.stdout
                
                # Extract latency values (this is OS-specific)
                if platform.system().lower() == 'windows':
                    times = re.findall(r'time[<=](\d+)ms', output)
                else:
                    times = re.findall(r'time=(\d+\.?\d*)', output)
                
                if times:
                    latencies = [float(t) for t in times]
                    return {
                        'avg_latency': round(sum(latencies) / len(latencies), 2),
                        'min_latency': round(min(latencies), 2),
                        'max_latency': round(max(latencies), 2),
                        'packet_loss': 0,  # Could be extracted from ping output
                        'host': host
                    }
            
            return {
                'avg_latency': 0,
                'min_latency': 0,
                'max_latency': 0,
                'packet_loss': 100,
                'host': host,
                'error': 'Failed to ping host'
            }
            
        except Exception as e:
            return {
                'avg_latency': 0,
                'min_latency': 0,
                'max_latency': 0,
                'packet_loss': 100,
                'host': host,
                'error': str(e)
            }