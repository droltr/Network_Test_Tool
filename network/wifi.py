"""Wi-Fi link diagnostics: the current connection (SSID, access point, signal, channel, band, PHY
rates), nearby access points from the cached scan list, channel congestion, and a tracker that turns
a series of samples into events (roams, disconnects, signal and rate drops).

Data sources, all read-only (nothing here connects, disconnects, triggers a scan or changes a
setting; nearby networks come only from the scan results the system already has):
- Windows: the Native Wifi API (wlanapi.dll) through ctypes: WlanEnumInterfaces, WlanQueryInterface
  (current connection, channel, RSSI) and WlanGetNetworkBssList (BSSID, RSSI and center frequency of
  the current and nearby access points). It is locale independent, unlike `netsh wlan show
  interfaces`, whose labels are translated ("Sinyal", "Kanal" on Turkish systems). The netsh parser
  is only a fallback for when wlanapi.dll cannot be loaded; it finds most fields by the shape of
  their values, and the rest by a short list of translated labels (best effort).
- Linux: `nmcli -t` (NetworkManager, cached list with --rescan no) for the connection and nearby
  networks, `iw dev <if> link` for RSSI and bit rates, and `iw dev <if> scan dump` (cached results,
  no root needed) when nmcli is missing.
- macOS: `system_profiler SPAirPortDataType -json`, best effort.

Windows 11 24H2 and later deny Wi-Fi details to desktop apps without the Location permission:
WlanQueryInterface/WlanGetNetworkBssList return ERROR_ACCESS_DENIED, or the connection comes back
with an empty SSID and BSSID. wifi_status() then reports reason "location_permission" with a hint
for the user instead of "disconnected".

Signal: Windows reports a 0-100 % link quality mapped linearly from -100 dBm (0 %) to -50 dBm
(100 %); percent_to_dbm()/dbm_to_percent() convert with the same mapping.

The Linux and macOS readers are checked against sample command output. To compare, run
wifi_status() next to `nmcli dev wifi` / `iw dev <if> link` on Linux and the Wi-Fi menu
(Option-click) on macOS.
"""
import ctypes
import json
import os
import re
import shutil
import statistics
import sys
import types
from datetime import datetime

from utils.paths import run_command

try:
    from ctypes import wintypes
except (ImportError, ValueError):   # older Pythons cannot import wintypes off Windows
    wintypes = types.SimpleNamespace(
        BYTE=ctypes.c_byte, WORD=ctypes.c_ushort, USHORT=ctypes.c_ushort, DWORD=ctypes.c_uint32,
        ULONG=ctypes.c_uint32, LONG=ctypes.c_int32, INT=ctypes.c_int, BOOL=ctypes.c_int,
        BOOLEAN=ctypes.c_ubyte, HANDLE=ctypes.c_void_p, WCHAR=ctypes.c_wchar)

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

WEAK_DBM = -70                 # below this, calls and video start to suffer
LOCATION_MESSAGE = ("Windows is blocking Wi-Fi details because location access is off. Turn on "
                    "Settings > Privacy & security > Location > 'Let desktop apps access your location' "
                    "and try again.")
STATUS_KEYS = ("available", "reason", "message", "interface", "ssid", "bssid", "signal_percent", "rssi_dbm",
               "band", "channel", "frequency_mhz", "radio_type", "rx_rate_mbps", "tx_rate_mbps", "auth",
               "connected")

# Win32 error codes
ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5
ERROR_SERVICE_NOT_ACTIVE = 1062
ERROR_NOT_FOUND = 1168
ERROR_INVALID_STATE = 5023

# wlanapi.h / windot11.h enumerations
WLAN_CLIENT_VERSION_2 = 2
WLAN_INTERFACE_STATE_CONNECTED = 1
OPCODE_CURRENT_CONNECTION = 7      # wlan_intf_opcode_current_connection
OPCODE_CHANNEL_NUMBER = 8          # wlan_intf_opcode_channel_number
OPCODE_RSSI = 0x10000102           # wlan_intf_opcode_rssi
DOT11_BSS_TYPE_ANY = 3
PHY_TYPES = {1: "FHSS", 2: "802.11", 4: "802.11a", 5: "802.11b", 6: "802.11g", 7: "802.11n", 8: "802.11ac",
             9: "802.11ad", 10: "802.11ax", 11: "802.11be"}
AUTH_ALGORITHMS = {1: "Open", 2: "Shared key", 3: "WPA-Enterprise", 4: "WPA-Personal", 5: "WPA-None",
                   6: "WPA2-Enterprise", 7: "WPA2-Personal", 8: "WPA3-Enterprise 192-bit", 9: "WPA3-Personal",
                   10: "OWE", 11: "WPA3-Enterprise"}


# ---------------------------------------------------------------------------- conversions

def percent_to_dbm(percent):
    """Windows link quality (0-100 %) to dBm: 0 % = -100 dBm, 100 % = -50 dBm, linear."""
    if percent is None:
        return None
    percent = max(0, min(100, int(round(percent))))
    return int(round(percent / 2 - 100))


def dbm_to_percent(dbm):
    """dBm to the Windows 0-100 % scale (inverse of percent_to_dbm, clamped)."""
    if dbm is None:
        return None
    return max(0, min(100, int(round(2 * (dbm + 100)))))


def channel_from_frequency(mhz):
    """802.11 channel number of a center frequency in MHz (2.4, 5 and 6 GHz bands), or None."""
    if not mhz:
        return None
    mhz = int(round(mhz))
    if mhz == 2484:
        return 14
    if 2407 < mhz < 2484:
        return (mhz - 2407) // 5
    if 4900 <= mhz < 5925:
        return (mhz - 5000) // 5 if mhz >= 5000 else (mhz - 4000) // 5
    if mhz == 5935:
        return 2
    if 5950 < mhz <= 7125:
        return (mhz - 5950) // 5
    return None


