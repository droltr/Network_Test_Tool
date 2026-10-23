"""iperf3 server parameter validation and the byte budget of -n / -k tests (no network needed)."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network import iperf  # noqa: E402


class _FakeControl:
    def __init__(self):
        self.sent = b""

    def sendall(self, data):
        self.sent += data


class CheckParamsTest(unittest.TestCase):
    BASE = {"tcp": True, "time": 10, "parallel": 2, "len": 131072}

    def setUp(self):
        self.server = iperf.IperfServer(max_duration=60)

    def check(self, **changes):
        return self.server._check_params(_FakeControl(), "client", {**self.BASE, **changes})

    def rejected(self, params):
        ctrl = _FakeControl()
        with self.assertRaises(iperf.IperfError):
            self.server._check_params(ctrl, "client", params)
        state, code, _errno = struct.unpack("!bii", ctrl.sent)
        self.assertEqual(state, iperf.SERVER_ERROR)
        return code

    def test_valid_duration_test(self):
        self.assertEqual(self.check(), (2, False, 10.0, 131072, False, 0))

    def test_reverse(self):
        self.assertTrue(self.check(reverse=True)[1])

    def test_duration_above_maximum_is_clamped(self):
        self.assertEqual(self.check(time=10 ** 9)[2:5:2], (60.0, True))

    def test_byte_count_test(self):
        # iperf3 -n 1M sends time 0 and bytes; the test is not turned into a plain duration test
        parallel, reverse, duration, blksize, clamped, byte_limit = self.check(time=0, bytes=1048576)
        self.assertEqual(byte_limit, 1048576)
        self.assertEqual(duration, 60.0)   # only the safety limit

    def test_block_count_test(self):
        self.assertEqual(self.check(time=0, blockcount=5, len=1000)[5], 5000)

    def test_bytes_and_blocks_first_limit_wins(self):
        self.assertEqual(self.check(time=0, bytes=3000, blockcount=5, len=1000)[5], 3000)

    def test_invalid_values(self):
        cases = [({"len": 10 ** 12}, iperf.IEBLOCKSIZE), ({"len": -5}, iperf.IEBLOCKSIZE),
                 ({"len": 1.5}, iperf.IEBLOCKSIZE), ({"parallel": 100000}, iperf.IENUMSTREAMS),
                 ({"parallel": True}, iperf.IENUMSTREAMS), ({"time": -1}, iperf.IEDURATION),
                 ({"time": "9999"}, iperf.IEDURATION), ({"udp": True}, iperf.IEUNIMP),
                 ({"bidirectional": True}, iperf.IEUNIMP), ({"bytes": -1}, iperf.IEUNIMP),
                 ({"blockcount": "5"}, iperf.IEUNIMP), ({"bytes": 1.5}, iperf.IEUNIMP)]
        for change, code in cases:
            with self.subTest(change=change):
                self.assertEqual(self.rejected({**self.BASE, **change}), code)

    def test_not_a_dict(self):
        self.assertEqual(self.rejected(["tcp"]), iperf.IEUNIMP)


class SendBudgetTest(unittest.TestCase):
    def test_take_and_give_back(self):
        budget = iperf._SendBudget(250)
        self.assertEqual(budget.take(100), 100)
        self.assertEqual(budget.take(100), 100)
        self.assertEqual(budget.take(100), 50)
        self.assertEqual(budget.take(100), 0)
        budget.give_back(30)
        self.assertEqual(budget.take(100), 30)


if __name__ == "__main__":
    unittest.main()
