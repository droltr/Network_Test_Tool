"""Windows IP Helper and Winsock API wrappers (ctypes).

Locale-independent replacements for scraping ipconfig / ping / netsh output, whose labels are
translated on non-English Windows ("Default Gateway" is "Varsayılan Ağ Geçidi" on Turkish systems).
Every function returns None when the API is unavailable (other platforms), so callers can fall back.

Structures follow the Windows SDK headers (iptypes.h, ipexport.h, winsock2.h) for both 32- and
64-bit processes; tests/test_winnet.py checks their sizes against the SDK values.
"""
import ctypes
import ntpath
import os
import socket
import struct
import sys
import types

try:
    from ctypes import wintypes
except (ImportError, ValueError):   # older Pythons cannot import wintypes off Windows
    wintypes = types.SimpleNamespace(
        BYTE=ctypes.c_byte, WORD=ctypes.c_ushort, USHORT=ctypes.c_ushort, DWORD=ctypes.c_uint32,
        ULONG=ctypes.c_uint32, INT=ctypes.c_int, BOOL=ctypes.c_int, HANDLE=ctypes.c_void_p, WCHAR=ctypes.c_wchar)

AF_UNSPEC, AF_INET, AF_INET6 = 0, 2, 23
GAA_FLAG_INCLUDE_GATEWAYS = 0x80
ERROR_BUFFER_OVERFLOW = 111
IF_OPER_STATUS_UP = 1
IF_TYPE_LOOPBACK = 24
# Loopback, PROP_VIRTUAL (TAP-Windows, OpenVPN DCO, Wintun) and tunnel interfaces
IF_TYPES_VIRTUAL = (IF_TYPE_LOOPBACK, 53, 131)

# ICMP status codes (ipexport.h)
IP_SUCCESS = 0
IP_PACKET_TOO_BIG = 11009
IP_REQ_TIMED_OUT = 11010
IP_TTL_EXPIRED_TRANSIT = 11013
IP_FLAG_DF = 0x2

IS_64BIT = ctypes.sizeof(ctypes.c_void_p) == 8
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

MAX_ADAPTER_ADDRESS_LENGTH = 8
MAX_DHCPV6_DUID_LENGTH = 130
WSAPROTOCOL_LEN = 255
MAX_PROTOCOL_CHAIN = 7
WSAENOBUFS = 10055


# ---------------------------------------------------------------------------- structures

class _Guid(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8)]


class _SocketAddress(ctypes.Structure):
    """SOCKET_ADDRESS (ws2def.h)."""
    _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", wintypes.INT)]


class _LengthFlags(ctypes.Structure):
    _fields_ = [("Length", wintypes.ULONG), ("Flags", wintypes.DWORD)]


class _AlignedLengthFlags(ctypes.Union):
    """union { ULONGLONG Alignment; struct { ULONG Length; DWORD Flags; }; } at the head of every
    IP_ADAPTER_*_ADDRESS entry (the Flags member is IfIndex in IP_ADAPTER_ADDRESSES)."""
    _anonymous_ = ("s",)
    _fields_ = [("Alignment", ctypes.c_ulonglong), ("s", _LengthFlags)]


class _AddressEntry(ctypes.Structure):
    """IP_ADAPTER_DNS_SERVER_ADDRESS_XP / IP_ADAPTER_GATEWAY_ADDRESS_LH, which is also the head of
    IP_ADAPTER_UNICAST_ADDRESS_LH: walking a list only reads Next and Address."""
    _anonymous_ = ("head",)


_AddressEntry._fields_ = [("head", _AlignedLengthFlags), ("Next", ctypes.POINTER(_AddressEntry)),
                          ("Address", _SocketAddress)]


class _AdapterAddresses(ctypes.Structure):
    """IP_ADAPTER_ADDRESSES_LH (iptypes.h, Vista and later)."""
    _anonymous_ = ("head",)