def band_from_frequency(mhz):
    """"2.4 GHz", "5 GHz" or "6 GHz" for a frequency in MHz, or None."""
    if not mhz:
        return None
    if 2400 <= mhz < 2500:
        return "2.4 GHz"
    if 4900 <= mhz < 5925:
        return "5 GHz"
    if 5925 <= mhz <= 7125:
        return "6 GHz"
    return None


def _band_from_channel(channel):
    """Best guess when only a channel number is known (6 GHz channels overlap both ranges)."""
    if not channel:
        return None
    if channel <= 14:
        return "2.4 GHz"
    if 32 <= channel <= 177:
        return "5 GHz"
    return None


def _band_text(text):
    """Normalize '5 GHz', '5GHz', '2.4 GHz', '2,4 GHz' to the band names used here."""
    match = re.search(r"(2[.,]4|5|6)\s*GHz", text or "", re.IGNORECASE)
    if not match:
        return None
    return {"2,4": "2.4 GHz", "2.4": "2.4 GHz", "5": "5 GHz", "6": "6 GHz"}[match.group(1)]


def _mac(raw):
    """Lower-case colon form of a MAC address given as bytes or text, or None."""
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        text = ":".join(f"{b:02x}" for b in raw)
    else:
        parts = re.split(r"[:\-]", str(raw).strip().replace("\\:", ":"))
        if len(parts) != 6 or not all(re.fullmatch(r"[0-9A-Fa-f]{1,2}", p) for p in parts):
            return None
        text = ":".join(p.lower().zfill(2) for p in parts)
    return None if text == "00:00:00:00:00:00" else text


def _number(text, kind=float):
    match = re.search(r"-?\d+(?:[.,]\d+)?", text or "")
    if not match:
        return None
    try:
        return kind(float(match.group(0).replace(",", ".")))
    except ValueError:
        return None


def _empty_status(reason=None, message="", interface=""):
    status = {key: None for key in STATUS_KEYS}
    status.update(available=False, reason=reason, message=message, interface=interface or "", connected=False)
    return status


def _finish(status):
    """Fill the fields that can be derived from others (dBm <-> %, channel <-> frequency, band)."""
    if status.get("rssi_dbm") is None and status.get("signal_percent") is not None:
        status["rssi_dbm"] = percent_to_dbm(status["signal_percent"])
    if status.get("signal_percent") is None and status.get("rssi_dbm") is not None:
        status["signal_percent"] = dbm_to_percent(status["rssi_dbm"])
    freq = status.get("frequency_mhz")
    if status.get("channel") is None and freq:
        status["channel"] = channel_from_frequency(freq)
    if status.get("band") is None:
        status["band"] = band_from_frequency(freq) if freq else _band_from_channel(status.get("channel"))
    return status


def _network(ssid=None, bssid=None, signal_percent=None, rssi_dbm=None, channel=None, band=None,
             frequency_mhz=None):
    net = {"ssid": ssid, "bssid": bssid, "signal_percent": signal_percent, "rssi_dbm": rssi_dbm,
           "channel": channel, "band": band, "frequency_mhz": frequency_mhz}
    return _finish(net)


# ---------------------------------------------------------------------------- Windows: wlanapi

class _Guid(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class _Dot11Ssid(ctypes.Structure):
    """DOT11_SSID (windot11.h)."""
    _fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_ubyte * 32)]


class _WlanInterfaceInfo(ctypes.Structure):
    """WLAN_INTERFACE_INFO (wlanapi.h)."""
    _fields_ = [("InterfaceGuid", _Guid), ("strInterfaceDescription", ctypes.c_wchar * 256),
                ("isState", ctypes.c_int)]


class _WlanInterfaceInfoList(ctypes.Structure):
    """WLAN_INTERFACE_INFO_LIST header; the InterfaceInfo array follows at offset 8."""
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD)]


class _WlanAssociationAttributes(ctypes.Structure):
    """WLAN_ASSOCIATION_ATTRIBUTES (wlanapi.h). Rates are in kbit/s."""
    _fields_ = [("dot11Ssid", _Dot11Ssid), ("dot11BssType", ctypes.c_int), ("dot11Bssid", ctypes.c_ubyte * 6),
                ("dot11PhyType", ctypes.c_int), ("uDot11PhyIndex", wintypes.ULONG),
                ("wlanSignalQuality", wintypes.ULONG), ("ulRxRate", wintypes.ULONG), ("ulTxRate", wintypes.ULONG)]


class _WlanSecurityAttributes(ctypes.Structure):
    """WLAN_SECURITY_ATTRIBUTES (wlanapi.h)."""
    _fields_ = [("bSecurityEnabled", ctypes.c_int), ("bOneXEnabled", ctypes.c_int),
                ("dot11AuthAlgorithm", ctypes.c_int), ("dot11CipherAlgorithm", ctypes.c_int)]


class _WlanConnectionAttributes(ctypes.Structure):
    """WLAN_CONNECTION_ATTRIBUTES (wlanapi.h)."""
    _fields_ = [("isState", ctypes.c_int), ("wlanConnectionMode", ctypes.c_int),
                ("strProfileName", ctypes.c_wchar * 256),
                ("wlanAssociationAttributes", _WlanAssociationAttributes),
                ("wlanSecurityAttributes", _WlanSecurityAttributes)]


class _WlanRateSet(ctypes.Structure):
    _fields_ = [("uRateSetLength", wintypes.ULONG), ("usRateSet", ctypes.c_ushort * 126)]


