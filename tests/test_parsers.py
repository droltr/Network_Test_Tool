"""Parsers of translated Windows tool output (ping, tracert, arp, route print) and Linux ping.

Samples are real output from a Turkish Windows 11 machine or the documented Windows wording of
other locales. Run from the project root: venv\\Scripts\\python.exe -m unittest discover tests
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network import health  # noqa: E402
from network.advanced import ARP_HEADER_RE  # noqa: E402
from network.ping import parse_ping_line, parse_ping_output  # noqa: E402
from network.trace import TraceRoute  # noqa: E402

TR_OK = """
8.8.8.8 32 bayt veri ile ping atılıyor:
8.8.8.8 yanıtı: bayt=32 süre=21ms TTL=118
8.8.8.8 yanıtı: bayt=32 süre<1ms TTL=118

8.8.8.8 için ping istatistiği:
    Paket: Giden = 2, Gelen = 2, Kaybolan = 0 (%0 kayıp),
Mili saniye türünden yaklaşık tur süreleri:
    En Az = 0ms, En Çok = 21ms, Ortalama = 10ms
"""
TR_UNREACHABLE = """
10.90.0.200 32 bayt veri ile ping atılıyor:
10.90.0.3 yanıtı: Hedef ana bilgisayara ulaşılamıyor.

10.90.0.200 için ping istatistiği:
    Paket: Giden = 1, Gelen = 1, Kaybolan = 0 (%0 kayıp),
"""
TR_TIMEOUT = "İstek zaman aşımına uğradı.\n    Paket: Giden = 1, Gelen = 0, Kaybolan = 1 (%100 kayıp),"
EN_OK = """
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=17ms TTL=118
Reply from 8.8.8.8: bytes=32 time<1ms TTL=118

Ping statistics for 8.8.8.8:
    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 0ms, Maximum = 17ms, Average = 8ms
"""
EN_UNREACHABLE = "Reply from 10.90.0.3: Destination host unreachable.\n    Minimum = 0ms, Maximum = 0ms, Average = 0ms"
LINUX = """PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=118 time=21.3 ms