_AdapterAddresses._fields_ = [
    ("head", _AlignedLengthFlags),               # Length, IfIndex
    ("Next", ctypes.POINTER(_AdapterAddresses)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.POINTER(_AddressEntry)),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.POINTER(_AddressEntry)),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", wintypes.BYTE * MAX_ADAPTER_ADDRESS_LENGTH),
    ("PhysicalAddressLength", wintypes.ULONG),
    ("AdapterFlags", wintypes.ULONG),            # union of Flags and its bit fields
    ("Mtu", wintypes.ULONG),
    ("IfType", wintypes.DWORD),                  # IFTYPE
    ("OperStatus", ctypes.c_int),                # IF_OPER_STATUS
    ("Ipv6IfIndex", wintypes.ULONG),
    ("ZoneIndices", wintypes.ULONG * 16),
    ("FirstPrefix", ctypes.c_void_p),
    ("TransmitLinkSpeed", ctypes.c_uint64),
    ("ReceiveLinkSpeed", ctypes.c_uint64),
    ("FirstWinsServerAddress", ctypes.c_void_p),
    ("FirstGatewayAddress", ctypes.POINTER(_AddressEntry)),
    ("Ipv4Metric", wintypes.ULONG),
    ("Ipv6Metric", wintypes.ULONG),
    ("Luid", ctypes.c_uint64),                   # IF_LUID
    ("Dhcpv4Server", _SocketAddress),
    ("CompartmentId", ctypes.c_uint32),          # NET_IF_COMPARTMENT_ID
    ("NetworkGuid", _Guid),                      # NET_IF_NETWORK_GUID
    ("ConnectionType", ctypes.c_int),            # NET_IF_CONNECTION_TYPE
    ("TunnelType", ctypes.c_int),                # TUNNEL_TYPE
    ("Dhcpv6Server", _SocketAddress),
    ("Dhcpv6ClientDuid", wintypes.BYTE * MAX_DHCPV6_DUID_LENGTH),
    ("Dhcpv6ClientDuidLength", wintypes.ULONG),
    ("Dhcpv6Iaid", wintypes.ULONG),
    ("FirstDnsSuffix", ctypes.c_void_p),
]


class _IpOptionInformation(ctypes.Structure):
    """IP_OPTION_INFORMATION (ipexport.h): the native layout, used inside ICMP_ECHO_REPLY."""
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte),
                ("OptionsSize", ctypes.c_ubyte), ("OptionsData", ctypes.c_void_p)]


class _IpOptionInformation32(ctypes.Structure):
    """IP_OPTION_INFORMATION32: OptionsData is a 32-bit pointer (UCHAR * POINTER_32). IcmpSendEcho
    takes its RequestOptions in this form in a 64-bit process."""
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte),
                ("OptionsSize", ctypes.c_ubyte), ("OptionsData", ctypes.c_uint32)]


# RequestOptions type of IcmpSendEcho for this process (the two are the same size in a 32-bit process)
_RequestOptions = _IpOptionInformation32 if IS_64BIT else _IpOptionInformation


class _IcmpEchoReply(ctypes.Structure):
    """ICMP_ECHO_REPLY (ipexport.h), native layout: IcmpSendEcho fills this one in a 64-bit process
    too (ICMP_ECHO_REPLY32 is only for IcmpSendEcho2 replies parsed by 32-bit code on Win64)."""
    _fields_ = [("Address", wintypes.ULONG), ("Status", wintypes.ULONG), ("RoundTripTime", wintypes.ULONG),
                ("DataSize", wintypes.USHORT), ("Reserved", wintypes.USHORT), ("Data", ctypes.c_void_p),
                ("Options", _IpOptionInformation)]


class _WsaProtocolChain(ctypes.Structure):
    _fields_ = [("ChainLen", wintypes.INT), ("ChainEntries", wintypes.DWORD * MAX_PROTOCOL_CHAIN)]