class _WlanBssEntry(ctypes.Structure):
    """WLAN_BSS_ENTRY (wlanapi.h). ulChCenterFrequency is in kHz."""
    _fields_ = [("dot11Ssid", _Dot11Ssid), ("uPhyId", wintypes.ULONG), ("dot11Bssid", ctypes.c_ubyte * 6),
                ("dot11BssType", ctypes.c_int), ("dot11BssPhyType", ctypes.c_int), ("lRssi", ctypes.c_int32),
                ("uLinkQuality", wintypes.ULONG), ("bInRegDomain", ctypes.c_ubyte),
                ("usBeaconPeriod", ctypes.c_ushort), ("ullTimestamp", ctypes.c_ulonglong),
                ("ullHostTimestamp", ctypes.c_ulonglong), ("usCapabilityInformation", ctypes.c_ushort),
                ("ulChCenterFrequency", wintypes.ULONG), ("wlanRateSet", _WlanRateSet),
                ("ulIeOffset", wintypes.ULONG), ("ulIeSize", wintypes.ULONG)]


class _WlanBssListHeader(ctypes.Structure):
    """WLAN_BSS_LIST header; the wlanBssEntries array follows at offset 8."""
    _fields_ = [("dwTotalSize", wintypes.DWORD), ("dwNumberOfItems", wintypes.DWORD)]


_wlan_lib = {}


def _wlanapi():
    """wlanapi.dll with prototypes, or None (other platforms, Windows Server without the WLAN feature)."""
    if not IS_WINDOWS:
        return None
    if "lib" not in _wlan_lib:
        try:
            lib = ctypes.WinDLL("wlanapi", use_last_error=True)
        except OSError:
            lib = None
        if lib is not None:
            pvoid = ctypes.c_void_p
            lib.WlanOpenHandle.restype = wintypes.DWORD
            lib.WlanOpenHandle.argtypes = [wintypes.DWORD, pvoid, ctypes.POINTER(wintypes.DWORD),
                                           ctypes.POINTER(wintypes.HANDLE)]
            lib.WlanCloseHandle.restype = wintypes.DWORD
            lib.WlanCloseHandle.argtypes = [wintypes.HANDLE, pvoid]
            lib.WlanEnumInterfaces.restype = wintypes.DWORD
            lib.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, pvoid, ctypes.POINTER(pvoid)]
            lib.WlanQueryInterface.restype = wintypes.DWORD
            lib.WlanQueryInterface.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Guid), ctypes.c_int, pvoid,
                                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(pvoid),
                                               ctypes.POINTER(ctypes.c_int)]
            lib.WlanGetNetworkBssList.restype = wintypes.DWORD
            lib.WlanGetNetworkBssList.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Guid), pvoid, ctypes.c_int,
                                                  ctypes.c_int, pvoid, ctypes.POINTER(pvoid)]
            lib.WlanFreeMemory.restype = None
            lib.WlanFreeMemory.argtypes = [pvoid]
        _wlan_lib["lib"] = lib
    return _wlan_lib["lib"]


def _ssid_text(dot11_ssid):
    length = min(int(dot11_ssid.uSSIDLength), 32)
    return bytes(dot11_ssid.ucSSID[:length]).decode("utf-8", errors="replace")


def _guid_alias(guid):
    """Friendly interface name ("Wi-Fi") of an interface GUID via iphlpapi, or None."""
    try:
        iphlp = ctypes.WinDLL("iphlpapi")
        luid = ctypes.c_uint64()
        if iphlp.ConvertInterfaceGuidToLuid(ctypes.byref(guid), ctypes.byref(luid)) != 0:
            return None
        alias = ctypes.create_unicode_buffer(257)
        if iphlp.ConvertInterfaceLuidToAlias(ctypes.byref(luid), alias, len(alias)) != 0:
            return None
        return alias.value or None
    except (OSError, AttributeError):
        return None


def _query(lib, handle, guid, opcode):
    """WlanQueryInterface: (error code, pointer); the caller frees the pointer with WlanFreeMemory."""
    size = wintypes.DWORD()
    data = ctypes.c_void_p()
    value_type = ctypes.c_int()
    error = lib.WlanQueryInterface(handle, ctypes.byref(guid), opcode, None, ctypes.byref(size),
                                   ctypes.byref(data), ctypes.byref(value_type))
    return error, data


def _query_scalar(lib, handle, guid, opcode, ctype):
    error, data = _query(lib, handle, guid, opcode)
    if error != ERROR_SUCCESS or not data.value:
        return None
    try:
        return ctypes.cast(data, ctypes.POINTER(ctype)).contents.value
    finally:
        lib.WlanFreeMemory(data)


def _bss_list(lib, handle, guid):
    """(error code, list of plain dicts) from WlanGetNetworkBssList (cached scan results only)."""
    data = ctypes.c_void_p()
    error = lib.WlanGetNetworkBssList(handle, ctypes.byref(guid), None, DOT11_BSS_TYPE_ANY, 0, None,
                                      ctypes.byref(data))
    if error != ERROR_SUCCESS or not data.value:
        return error, []
    try:
        header = ctypes.cast(data, ctypes.POINTER(_WlanBssListHeader)).contents
        count = int(header.dwNumberOfItems)
        entries = (_WlanBssEntry * count).from_address(data.value + ctypes.sizeof(_WlanBssListHeader))
        result = [{"ssid": _ssid_text(e.dot11Ssid), "bssid": _mac(bytes(e.dot11Bssid)), "rssi_dbm": int(e.lRssi),
                   "link_quality": int(e.uLinkQuality), "frequency_mhz": int(e.ulChCenterFrequency) // 1000,
                   "phy": int(e.dot11BssPhyType)} for e in entries]
    finally:
        lib.WlanFreeMemory(data)
    return ERROR_SUCCESS, result