--- 8.8.8.8 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 21.3/21.3/21.3/0.0 ms
"""


class PingParserTest(unittest.TestCase):
    def test_english(self):
        self.assertEqual(parse_ping_output(EN_OK), [(17.0, 118), (0.5, 118)])

    def test_turkish_sure(self):
        self.assertEqual(parse_ping_output(TR_OK), [(21.0, 118), (0.5, 118)])

    def test_turkish_sub_millisecond(self):
        self.assertEqual(parse_ping_line("8.8.8.8 yanıtı: bayt=32 süre<1ms TTL=118"), (0.5, 118))

    def test_turkish_unreachable_is_lost(self):
        self.assertEqual(parse_ping_output(TR_UNREACHABLE), [])

    def test_turkish_timeout(self):
        self.assertEqual(parse_ping_output(TR_TIMEOUT), [])

    def test_english_unreachable_and_statistics_line(self):
        self.assertEqual(parse_ping_output(EN_UNREACHABLE), [])

    def test_statistics_lines_never_match(self):
        self.assertIsNone(parse_ping_line("    Minimum = 17ms, Maximum = 20ms, Average = 18ms"))
        self.assertIsNone(parse_ping_line("    En Az = 0ms, En Çok = 21ms, Ortalama = 10ms"))

    def test_ttl_expired(self):
        self.assertEqual(parse_ping_output("Reply from 10.0.0.1: TTL expired in transit."), [])
        self.assertEqual(parse_ping_output("10.0.0.1 yanıtı: Aktarımda TTL süresi doldu."), [])

    def test_other_locales(self):
        self.assertEqual(parse_ping_output("Antwort von 8.8.8.8: Bytes=32 Zeit=21ms TTL=118"), [(21.0, 118)])
        self.assertEqual(parse_ping_output("Réponse de 8.8.8.8 : octets=32 temps=21 ms TTL=118"), [(21.0, 118)])
        self.assertEqual(parse_ping_output("Ответ от 8.8.8.8: число байт=32 время=21мс TTL=118"), [(21.0, 118)])

    def test_ipv6_reply_without_ttl(self):
        self.assertEqual(parse_ping_output("Reply from ::1: time<1ms"), [(0.5, None)])

    def test_linux(self):
        self.assertEqual(parse_ping_output(LINUX), [(21.3, 118)])
        self.assertEqual(parse_ping_output("From 10.0.0.1 icmp_seq=1 Destination Host Unreachable"), [])


class TracertParserTest(unittest.TestCase):
    def setUp(self):
        self.tracer = TraceRoute()
        self.tracer.platform = "windows"

    def parse(self, line):
        return self.tracer._parse_line(line)

    def test_english_hop(self):
        self.assertEqual(self.parse("  1    <1 ms     2 ms     3 ms  10.90.0.254"),
                         {"hop": 1, "time": "1.8 ms", "ms": 5.5 / 3, "ip": "10.90.0.254", "status": "ok"})

    def test_english_timeout(self):
        self.assertEqual(self.parse("  2     *        *        *     Request timed out."),
                         {"hop": 2, "time": "*", "ms": None, "ip": "Request timed out", "status": "timeout"})

    def test_turkish_timeout(self):
        self.assertEqual(self.parse("  2     *        *        *     İstek zaman aşımına uğradı."),
                         {"hop": 2, "time": "*", "ms": None, "ip": "Request timed out", "status": "timeout"})

    def test_partial_hop(self):
        hop = self.parse("  4     *       12 ms     *     172.25.34.33")
        self.assertEqual((hop["ip"], hop["ms"], hop["status"]), ("172.25.34.33", 12.0, "ok"))

    def test_english_unreachable_report(self):
        hop = self.parse("  1     *     10.90.0.3  reports: Destination host unreachable.")
        self.assertEqual((hop["ip"], hop["status"]), ("Unreachable (reported by 10.90.0.3)", "timeout"))

    def test_turkish_unreachable_report(self):
        hop = self.parse("  1     *     10.90.0.3  raporları: Hedef ana bilgisayara ulaşılamıyor.")
        self.assertEqual((hop["ip"], hop["status"]), ("Unreachable (reported by 10.90.0.3)", "timeout"))

    def test_localized_unit_and_ipv6(self):
        self.assertEqual(self.parse("  1     2 мс     2 мс     2 мс  10.90.0.254")["ms"], 2.0)
        self.assertEqual(self.parse("  1     1 ms     1 ms     1 ms  2001:db8::1")["ip"], "2001:db8::1")

    def test_headers_and_footers_ignored(self):
        for line in ("En fazla 30 atlamanın üzerinden 1.1.1.1 yolu izleniyor",
                     "Tracing route to 1.1.1.1 over a maximum of 30 hops",
                     "İzleme tamamlandı.", "Trace complete."):
            self.assertIsNone(self.parse(line), line)

    def test_linux(self):
        self.tracer.platform = "linux"
        self.assertEqual(self.parse(" 1  192.168.1.1  1.123 ms")["ms"], 1.123)
        self.assertEqual(self.parse(" 3  *")["status"], "timeout")
        self.assertIsNone(self.parse("traceroute to 8.8.8.8 (8.8.8.8), 30 hops max"))


class ArpHeaderTest(unittest.TestCase):
    def test_headers(self):
        self.assertEqual(ARP_HEADER_RE.match("Interface: 10.90.0.3 --- 0x9").group(1), "10.90.0.3")
        self.assertEqual(ARP_HEADER_RE.match("Arabirim: 10.90.0.3 --- 0x9").group(1), "10.90.0.3")

    def test_column_header_and_rows_ignored(self):
        self.assertIsNone(ARP_HEADER_RE.match("  İnternet Adresi      Fiziksel Adres      Tür"))
        self.assertIsNone(ARP_HEADER_RE.match("  10.90.0.254           00-11-22-33-44-55     dinamik"))


ROUTE6_TR = """===========================================================================
Arabirim Listesi
  9...18 26 49 20 bc a5 ......Intel(R) Wi-Fi 6 AX200 160MHz
===========================================================================

IPv6 Yol Tablosu
===========================================================================
Etkin Yollar:
 Arabirim Ölçüm Ağ Hedefi                Ağ Geçidi
  9    281 ::/0                     fe80::1
  1    331 ::1/128                  On-link
===========================================================================
Kalıcı Yollar:
  0 4294967295 ::/0                     fe80::99
==========================================================================="""

ROUTE6_NONE = """===========================================================================
Interface List
===========================================================================

IPv6 Route Table
===========================================================================
Active Routes:
 If Metric Network Destination      Gateway
  1    331 ::1/128                  On-link
===========================================================================
Persistent Routes:
  None
"""


class RoutePrint6Test(unittest.TestCase):
    def test_turkish_default_route(self):
        with mock.patch.object(health, "_run", return_value=(0, ROUTE6_TR)):
            self.assertEqual(health._windows_ipv6_default_routes(), ["::/0 via fe80::1 if 9 metric 281"])

    def test_no_default_route(self):
        with mock.patch.object(health, "_run", return_value=(0, ROUTE6_NONE)):
            self.assertEqual(health._windows_ipv6_default_routes(), [])


if __name__ == "__main__":
    unittest.main()