class _WsaProtocolInfoW(ctypes.Structure):
    """WSAPROTOCOL_INFOW (winsock2.h)."""
    _fields_ = [
        ("dwServiceFlags1", wintypes.DWORD), ("dwServiceFlags2", wintypes.DWORD),
        ("dwServiceFlags3", wintypes.DWORD), ("dwServiceFlags4", wintypes.DWORD),
        ("dwProviderFlags", wintypes.DWORD),
        ("ProviderId", _Guid),
        ("dwCatalogEntryId", wintypes.DWORD),
        ("ProtocolChain", _WsaProtocolChain),
        ("iVersion", wintypes.INT), ("iAddressFamily", wintypes.INT), ("iMaxSockAddr", wintypes.INT),
        ("iMinSockAddr", wintypes.INT), ("iSocketType", wintypes.INT), ("iProtocol", wintypes.INT),
        ("iProtocolMaxOffset", wintypes.INT), ("iNetworkByteOrder", wintypes.INT),
        ("iSecurityScheme", wintypes.INT),
        ("dwMessageSize", wintypes.DWORD), ("dwProviderReserved", wintypes.DWORD),
        ("szProtocol", wintypes.WCHAR * (WSAPROTOCOL_LEN + 1)),
    ]


# ---------------------------------------------------------------------------- libraries

_libraries = {}


def _iphlpapi():
    """iphlpapi.dll with the prototypes of the functions used here, or None."""
    if not sys.platform.startswith('win'):
        return None
    if 'iphlpapi' not in _libraries:
        try:
            lib = ctypes.WinDLL('iphlpapi', use_last_error=True)
        except OSError:
            lib = None
        if lib is not None:
            # ULONG GetAdaptersAddresses(ULONG Family, ULONG Flags, PVOID Reserved,
            #                            PIP_ADAPTER_ADDRESSES AdapterAddresses, PULONG SizePointer)
            lib.GetAdaptersAddresses.restype = wintypes.ULONG
            lib.GetAdaptersAddresses.argtypes = [wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p,
                                                 ctypes.POINTER(wintypes.ULONG)]
            # HANDLE IcmpCreateFile(void)
            lib.IcmpCreateFile.restype = wintypes.HANDLE
            lib.IcmpCreateFile.argtypes = []
            # DWORD IcmpSendEcho(HANDLE IcmpHandle, IPAddr DestinationAddress, LPVOID RequestData,
            #                    WORD RequestSize, PIP_OPTION_INFORMATION RequestOptions, LPVOID ReplyBuffer,
            #                    DWORD ReplySize, DWORD Timeout)
            lib.IcmpSendEcho.restype = wintypes.DWORD
            lib.IcmpSendEcho.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.WORD,
                                         ctypes.POINTER(_RequestOptions), ctypes.c_void_p, wintypes.DWORD,
                                         wintypes.DWORD]
            # BOOL IcmpCloseHandle(HANDLE IcmpHandle)
            lib.IcmpCloseHandle.restype = wintypes.BOOL
            lib.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
        _libraries['iphlpapi'] = lib
    return _libraries['iphlpapi']


def _ws2_32():
    """ws2_32.dll with the WSC catalog functions (the *32 variants exist only in 64-bit Windows), or None."""
    if not sys.platform.startswith('win'):
        return None
    if 'ws2_32' not in _libraries:
        try:
            lib = ctypes.WinDLL('ws2_32')
        except OSError:
            lib = None
        if lib is not None:
            for suffix in ('', '32'):
                try:
                    enum = getattr(lib, 'WSCEnumProtocols' + suffix)
                    path = getattr(lib, 'WSCGetProviderPath' + suffix)
                except AttributeError:
                    continue
                # int WSCEnumProtocols(LPINT lpiProtocols, LPWSAPROTOCOL_INFOW lpProtocolBuffer,
                #                      LPDWORD lpdwBufferLength, LPINT lpErrno)
                enum.restype = wintypes.INT
                enum.argtypes = [ctypes.POINTER(wintypes.INT), ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                 ctypes.POINTER(wintypes.INT)]
                # int WSCGetProviderPath(LPGUID lpProviderId, WCHAR *lpszProviderDllPath,
                #                        LPINT lpProviderDllPathLen, LPINT lpErrno)
                path.restype = wintypes.INT
                path.argtypes = [ctypes.POINTER(_Guid), ctypes.c_wchar_p, ctypes.POINTER(wintypes.INT),
                                 ctypes.POINTER(wintypes.INT)]
        _libraries['ws2_32'] = lib
    return _libraries['ws2_32']