def _windows_raw():
    """Everything the Native Wifi API says about the WLAN interfaces, as plain data:
    {'error': code} or {'error': 0, 'interfaces': [{'name', 'description', 'state', 'conn_error',
    'conn': {...} | None, 'channel', 'rssi', 'bss_error', 'bss': [...]}, ...]}.
    Returns None when wlanapi.dll is unavailable."""
    lib = _wlanapi()
    if lib is None:
        return None
    handle = wintypes.HANDLE()
    version = wintypes.DWORD()
    error = lib.WlanOpenHandle(WLAN_CLIENT_VERSION_2, None, ctypes.byref(version), ctypes.byref(handle))
    if error != ERROR_SUCCESS:
        return {"error": error}
    try:
        info_ptr = ctypes.c_void_p()
        error = lib.WlanEnumInterfaces(handle, None, ctypes.byref(info_ptr))
        if error != ERROR_SUCCESS:
            return {"error": error}
        try:
            count = ctypes.cast(info_ptr, ctypes.POINTER(_WlanInterfaceInfoList)).contents.dwNumberOfItems
            infos = (_WlanInterfaceInfo * count).from_address(info_ptr.value + 8)
            guids = [(_Guid.from_buffer_copy(i.InterfaceGuid), i.strInterfaceDescription, int(i.isState))
                     for i in infos]
        finally:
            lib.WlanFreeMemory(info_ptr)
        interfaces = []
        for guid, description, state in guids:
            item = {"name": _guid_alias(guid) or description, "description": description, "state": state,
                    "conn_error": None, "conn": None, "channel": None, "rssi": None, "bss_error": None, "bss": []}
            conn_error, data = _query(lib, handle, guid, OPCODE_CURRENT_CONNECTION)
            item["conn_error"] = conn_error
            if conn_error == ERROR_SUCCESS and data.value:
                try:
                    attrs = ctypes.cast(data, ctypes.POINTER(_WlanConnectionAttributes)).contents
                    assoc, sec = attrs.wlanAssociationAttributes, attrs.wlanSecurityAttributes
                    item["conn"] = {"state": int(attrs.isState), "profile": attrs.strProfileName,
                                    "ssid": _ssid_text(assoc.dot11Ssid), "bssid": _mac(bytes(assoc.dot11Bssid)),
                                    "phy": int(assoc.dot11PhyType), "quality": int(assoc.wlanSignalQuality),
                                    "rx_kbps": int(assoc.ulRxRate), "tx_kbps": int(assoc.ulTxRate),
                                    "auth": int(sec.dot11AuthAlgorithm)}
                finally:
                    lib.WlanFreeMemory(data)
            if state == WLAN_INTERFACE_STATE_CONNECTED:
                # Channel and RSSI stay readable when the Location privacy block hides the connection
                item["channel"] = _query_scalar(lib, handle, guid, OPCODE_CHANNEL_NUMBER, wintypes.ULONG)
                item["rssi"] = _query_scalar(lib, handle, guid, OPCODE_RSSI, ctypes.c_int32)
            item["bss_error"], item["bss"] = _bss_list(lib, handle, guid)
            interfaces.append(item)
        return {"error": ERROR_SUCCESS, "interfaces": interfaces}
    finally:
        lib.WlanCloseHandle(handle, None)


def _windows_status_from_raw(raw):
    """Build the wifi_status() dict from _windows_raw() data (pure; tested offline)."""
    error = raw.get("error")
    if error == ERROR_SERVICE_NOT_ACTIVE:
        return _empty_status("no_wifi", "No Wi-Fi adapter (the WLAN AutoConfig service is not running).")
    if error == ERROR_ACCESS_DENIED:
        return _empty_status("location_permission", LOCATION_MESSAGE)
    if error:
        return _empty_status("error", f"The Windows Wi-Fi API failed (error {error}).")
    interfaces = raw.get("interfaces") or []
    if not interfaces:
        return _empty_status("no_wifi", "No Wi-Fi adapter found. The computer may be on Ethernet only.")
    # Prefer an interface that reports a connection
    iface = next((i for i in interfaces if i.get("state") == WLAN_INTERFACE_STATE_CONNECTED), interfaces[0])
    name = iface.get("name") or iface.get("description") or ""
    connected = iface.get("state") == WLAN_INTERFACE_STATE_CONNECTED
    conn = iface.get("conn")
    rssi = iface.get("rssi")
    rssi = int(rssi) if rssi is not None and -120 < rssi < 0 else None
    blocked = (iface.get("conn_error") == ERROR_ACCESS_DENIED
               or (connected and conn and not conn.get("ssid") and not conn.get("bssid"))
               or (not conn and iface.get("bss_error") == ERROR_ACCESS_DENIED))
    if blocked:
        # Windows hides the network identity (Location privacy block). Signal and channel are still
        # readable while connected, so they are kept: the link can be monitored without the SSID.
        status = _empty_status("location_permission", LOCATION_MESSAGE, name)
        if connected:
            status.update(connected=True, rssi_dbm=rssi, channel=iface.get("channel") or None)
            _finish(status)
            if status["rssi_dbm"] is not None:
                status["message"] += " Signal strength and channel are still shown."
        return status
    if not connected or not conn:
        return _empty_status("disconnected", "The Wi-Fi adapter is not connected to a network.", name)
    status = _empty_status(None, "", name)
    status.update(available=True, connected=True, ssid=conn.get("ssid") or None, bssid=conn.get("bssid"),
                  signal_percent=conn.get("quality"), radio_type=PHY_TYPES.get(conn.get("phy")),
                  rx_rate_mbps=round(conn["rx_kbps"] / 1000, 1) if conn.get("rx_kbps") else None,
                  tx_rate_mbps=round(conn["tx_kbps"] / 1000, 1) if conn.get("tx_kbps") else None,
                  auth=AUTH_ALGORITHMS.get(conn.get("auth")), channel=iface.get("channel") or None)
    status["rssi_dbm"] = rssi
    entry = next((b for b in iface.get("bss") or [] if b.get("bssid") and b["bssid"] == status["bssid"]), None)
    if entry:
        status["frequency_mhz"] = entry.get("frequency_mhz") or None
        if status["rssi_dbm"] is None and entry.get("rssi_dbm"):
            status["rssi_dbm"] = entry["rssi_dbm"]
    _finish(status)
    status["message"] = _status_message(status)
    return status


