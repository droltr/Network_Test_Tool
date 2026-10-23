"""Stop paths: TraceRoute reuse and stop/start race, ConnectionMonitor stop latency (no network needed)."""
import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network import monitor  # noqa: E402
from network.trace import TraceRoute  # noqa: E402


class _FakeProcess:
    """Popen stand-in that prints one hop line per readline until terminated."""

    def __init__(self, *args, **kwargs):
        self.terminated = threading.Event()
        self.lines = [b"  1    <1 ms    <1 ms    <1 ms  10.0.0.1\r\n", b"  2     5 ms     5 ms     5 ms  10.0.0.2\r\n"]
        self.stdout = self

    def readline(self):
        if self.lines and not self.terminated.is_set():
            return self.lines.pop(0)
        return b""

    def close(self):
        pass

    def poll(self):
        return 0

    def terminate(self):
        self.terminated.set()

    def wait(self, timeout=None):
        return 0


class TraceCancellationTest(unittest.TestCase):
    def setUp(self):
        self.popen = mock.patch("network.trace.subprocess.Popen", side_effect=_FakeProcess)
        self.popen_mock = self.popen.start()
        self.addCleanup(self.popen.stop)
        self.tracer = TraceRoute()
        self.tracer.platform = "windows"

    def run_trace(self):
        hops = []
        self.tracer.run_trace("10.0.0.2", hops.append, max_hops=3)
        return hops

    def test_reuse(self):
        self.assertEqual(len(self.run_trace()), 2)
        self.assertEqual(len(self.run_trace()), 2)

    def test_stop_before_start_cancels_only_the_next_run(self):
        self.tracer.stop()
        self.assertEqual(self.run_trace(), [])
        self.assertEqual(self.popen_mock.call_count, 0)
        self.assertEqual(len(self.run_trace()), 2)   # the cancellation was used up

    def test_stop_during_run_then_reuse(self):
        def stop_on_first_hop(hop):
            hops.append(hop)
            self.tracer.stop()
        hops = []
        self.tracer.run_trace("10.0.0.2", stop_on_first_hop, max_hops=3)
        self.assertEqual(len(hops), 1)
        self.assertFalse(self.tracer.is_running)
        self.assertEqual(len(self.run_trace()), 2)

    def test_stop_between_check_and_popen(self):
        # stop() arriving after run_trace() started but before the process exists prevents the Popen
        original = self.tracer._start_process

        def late_stop(command, cancel):
            self.tracer.stop()
            return original(command, cancel)
        self.tracer._start_process = late_stop
        self.assertEqual(self.run_trace(), [])
        self.assertEqual(self.popen_mock.call_count, 0)
        del self.tracer._start_process
        self.assertEqual(len(self.run_trace()), 2)


class MonitorStopTest(unittest.TestCase):
    def test_stop_does_not_wait_for_slow_probes(self):
        events = []
        mon = monitor.ConnectionMonitor(interval=0.5, callback=lambda kind, data: events.append(kind))
        mon._targets = lambda: {"gateway": "10.0.0.1", "dns": "10.0.0.1", "internet": "x"}
        mon._snapshot_interfaces = lambda: {}

        def slow_probe(name, address):
            time.sleep(4)   # a ping running into its subprocess timeout
            return {"ok": False, "ms": None, "address": address}
        mon._probe_target = slow_probe
        worker = threading.Thread(target=mon.run)
        worker.start()
        time.sleep(0.5)
        started = time.monotonic()
        mon.stop()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 1.5)
        time.sleep(4)
        self.assertNotIn("sample", events)   # no late callback from the probes still running at stop()


if __name__ == "__main__":
    unittest.main()