# ---------------------------------------------------------------------------- adapters

def _sockaddr_text(address):
    """Text form of a SOCKET_ADDRESS (IPv4 or IPv6, without zone), or None."""
    if not address.lpSockaddr or address.iSockaddrLength < 8:
        return None
    raw = ctypes.string_at(address.lpSockaddr, address.iSockaddrLength)
    family = struct.unpack_from('<H', raw)[0]
    if family == AF_INET:
        return socket.inet_ntop(socket.AF_INET, raw[4:8])
    if family == AF_INET6 and len(raw) >= 24:
        return socket.inet_ntop(socket.AF_INET6, raw[8:24])
    return None


def _entries(pointer):
    addresses = []
    while pointer:
        text = _sockaddr_text(pointer.contents.Address)
        if text:
            addresses.append(text)
        pointer = pointer.contents.Next
    return addresses


def adapter_addresses():
    """Adapters from GetAdaptersAddresses, lowest IPv4 metric first.

    Each entry: {'name', 'description', 'up', 'if_type', 'ipv4_metric', 'addresses', 'dns', 'gateways'}
    (addresses, dns and gateways are lists of IPv4/IPv6 strings). Returns None if the API is unavailable.
    """
    lib = _iphlpapi()
    if lib is None:
        return None
    size = wintypes.ULONG(16 * 1024)
    for _attempt in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        result = lib.GetAdaptersAddresses(AF_UNSPEC, GAA_FLAG_INCLUDE_GATEWAYS, None, buffer, ctypes.byref(size))
        if result != ERROR_BUFFER_OVERFLOW:
            break
    if result != 0:
        return None
    adapters = []
    pointer = ctypes.cast(buffer, ctypes.POINTER(_AdapterAddresses))
    while pointer:
        item = pointer.contents
        adapters.append({
            'name': item.FriendlyName or '',
            'description': item.Description or '',
            'up': item.OperStatus == IF_OPER_STATUS_UP,
            'if_type': item.IfType,
            'ipv4_metric': item.Ipv4Metric,
            'addresses': _entries(item.FirstUnicastAddress),
            'dns': _entries(item.FirstDnsServerAddress),
            'gateways': _entries(item.FirstGatewayAddress),
        })
        pointer = item.Next
    adapters.sort(key=lambda a: a['ipv4_metric'])
    return adapters


# ---------------------------------------------------------------------------- ICMP

def icmp_echo(address, timeout_ms=1000, size=32, dont_fragment=False, ttl=128):
    """Send one ICMP echo request to an IPv4 address with IcmpSendEcho.

    Returns (status, rtt_ms) where status is an IP_* code (IP_SUCCESS, IP_PACKET_TOO_BIG,
    IP_REQ_TIMED_OUT, IP_TTL_EXPIRED_TRANSIT, ...), or None if the API is unavailable.
    """
    lib = _iphlpapi()
    if lib is None:
        return None
    handle = lib.IcmpCreateFile()
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None
    try:
        # IPAddr is the address in network byte order, read as a native DWORD
        destination = struct.unpack('<I', socket.inet_aton(socket.gethostbyname(address)))[0]
        payload = ctypes.create_string_buffer(b'\x61' * size, size)
        options = _RequestOptions(Ttl=ttl, Flags=IP_FLAG_DF if dont_fragment else 0)
        # One reply, the echoed data, room for an ICMP error message (8 bytes) and the
        # IO_STATUS_BLOCK newer Windows versions also place in the buffer, plus some slack
        reply_size = ctypes.sizeof(_IcmpEchoReply) + size + 8 + 16 + 64
        reply = ctypes.create_string_buffer(reply_size)
        count = lib.IcmpSendEcho(handle, destination, payload, size, ctypes.byref(options), reply, reply_size,
                                 timeout_ms)
        if count:
            echo = _IcmpEchoReply.from_buffer(reply)
            return echo.Status, float(echo.RoundTripTime)
        return ctypes.get_last_error(), None
    finally:
        lib.IcmpCloseHandle(handle)