def _windows_networks_from_raw(raw):
    networks, seen = [], set()
    for iface in (raw or {}).get("interfaces") or []:
        for b in iface.get("bss") or []:
            if not b.get("bssid") or b["bssid"] in seen:
                continue
            seen.add(b["bssid"])
            networks.append(_network(ssid=b.get("ssid") or None, bssid=b["bssid"],
                                     signal_percent=b.get("link_quality"), rssi_dbm=b.get("rssi_dbm"),
                                     frequency_mhz=b.get("frequency_mhz") or None))
    return networks


# ---------------------------------------------------------------------------- Windows: netsh fallback

_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}$")
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
# Translated "Channel" and "Authentication" labels (en, tr, de, fr, es, it, pt, nl, pl, ru)
_CHANNEL_LABELS = ("channel", "kanal", "canal", "canale", "kanaal", "канал")
_AUTH_LABELS = ("authentication", "kimlik doğrulama", "authentifizierung", "authentification", "autenticación",
                "autenticazione", "autenticação", "verificatie", "uwierzytelnianie", "проверка подлинности")


def parse_netsh_interfaces(text):
    """Parse `netsh wlan show interfaces` output into a wifi_status()-shaped dict (best effort).

    Labels are translated on non-English Windows, so fields are found by the shape of their values
    where possible: the second MAC address is the BSSID (the first is the adapter's own address),
    'NN%' is the signal, '802.11..' the radio type, the two '(Mbps)' lines are receive then transmit
    rate, 'x GHz' the band. SSID keeps its untranslated label; channel and authentication use a short
    list of translations. Only the first interface that has a BSSID (or else the first one) is used.
    """
    blocks, current, first_label = [], None, None
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label, value = label.strip(), value.strip()
        if not label or label.startswith("There ") or "\t" in label:
            continue
        if first_label is None:
            if not value:
                continue         # a header such as "Sistemde 1 arabirim var:"
            first_label = label
        if label == first_label:
            current = []
            blocks.append(current)
        if current is not None:
            current.append((label, value))
    if not blocks:
        return _empty_status("no_wifi", "No Wi-Fi adapter found. The computer may be on Ethernet only.")
    parsed = [_parse_netsh_block(b) for b in blocks]
    status = next((p for p in parsed if p["bssid"]), parsed[0])
    return status


def _parse_netsh_block(pairs):
    status = _empty_status(None, "", pairs[0][1] if pairs else "")
    macs, rates = [], []
    for label, value in pairs:
        low = label.lower()
        if _MAC_RE.match(value):
            macs.append(_mac(value))
        elif label == "SSID":
            status["ssid"] = value or None
        elif re.fullmatch(r"\d{1,3}\s*%", value):
            status["signal_percent"] = int(value.rstrip("% "))
        elif re.match(r"802\.11\w*$", value):
            status["radio_type"] = value
        elif "(mbps)" in low or "(мбит/с)" in low:
            rates.append(_number(value))
        elif re.fullmatch(r"\d(?:[.,]\d)?\s*GHz", value, re.IGNORECASE):
            status["band"] = _band_text(value)
        elif any(low == c or low.startswith(c + " ") for c in _CHANNEL_LABELS) and value.isdigit():
            status["channel"] = int(value)
        elif low in _AUTH_LABELS:
            status["auth"] = value or None
        elif value and re.fullmatch(r"-\d{2,3}\s*dBm", value):
            status["rssi_dbm"] = int(_number(value))
    status["bssid"] = macs[1] if len(macs) > 1 else None
    if rates:
        status["rx_rate_mbps"] = rates[0]
    if len(rates) > 1:
        status["tx_rate_mbps"] = rates[1]
    if status["bssid"] or status["ssid"]:
        status.update(available=True, connected=True)
        _finish(status)
        status["message"] = _status_message(status)
    else:
        status.update(reason="disconnected", message="The Wi-Fi adapter is not connected to a network.")
    return status


def _netsh_status():
    try:
        result = run_command(["netsh", "wlan", "show", "interfaces"], timeout=10)
    except (OSError, ValueError) as exc:
        return _empty_status("error", f"netsh failed: {exc}")
    text = (result.stdout or "") + (result.stderr or "")
    if re.search(r"location|konum", text, re.IGNORECASE) and "SSID" not in text:
        return _empty_status("location_permission", LOCATION_MESSAGE)
    return parse_netsh_interfaces(result.stdout)


# ---------------------------------------------------------------------------- Linux

def _split_terse(line):
    """Split one `nmcli -t` line on ':' honoring the '\\:' and '\\\\' escapes."""
    fields, buf, escape = [], [], False
    for char in line:
        if escape:
            buf.append(char)
            escape = False
        elif char == "\\":
            escape = True
        elif char == ":":
            fields.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    fields.append("".join(buf))
    return fields


NMCLI_FIELDS = ("ACTIVE", "SSID", "BSSID", "CHAN", "FREQ", "RATE", "SIGNAL", "SECURITY", "DEVICE")


def parse_nmcli_wifi(text):
    """Parse `nmcli -t -f ACTIVE,SSID,BSSID,CHAN,FREQ,RATE,SIGNAL,SECURITY,DEVICE dev wifi list` output.

    Returns a list of network dicts with the nearby_networks() keys plus 'active' (bool), 'rate_mbps',
    'security' and 'device'. Malformed lines are skipped. NetworkManager's SIGNAL is its own 0-100
    scale; rssi_dbm is estimated from it with the Windows mapping.
    """
    networks = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        fields = _split_terse(line)
        if len(fields) != len(NMCLI_FIELDS):
            continue
        row = dict(zip(NMCLI_FIELDS, fields))
        bssid = _mac(row["BSSID"])
        if not bssid:
            continue
        freq = _number(row["FREQ"], int)
        signal = _number(row["SIGNAL"], int)
        net = _network(ssid=row["SSID"] or None, bssid=bssid, signal_percent=signal,
                       channel=_number(row["CHAN"], int), frequency_mhz=freq)
        net.update(active=row["ACTIVE"].strip().lower() in ("yes", "*"), rate_mbps=_number(row["RATE"]),
                   security=row["SECURITY"].strip() or None, device=row["DEVICE"].strip() or None)
        networks.append(net)
    return networks


