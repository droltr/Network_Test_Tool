import threading
import time
from typing import Optional, Callable, Dict
import speedtest


class SpeedTester:
    """Internet speed test with progress tracking and detailed results."""
    
    def __init__(self):
        self.download_speed = 0.0
        self.upload_speed = 0.0
        self.ping_latency = 0.0
        self.server_info = {}
        self.is_testing = False
        
    def perform_speed_test(self, progress_callback: Optional[Callable] = None) -> Dict:
        """Perform a complete speed test with progress tracking."""
        self.is_testing = True
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
            st = speedtest.Speedtest()
            
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
            
            # Get best server
            st.get_best_server()
            server_info = st.results.server
            
            results['server'] = {
                'name': server_info.get('name', 'Unknown'),
                'sponsor': server_info.get('sponsor', 'Unknown'),
                'country': server_info.get('country', 'Unknown'),
                'distance': round(server_info.get('d', 0), 2)
            }
            
            if not self.is_testing:
                return results
            
            if progress_callback:
                progress_callback(30, "Testing ping...")
            
            # Test ping
            ping_result = st.results.ping
            results['ping'] = round(ping_result, 2)
            self.ping_latency = results['ping']
            
            if not self.is_testing:
                return results
            
            if progress_callback:
                progress_callback(40, "Testing download speed...")
            
            # Test download with progress tracking
            download_result = st.download(callback=self._create_progress_callback(
                progress_callback, 40, 70, "Testing download speed..."
            ))
            results['download_speed'] = round(download_result / 1_000_000, 2)  # Convert to Mbps
            self.download_speed = results['download_speed']
            
            if not self.is_testing:
                return results
            
            if progress_callback:
                progress_callback(70, "Testing upload speed...")
            
            # Test upload with progress tracking
            upload_result = st.upload(callback=self._create_progress_callback(
                progress_callback, 70, 95, "Testing upload speed..."
            ))
            results['upload_speed'] = round(upload_result / 1_000_000, 2)  # Convert to Mbps
            self.upload_speed = results['upload_speed']
            
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
    
    def _create_progress_callback(self, main_callback: Optional[Callable], 
                                start_progress: int, end_progress: int, message: str):
        """Create a progress callback for download/upload operations."""
        if not main_callback:
            return None
        
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
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
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