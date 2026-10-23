"""utils.winnet: structure layouts against the Windows SDK and the Winsock provider classification."""
import ctypes
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network import health  # noqa: E402
from utils import winnet  # noqa: E402

IS_WINDOWS = sys.platform.startswith("win")


@unittest.skipUnless(IS_WINDOWS and winnet.IS_64BIT, "SDK sizes below are for 64-bit Windows")
class StructLayout64Test(unittest.TestCase):
    """sizeof / offsetof values of the x64 Windows SDK headers."""

    def test_sizes(self):
        expected = {
            "_SocketAddress": 16,             # SOCKET_ADDRESS
            "_AddressEntry": 32,              # IP_ADAPTER_GATEWAY_ADDRESS_LH / DNS_SERVER_ADDRESS_XP
            "_AdapterAddresses": 448,         # IP_ADAPTER_ADDRESSES_LH
            "_IpOptionInformation": 16,       # IP_OPTION_INFORMATION
            "_IpOptionInformation32": 8,      # IP_OPTION_INFORMATION32
            "_IcmpEchoReply": 40,             # ICMP_ECHO_REPLY
            "_WsaProtocolInfoW": 628,         # WSAPROTOCOL_INFOW
        }
        for name, size in expected.items():
            with self.subTest(name=name):
                self.assertEqual(ctypes.sizeof(getattr(winnet, name)), size)

    def test_adapter_offsets(self):
        offsets = {"Next": 8, "AdapterName": 16, "FirstDnsServerAddress": 48, "Description": 64,
                   "FriendlyName": 72, "OperStatus": 104, "FirstGatewayAddress": 208, "Ipv4Metric": 216,
                   "Luid": 224, "Dhcpv6Server": 280, "FirstDnsSuffix": 440}
        for name, offset in offsets.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(winnet._AdapterAddresses, name).offset, offset)

    def test_request_options_are_32bit_form(self):
        self.assertIs(winnet._RequestOptions, winnet._IpOptionInformation32)
        self.assertEqual(winnet._IcmpEchoReply.Options.offset, 24)


@unittest.skipUnless(IS_WINDOWS, "Windows API")
class PrototypesTest(unittest.TestCase):
    def test_declared(self):
        lib = winnet._iphlpapi()
        for name in ("GetAdaptersAddresses", "IcmpCreateFile", "IcmpSendEcho", "IcmpCloseHandle"):
            with self.subTest(name=name):
                self.assertIsNotNone(getattr(lib, name).argtypes)
                self.assertIsNotNone(getattr(lib, name).restype)

    def test_winsock_catalog_readable(self):
        providers = winnet.winsock_providers()
        self.assertTrue(providers)
        self.assertTrue(all(p["path"] for p in providers))


class ProviderPathTest(unittest.TestCase):
    ROOT = r"C:\Windows"

    def test_windows_paths(self):
        for path in (r"%SystemRoot%\system32\mswsock.dll", r"%windir%\SysWOW64\mswsock.dll",
                     r"C:\WINDOWS\System32\mswsock.dll"):
            with self.subTest(path=path):
                self.assertTrue(winnet.is_windows_provider_path(path, self.ROOT))

    def test_other_paths(self):
        for path in (r"C:\Program Files\Vendor\lsp.dll", r"%SystemRoot%\system32\drivers\x.dll",
                     r"%SystemRoot%\system32\..\Temp\x.dll", r"D:\Windows\system32\x.dll", "", None):
            with self.subTest(path=path):
                self.assertFalse(winnet.is_windows_provider_path(path, self.ROOT))


class WinsockCheckTest(unittest.TestCase):
    MS = {"name": "MSAFD Tcpip [TCP/IP]", "path": r"%SystemRoot%\system32\mswsock.dll", "layered": False,
          "catalog": 64}

    def run_check(self, providers):
        with mock.patch.object(health, "PLATFORM", "windows"), \
                mock.patch.object(health.winnet, "winsock_providers", return_value=providers), \
                mock.patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}):
            return health.check_windows_winsock()

    def test_only_microsoft(self):
        self.assertEqual(self.run_check([self.MS, {**self.MS, "catalog": 32}])["status"], "ok")

    def test_third_party_dll(self):
        result = self.run_check([self.MS, {"name": "Vendor LSP", "path": r"C:\Program Files\Vendor\vlsp.dll",
                                           "layered": False, "catalog": 64}])
        self.assertEqual(result["status"], "warn")
        self.assertIn("vlsp.dll", result["details"][0])

    def test_layered_provider_in_system32(self):
        result = self.run_check([self.MS, {**self.MS, "name": "Old LSP", "path": r"%SystemRoot%\system32\olsp.dll",
                                           "layered": True}])
        self.assertEqual(result["status"], "warn")

    def test_unreadable_catalog(self):
        self.assertEqual(self.run_check(None)["status"], "info")


if __name__ == "__main__":
    unittest.main()