def parse_iw_link(text):
    """Parse `iw dev <if> link` output: {'connected', 'bssid', 'ssid', 'frequency_mhz', 'rssi_dbm',
    'rx_rate_mbps', 'tx_rate_mbps', 'radio_type'} (missing values are None)."""
    info = {"connected": False, "bssid": None, "ssid": None, "frequency_mhz": None, "rssi_dbm": None,
            "rx_rate_mbps": None, "tx_rate_mbps": None, "radio_type": None}
    text = text or ""
    match = re.search(r"Connected to\s+([0-9a-fA-F:]{17})", text)
    if not match:
        return info
    info["connected"] = True
    info["bssid"] = _mac(match.group(1))
    for line in text.splitlines():
        label, _, value = line.strip().partition(":")
        label, value = label.strip().lower(), value.strip()
        if label == "ssid":
            info["ssid"] = value or None
        elif label == "freq":
            info["frequency_mhz"] = _number(value, int)
        elif label == "signal":
            info["rssi_dbm"] = _number(value, int)
        elif label in ("rx bitrate", "tx bitrate"):
            info["rx_rate_mbps" if label.startswith("rx") else "tx_rate_mbps"] = _number(value)
            if label == "rx bitrate" or info["radio_type"] is None:
                info["radio_type"] = _iw_radio(value) or info["radio_type"]
    return info


def _iw_radio(bitrate):
    for flag, name in (("EHT-", "802.11be"), ("HE-", "802.11ax"), ("VHT-", "802.11ac"), ("MCS", "802.11n")):
        if flag in bitrate:
            return name
    return None


def parse_iw_scan(text):
    """Parse `iw dev <if> scan dump` (cached results) into nearby_networks() dicts."""
    networks, current = [], None
    for line in (text or "").splitlines():
        match = re.match(r"^BSS\s+([0-9a-fA-F:]{17})", line)
        if match:
            current = {"bssid": _mac(match.group(1)), "ssid": None, "freq": None, "rssi": None}
            networks.append(current)
            continue
        if current is None:
            continue
        label, _, value = line.strip().partition(":")
        label = label.strip().lower()
        if label == "freq":
            current["freq"] = _number(value, int)
        elif label == "signal":
            current["rssi"] = _number(value, int)
        elif label == "ssid" and current["ssid"] is None:
            current["ssid"] = value.strip() or None
    return [_network(ssid=n["ssid"], bssid=n["bssid"], rssi_dbm=n["rssi"], frequency_mhz=n["freq"])
            for n in networks if n["bssid"]]


def _linux_wifi_interfaces():
    base = "/sys/class/net"
    try:
        return sorted(name for name in os.listdir(base) if os.path.isdir(os.path.join(base, name, "wireless")))
    except OSError:
        return []


def _run_text(command, timeout=10):
    try:
        result = run_command(command, timeout=timeout)
    except Exception:  # noqa: BLE001 - a missing or hanging tool is just "no data"
        return None
    return result.stdout if result.returncode == 0 else None


def _nmcli_list():
    if not shutil.which("nmcli"):
        return None
    text = _run_text(["nmcli", "-t", "-f", ",".join(NMCLI_FIELDS), "dev", "wifi", "list", "--rescan", "no"])
    return None if text is None else parse_nmcli_wifi(text)


def _linux_status():
    interfaces = _linux_wifi_interfaces()
    nm = _nmcli_list()
    if not interfaces and not nm:
        return _empty_status("no_wifi", "No Wi-Fi adapter found. The computer may be on Ethernet only.")
    active = next((n for n in nm or [] if n.get("active")), None)
    iface = (active or {}).get("device") or (interfaces[0] if interfaces else "")
    link = None
    if iface and shutil.which("iw"):
        text = _run_text(["iw", "dev", iface, "link"])
        link = parse_iw_link(text) if text is not None else None
    if not active and not (link and link["connected"]):
        if nm is None and link is None:
            return _empty_status("unsupported", "Neither nmcli nor iw is available to read the Wi-Fi link.", iface)
        return _empty_status("disconnected", "The Wi-Fi adapter is not connected to a network.", iface)
    status = _empty_status(None, "", iface)
    status.update(available=True, connected=True)
    if active:
        status.update(ssid=active["ssid"], bssid=active["bssid"], signal_percent=active["signal_percent"],
                      channel=active["channel"], frequency_mhz=active["frequency_mhz"], band=active["band"],
                      rx_rate_mbps=active.get("rate_mbps"), auth=active.get("security"))
    if link and link["connected"]:
        for key in ("ssid", "bssid", "frequency_mhz", "rssi_dbm", "rx_rate_mbps", "tx_rate_mbps", "radio_type"):
            if link[key] is not None:
                status[key] = link[key]
        if link["rssi_dbm"] is not None:
            status["signal_percent"] = dbm_to_percent(link["rssi_dbm"])
        if link["frequency_mhz"]:
            status["band"] = band_from_frequency(link["frequency_mhz"])
            status["channel"] = channel_from_frequency(link["frequency_mhz"])
    _finish(status)
    status["message"] = _status_message(status)
    return status


def _linux_networks():
    nm = _nmcli_list()
    if nm is not None:
        return [{k: n[k] for k in ("ssid", "bssid", "signal_percent", "rssi_dbm", "channel", "band",
                                   "frequency_mhz")} for n in nm]
    networks = []
    if shutil.which("iw"):
        for iface in _linux_wifi_interfaces():
            text = _run_text(["iw", "dev", iface, "scan", "dump"])
            networks.extend(parse_iw_scan(text or ""))
    return networks