# ---------------------------------------------------------------------------- Winsock catalog

def _enum_protocols(enum):
    """WSAPROTOCOL_INFOW entries from WSCEnumProtocols(32), or None on failure."""
    length, error = wintypes.DWORD(0), wintypes.INT(0)
    for _attempt in range(3):
        buffer = ctypes.create_string_buffer(max(length.value, 1))
        count = enum(None, buffer, ctypes.byref(length), ctypes.byref(error))
        if count >= 0:
            infos = (_WsaProtocolInfoW * count).from_buffer(buffer) if count else []
            return list(infos)
        if error.value != WSAENOBUFS:
            return None
    return None


def _provider_path(get_path, provider_id):
    length, error = wintypes.INT(260), wintypes.INT(0)
    buffer = ctypes.create_unicode_buffer(length.value)
    if get_path(ctypes.byref(provider_id), buffer, ctypes.byref(length), ctypes.byref(error)) != 0:
        return ''
    return buffer.value


def winsock_providers():
    """Protocol providers of the Winsock catalog (what `netsh winsock show catalog` lists, whose labels
    are translated), from WSCEnumProtocols and WSCGetProviderPath, for the native catalog and on
    64-bit Windows also the 32-bit one.

    Each entry: {'name', 'path' (as registered, e.g. "%SystemRoot%\\system32\\mswsock.dll"),
    'layered' (a layered service provider or a protocol chain through one), 'catalog' (64 or 32)}.
    Returns None if the API is unavailable.
    """
    lib = _ws2_32()
    if lib is None or not hasattr(lib, 'WSCEnumProtocols'):
        return None
    providers = []
    catalogs = [('', 64 if IS_64BIT else 32)]
    if IS_64BIT and hasattr(lib, 'WSCEnumProtocols32'):
        catalogs.append(('32', 32))
    for suffix, bits in catalogs:
        infos = _enum_protocols(getattr(lib, 'WSCEnumProtocols' + suffix))
        if infos is None:
            if not providers and suffix == '':
                return None
            continue
        get_path = getattr(lib, 'WSCGetProviderPath' + suffix)
        for info in infos:
            providers.append({
                'name': info.szProtocol,
                'path': _provider_path(get_path, info.ProviderId),
                # ChainLen 1 is a base provider; 0 is a layered provider itself, >1 a chain through one
                'layered': info.ProtocolChain.ChainLen != 1,
                'catalog': bits,
            })
    return providers


def is_windows_provider_path(path, system_root=None):
    """True for a provider DLL directly in the Windows system directories (System32, SysWOW64).
    Uses Windows path rules on every platform, so it can be tested anywhere."""
    root = system_root or os.environ.get('SystemRoot') or os.environ.get('windir') or r'C:\Windows'
    text = path or ''
    for variable in ('%systemroot%', '%windir%'):
        if text.lower().startswith(variable):
            text = root + text[len(variable):]
    text = ntpath.normcase(ntpath.normpath(text))
    return any(ntpath.dirname(text) == ntpath.normcase(ntpath.join(root, folder))
               for folder in ('system32', 'syswow64'))