# ---------------------------------------------------------------------------- macOS (best effort)

def _mac_profile():
    text = _run_text(["system_profiler", "SPAirPortDataType", "-json"], timeout=30)
    if not text:
        return None
    try:
        data = json.loads(text)
        return data["SPAirPortDataType"][0].get("spairport_airport_interfaces") or []
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _mac_channel(text):
    """'36 (5GHz, 80MHz)' -> (36, '5 GHz')."""
    text = str(text or "")
    return _number(text, int), _band_text(text)


def _mac_network(item):
    channel, band = _mac_channel(item.get("spairport_network_channel"))
    rssi = None
    noise = item.get("spairport_signal_noise")
    if noise:
        rssi = _number(str(noise).split("/")[0], int)
    ssid = item.get("_name")
    return _network(ssid=None if not ssid or ssid.startswith("<redacted") else ssid, rssi_dbm=rssi,
                    channel=channel, band=band)


def _mac_status():
    interfaces = _mac_profile()
    if interfaces is None:
        return _empty_status("unsupported", "system_profiler did not return Wi-Fi information.")
    if not interfaces:
        return _empty_status("no_wifi", "No Wi-Fi adapter found.")
    iface = next((i for i in interfaces if i.get("spairport_current_network_information")), interfaces[0])
    current = iface.get("spairport_current_network_information")
    name = iface.get("_name") or ""
    if not current:
        return _empty_status("disconnected", "The Wi-Fi adapter is not connected to a network.", name)
    net = _mac_network(current)
    status = _empty_status(None, "", name)
    status.update(available=True, connected=True, ssid=net["ssid"], rssi_dbm=net["rssi_dbm"],
                  channel=net["channel"], band=net["band"], radio_type=current.get("spairport_network_phymode"),
                  tx_rate_mbps=_number(str(current.get("spairport_network_rate") or ""), float),
                  auth=(str(current.get("spairport_security_mode") or "").replace("spairport_security_mode_", "")
                        .replace("_", " ") or None))
    _finish(status)
    status["message"] = _status_message(status)
    return status


def _mac_networks():
    networks = []
    for iface in _mac_profile() or []:
        for item in iface.get("spairport_airport_other_local_wireless_networks") or []:
            networks.append(_mac_network(item))
    return networks


# ---------------------------------------------------------------------------- public API

def _status_message(status):
    parts = [f"Connected to {status['ssid'] or 'a hidden network'}"]
    if status.get("band"):
        parts.append(f"{status['band']}" + (f" channel {status['channel']}" if status.get("channel") else ""))
    if status.get("rssi_dbm") is not None:
        parts.append(f"{status['rssi_dbm']} dBm ({status.get('signal_percent')} %)")
    text = ", ".join(parts)
    if status.get("rssi_dbm") is not None and status["rssi_dbm"] < WEAK_DBM:
        text += ". The signal is weak; move closer to the access point."
    return text


def wifi_status():
    """Current Wi-Fi link as a dict with the STATUS_KEYS (see the module docstring). Never raises."""
    try:
        if IS_WINDOWS:
            raw = _windows_raw()
            if raw is None:
                return _netsh_status()
            return _windows_status_from_raw(raw)
        if IS_MAC:
            return _mac_status()
        if sys.platform.startswith("linux"):
            return _linux_status()
        return _empty_status("unsupported", f"Wi-Fi diagnostics are not supported on {sys.platform}.")
    except Exception as exc:  # noqa: BLE001 - the contract is to never raise
        return _empty_status("error", f"Could not read the Wi-Fi status: {exc}")


def nearby_networks():
    """Access points from the system's cached scan results (no new scan is triggered). Never raises."""
    try:
        if IS_WINDOWS:
            return _windows_networks_from_raw(_windows_raw())
        if IS_MAC:
            return _mac_networks()
        if sys.platform.startswith("linux"):
            return _linux_networks()
    except Exception:  # noqa: BLE001 - the contract is to never raise
        pass
    return []


def _rssi(item):
    if item.get("rssi_dbm") is not None:
        return item["rssi_dbm"]
    return percent_to_dbm(item.get("signal_percent"))


def channel_congestion(status, networks):
    """How crowded our channel is: other BSSIDs on the same channel (same band), on overlapping
    2.4 GHz channels (within 4), and how many of those are strong (>= -70 dBm).
    level: 'high' with 3+ strong neighbors or 8+ in total, 'medium' with 1+ strong or 4+ in total."""
    result = {"same_channel": 0, "overlapping": 0, "strong_neighbors": 0, "level": "low"}
    try:
        channel = (status or {}).get("channel")
        if not channel:
            return result
        band = status.get("band") or _band_from_channel(channel)
        own = status.get("bssid")
        seen = set()
        for net in networks or []:
            bssid = net.get("bssid")
            if not bssid or bssid == own or bssid in seen or not net.get("channel"):
                continue
            seen.add(bssid)
            net_band = net.get("band") or _band_from_channel(net["channel"])
            if band and net_band and net_band != band:
                continue
            if net["channel"] == channel:
                result["same_channel"] += 1
            elif band == "2.4 GHz" and abs(net["channel"] - channel) <= 4:
                result["overlapping"] += 1
            else:
                continue
            rssi = _rssi(net)
            if rssi is not None and rssi >= WEAK_DBM:
                result["strong_neighbors"] += 1
        total = result["same_channel"] + result["overlapping"]
        if result["strong_neighbors"] >= 3 or total >= 8:
            result["level"] = "high"
        elif result["strong_neighbors"] >= 1 or total >= 4:
            result["level"] = "medium"
    except Exception:  # noqa: BLE001 - bad input gives the neutral result
        pass
    return result


# ---------------------------------------------------------------------------- tracker

_COMPACT_KEYS = ("connected", "ssid", "bssid", "rssi_dbm", "signal_percent", "channel", "band", "rx_rate_mbps",
                 "tx_rate_mbps")
_DISCONNECTED_REASONS = ("disconnected", "no_wifi")


class WifiTracker:
    """Turns successive wifi_status() samples into events and keeps link counters.

    update(status, when) returns a list of {'time', 'kind', 'text', 'details'} events. A sample counts
    as connected when status['connected'] is true (also under the Location block, which still gives
    signal and channel) and as disconnected when its reason is 'disconnected' or 'no_wifi'; other
    samples ('error', 'unsupported', blocked and not connected) say nothing about the link and are
    only recorded. SSID and BSSID changes are only reported when both values are known. Signal and rate baselines (median of the last 10 samples) restart after a roam or a
    reconnect, since a different access point has its own levels.
    """
    HISTORY = 10
    MIN_HISTORY = 3
    RECOVER_MARGIN_DB = 3          # hysteresis so a signal hovering at the threshold is one event
    MAX_SAMPLES = 100000

    def __init__(self, signal_drop_db=10, weak_dbm=-70, rate_drop_ratio=0.5):
        self.signal_drop_db = signal_drop_db
        self.weak_dbm = weak_dbm
        self.rate_drop_ratio = rate_drop_ratio
        self.roam_count = 0
        self.disconnect_count = 0
        self.min_rssi = None
        self.samples = []
        self._last = None            # last connected status
        self._connected = None       # None until the first conclusive sample
        self._weak = False
        self._rssi_history = []
        self._rate_history = []
        self._signal_dropped = False
        self._rate_dropped = False

    def _reset_baselines(self):
        self._rssi_history, self._rate_history = [], []
        self._signal_dropped = self._rate_dropped = False

    def update(self, status, when=None):
        when = when if when is not None else datetime.now()
        status = status or {}
        events = []

        def emit(kind, text, **details):
            events.append({"time": when, "kind": kind, "text": text, "details": details})

        self.samples.append((when, {k: status.get(k) for k in _COMPACT_KEYS}))
        if len(self.samples) > self.MAX_SAMPLES:
            del self.samples[:len(self.samples) - self.MAX_SAMPLES]

        connected = bool(status.get("connected"))
        if not connected and status.get("reason") not in _DISCONNECTED_REASONS:
            return events            # inconclusive sample
        if not connected:
            if self._connected:
                self.disconnect_count += 1
                last = self._last or {}
                emit("disconnect", f"Wi-Fi disconnected from {last.get('ssid') or 'the network'}",
                     ssid=last.get("ssid"), bssid=last.get("bssid"), reason=status.get("reason"))
            self._connected = False
            self._weak = False
            self._reset_baselines()
            return events

        last = self._last
        if self._connected is False:
            emit("reconnect", f"Wi-Fi reconnected to {status.get('ssid') or 'a network'}",
                 ssid=status.get("ssid"), bssid=status.get("bssid"))
        if last:
            if status.get("ssid") and last.get("ssid") and status["ssid"] != last["ssid"]:
                emit("ssid_change", f"Wi-Fi network changed from {last.get('ssid')} to {status.get('ssid')}",
                     old=last.get("ssid"), new=status.get("ssid"))
                self._reset_baselines()
            elif status.get("bssid") and last.get("bssid") and status["bssid"] != last["bssid"]:
                self.roam_count += 1
                emit("roam", f"Roamed to another access point ({last['bssid']} -> {status['bssid']})",
                     old=last["bssid"], new=status["bssid"], ssid=status.get("ssid"),
                     old_rssi=last.get("rssi_dbm"), new_rssi=status.get("rssi_dbm"))
                self._reset_baselines()
            if status.get("band") and last.get("band") and status["band"] != last["band"]:
                emit("band_change", f"Wi-Fi band changed from {last['band']} to {status['band']}",
                     old=last["band"], new=status["band"])
        elif self._connected is False:
            self._reset_baselines()
        self._connected = True
        self._last = dict(status)

        rssi = _rssi(status)
        if rssi is not None:
            self.min_rssi = rssi if self.min_rssi is None else min(self.min_rssi, rssi)
            if not self._weak and rssi < self.weak_dbm:
                self._weak = True
                emit("signal_weak", f"Wi-Fi signal is weak ({rssi} dBm)", rssi_dbm=rssi, threshold=self.weak_dbm)
            elif self._weak and rssi >= self.weak_dbm + self.RECOVER_MARGIN_DB:
                self._weak = False
                emit("signal_recovered", f"Wi-Fi signal recovered ({rssi} dBm)", rssi_dbm=rssi)
            if len(self._rssi_history) >= self.MIN_HISTORY:
                median = statistics.median(self._rssi_history)
                if median - rssi >= self.signal_drop_db:
                    if not self._signal_dropped:
                        emit("signal_drop", f"Wi-Fi signal dropped by {median - rssi:g} dB to {rssi} dBm",
                             rssi_dbm=rssi, median_dbm=median)
                    self._signal_dropped = True
                else:
                    self._signal_dropped = False
            self._rssi_history = (self._rssi_history + [rssi])[-self.HISTORY:]

        rate = status.get("rx_rate_mbps")
        if rate is not None:
            if len(self._rate_history) >= self.MIN_HISTORY:
                median = statistics.median(self._rate_history)
                if median > 0 and rate < median * self.rate_drop_ratio:
                    if not self._rate_dropped:
                        emit("rate_drop", f"Wi-Fi receive rate dropped to {rate:g} Mbps (usually {median:g} Mbps)",
                             rx_rate_mbps=rate, median_mbps=median)
                    self._rate_dropped = True
                else:
                    self._rate_dropped = False
            self._rate_history = (self._rate_history + [rate])[-self.HISTORY:]
        return events
