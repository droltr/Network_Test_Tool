"""iperf3-compatible TCP client and server written in Python.

This is an independent implementation of the iperf3 control protocol, written from the
protocol as implemented in ESnet's iperf3 (https://github.com/esnet/iperf, BSD-3-Clause):
a TCP control connection with one-byte state messages and length-prefixed JSON, plus one
TCP connection per data stream. No iperf3 code is copied. See THIRD_PARTY_NOTICES.md.

Supported: TCP, upload (client sends) and download (-R, server sends), parallel streams,
fixed duration. Not supported yet: UDP, bidirectional mode, authentication.
"""
import json
import os
import secrets
import select
import socket
import struct
import threading
import time

DEFAULT_PORT = 5201
DEFAULT_BLKSIZE = 128 * 1024
COOKIE_SIZE = 37
COOKIE_CHARS = "abcdefghijklmnopqrstuvwxyz234567"
CLIENT_VERSION = "3.17 (network-test-tool)"
MAX_PARAMS_JSON = 8 * 1024

# Control states (iperf_api.h)
TEST_START = 1
TEST_RUNNING = 2
TEST_END = 4
PARAM_EXCHANGE = 9
CREATE_STREAMS = 10
SERVER_TERMINATE = 11
CLIENT_TERMINATE = 12
EXCHANGE_RESULTS = 13
DISPLAY_RESULTS = 14
IPERF_START = 15
IPERF_DONE = 16
ACCESS_DENIED = -1
SERVER_ERROR = -2

# Error numbers sent with SERVER_ERROR (iperf_api.h)
IEUNIMP = 13
ERROR_TEXT = {
    IEUNIMP: "an option you are trying to set is not implemented yet",
    119: "the client has terminated",
    120: "the server has terminated",
    121: "the server is busy running a test. try again later",
}


class IperfError(Exception):
    pass


def make_cookie():
    """36 random characters from iperf's alphabet plus a terminating NUL."""
    return ("".join(secrets.choice(COOKIE_CHARS) for _ in range(COOKIE_SIZE - 1)) + "\0").encode("ascii")


def stream_ids(count):
    """iperf3 numbers streams 1, 3, 4, 5, ... (kept for compatibility, see iperf_add_stream)."""
    return [1] + list(range(3, count + 2))


def recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise IperfError("the connection was closed by the other side")
        data += chunk
    return bytes(data)


def send_state(sock, state):
    sock.sendall(struct.pack("b", state))


def recv_state(sock):
    return struct.unpack("b", recv_exact(sock, 1))[0]


def send_json(sock, obj):
    payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def recv_json(sock, max_size=0):
    size = struct.unpack("!I", recv_exact(sock, 4))[0]
    if size == 0 or (max_size and size > max_size):
        raise IperfError(f"unexpected JSON message size {size}")
    return json.loads(recv_exact(sock, size).decode("utf-8"))


def mbps(byte_count, seconds):
    return byte_count * 8 / seconds / 1_000_000 if seconds > 0 else 0.0


class _Stream:
    """One TCP data connection with a sender or receiver thread."""

    def __init__(self, sock, stream_id, sending, blksize):
        self.sock = sock
        self.id = stream_id
        self.sending = sending
        self.blksize = blksize
        self.bytes = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.start_time = None
        self.end_time = None
        self.error = None

    def start(self):
        self.start_time = time.monotonic()
        self.thread.start()

    def _run(self):
        self.sock.settimeout(0.5)
        try:
            if self.sending:
                buffer = memoryview(os.urandom(self.blksize))
                while not self.stop.is_set():
                    try:
                        self.bytes += self.sock.send(buffer)
                    except socket.timeout:
                        continue
            else:
                buffer = bytearray(self.blksize)
                while not self.stop.is_set():
                    try:
                        received = self.sock.recv_into(buffer)
                    except socket.timeout:
                        continue
                    if received == 0:
                        break
                    self.bytes += received
        except OSError as e:
            if not self.stop.is_set():
                self.error = str(e)
        finally:
            self.end_time = time.monotonic()

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=2)
        if self.end_time is None:
            self.end_time = time.monotonic()
        try:
            self.sock.close()
        except OSError:
            pass

    def result(self):
        """Per-stream entry for the EXCHANGE_RESULTS message (send_results in iperf_api.c)."""
        return {
            "id": self.id,
            "bytes": self.bytes,
            "retransmits": -1,
            "jitter": 0,
            "errors": 0,
            "omitted_errors": 0,
            "packets": 0,
            "omitted_packets": 0,
            "start_time": 0,
            "end_time": round((self.end_time or time.monotonic()) - (self.start_time or time.monotonic()), 6),
        }


def _results_message(streams, sender):
    return {
        "cpu_util_total": 0,
        "cpu_util_user": 0,
        "cpu_util_system": 0,
        # 0: sender without retransmit counters, -1: receiver (iperf_api.c send_results)
        "sender_has_retransmits": 0 if sender else -1,
        "streams": [s.result() for s in streams],
    }


def _peer_totals(peer_results):
    streams = peer_results.get("streams", []) if isinstance(peer_results, dict) else []
    total = sum(int(s.get("bytes", 0)) for s in streams)
    seconds = max((float(s.get("end_time", 0)) - float(s.get("start_time", 0)) for s in streams), default=0.0)
    retrans = [int(s.get("retransmits", -1)) for s in streams]
    retransmits = sum(r for r in retrans if r >= 0) if any(r >= 0 for r in retrans) else None
    return total, seconds, retransmits


# ---------------------------------------------------------------------------- client

class IperfClient:
    """Run one iperf3 TCP test against a server.

    interval_callback(dict) gets {'t': seconds, 'mbps': value} about once per second;
    log_callback(str) gets progress lines.
    """

    def __init__(self, host, port=DEFAULT_PORT, duration=10, parallel=1, reverse=False,
                 blksize=DEFAULT_BLKSIZE, connect_timeout=8, interval_callback=None, log_callback=None):
        self.host = host
        self.port = int(port)
        self.duration = max(1, int(duration))
        self.parallel = max(1, min(int(parallel), 64))
        self.reverse = bool(reverse)
        self.blksize = int(blksize)
        self.connect_timeout = connect_timeout
        self.interval_callback = interval_callback or (lambda data: None)
        self.log = log_callback or (lambda text: None)
        self._stop = threading.Event()
        self.ctrl = None
        self.streams = []

    def stop(self):
        """End the test early; the results so far are still exchanged."""
        self._stop.set()

    def _connect(self):
        return socket.create_connection((self.host, self.port), timeout=self.connect_timeout)

    def run(self):
        result = {
            'host': self.host, 'port': self.port, 'duration': self.duration, 'parallel': self.parallel,
            'direction': 'download' if self.reverse else 'upload', 'intervals': [], 'error': None,
        }
        cookie = make_cookie()
        try:
            self.log(f"Connecting to {self.host} port {self.port}")
            self.ctrl = self._connect()
            self.ctrl.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            result['remote_address'] = self.ctrl.getpeername()[0]
            self.ctrl.sendall(cookie)
            self.ctrl.settimeout(15)
            test_started = None

            while True:
                state = recv_state(self.ctrl)
                if state == PARAM_EXCHANGE:
                    params = {"tcp": True, "omit": 0, "time": self.duration, "num": 0, "blockcount": 0,
                              "parallel": self.parallel, "len": self.blksize, "client_version": CLIENT_VERSION}
                    if self.reverse:
                        params["reverse"] = True
                    send_json(self.ctrl, params)
                elif state == CREATE_STREAMS:
                    for stream_id in stream_ids(self.parallel):
                        sock = self._connect()
                        sock.sendall(cookie)
                        self.streams.append(_Stream(sock, stream_id, sending=not self.reverse,
                                                    blksize=self.blksize))
                    self.log(f"Connected {self.parallel} stream(s), "
                             f"{'server sends (download)' if self.reverse else 'client sends (upload)'}")
                elif state == TEST_START:
                    pass
                elif state == TEST_RUNNING:
                    test_started = time.monotonic()
                    for stream in self.streams:
                        stream.start()
                    self._run_test(test_started, result)
                    send_state(self.ctrl, TEST_END)
                    elapsed = time.monotonic() - test_started
                    for stream in self.streams:
                        if not self.reverse:
                            stream.finish()
                    result['elapsed'] = elapsed
                elif state == EXCHANGE_RESULTS:
                    if self.reverse:
                        for stream in self.streams:
                            stream.finish()
                    send_json(self.ctrl, _results_message(self.streams, sender=not self.reverse))
                    result['server_results'] = recv_json(self.ctrl)
                elif state == DISPLAY_RESULTS:
                    send_state(self.ctrl, IPERF_DONE)
                    break
                elif state == IPERF_DONE:
                    break
                elif state == ACCESS_DENIED:
                    raise IperfError("The server is busy running a test. Try again later or pick another server.")
                elif state == SERVER_ERROR:
                    code, errno_value = struct.unpack("!ii", recv_exact(self.ctrl, 8))
                    text = ERROR_TEXT.get(code, f"server error {code}")
                    raise IperfError(f"Server error: {text}" + (f" (errno {errno_value})" if errno_value > 0 else ""))
                elif state == SERVER_TERMINATE:
                    raise IperfError("The server terminated the test.")
                else:
                    raise IperfError(f"Unexpected message {state} from the server.")
        except socket.timeout:
            result['error'] = "The server did not respond in time."
        except ConnectionRefusedError:
            result['error'] = f"Connection refused by {self.host}:{self.port}. No iperf3 server is listening there."
        except socket.gaierror:
            result['error'] = f"Could not resolve {self.host}."
        except (IperfError, OSError, ValueError) as e:
            result['error'] = str(e)
        finally:
            for stream in self.streams:
                stream.finish()
            if self.ctrl:
                try:
                    self.ctrl.close()
                except OSError:
                    pass

        self._summarize(result)
        return result

    def _run_test(self, started, result):
        """Wait for the duration while sampling throughput once per second."""
        last_time, last_bytes = started, 0
        deadline = started + self.duration
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= deadline:
                break
            # Watch the control socket for an early server message without consuming the test time
            readable, _, _ = select.select([self.ctrl], [], [], min(0.2, deadline - now))
            if readable:
                state = recv_state(self.ctrl)
                if state == SERVER_TERMINATE:
                    raise IperfError("The server terminated the test.")
                if state == SERVER_ERROR:
                    code, _errno = struct.unpack("!ii", recv_exact(self.ctrl, 8))
                    raise IperfError(f"Server error: {ERROR_TEXT.get(code, code)}")
            now = time.monotonic()
            if now - last_time >= 1.0:
                total = sum(s.bytes for s in self.streams)
                sample = {'t': round(now - started, 2), 'mbps': round(mbps(total - last_bytes, now - last_time), 2)}
                result['intervals'].append(sample)
                self.interval_callback(sample)
                last_time, last_bytes = now, total
        now = time.monotonic()
        total = sum(s.bytes for s in self.streams)
        if now - last_time > 0.2:
            sample = {'t': round(now - started, 2), 'mbps': round(mbps(total - last_bytes, now - last_time), 2)}
            result['intervals'].append(sample)
            self.interval_callback(sample)

    def _summarize(self, result):
        local_bytes = sum(s.bytes for s in self.streams)
        local_seconds = max((s.end_time - s.start_time for s in self.streams
                             if s.start_time and s.end_time), default=result.get('elapsed', 0) or 0)
        peer_bytes, peer_seconds, retransmits = _peer_totals(result.get('server_results'))
        if self.reverse:
            sent, sent_s, received, received_s = peer_bytes, peer_seconds, local_bytes, local_seconds
        else:
            sent, sent_s, received, received_s = local_bytes, local_seconds, peer_bytes, peer_seconds
        result.update({
            'sent_bytes': sent,
            'received_bytes': received,
            'sender_mbps': round(mbps(sent, sent_s), 2),
            'receiver_mbps': round(mbps(received, received_s), 2) if received_s else None,
            'retransmits': retransmits,
        })


# ---------------------------------------------------------------------------- server

class IperfServer:
    """iperf3-compatible TCP server; one test at a time, like iperf3 itself.

    event_callback(kind, data) receives: 'listening', 'client', 'interval', 'result', 'error', 'stopped'.
    """

    def __init__(self, port=DEFAULT_PORT, bind_address="", event_callback=None, max_duration=3600):
        self.port = int(port)
        self.bind_address = bind_address
        self.event = event_callback or (lambda kind, data: None)
        self.max_duration = max_duration
        self._stop = threading.Event()
        self.listener = None

    def stop(self):
        self._stop.set()

    def _listen(self):
        try:
            sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)   # accept IPv4 too
        except (OSError, AttributeError):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_address, self.port))
        sock.listen(16)
        sock.settimeout(0.5)
        return sock

    def serve_forever(self):
        try:
            self.listener = self._listen()
        except OSError as e:
            self.event('error', f"Could not listen on port {self.port}: {e}")
            self.event('stopped', None)
            return
        self.event('listening', {'port': self.port})
        try:
            while not self._stop.is_set():
                try:
                    conn, addr = self.listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    self._handle_test(conn, addr)
                except (IperfError, OSError, ValueError) as e:
                    self.event('error', f"Test from {addr[0]} failed: {e}")
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass
        finally:
            self.listener.close()
            self.event('stopped', None)

    def _accept_stream(self, cookie, deadline):
        while time.monotonic() < deadline and not self._stop.is_set():
            try:
                conn, _addr = self.listener.accept()
            except socket.timeout:
                continue
            conn.settimeout(5)
            try:
                received = recv_exact(conn, COOKIE_SIZE)
            except (IperfError, OSError):
                conn.close()
                continue
            if received == cookie:
                return conn
            send_state(conn, ACCESS_DENIED)   # someone else while we are busy
            conn.close()
        raise IperfError("the client did not open its data streams")

    def _handle_test(self, ctrl, addr):
        client = addr[0].removeprefix("::ffff:")
        ctrl.settimeout(10)
        ctrl.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        cookie = recv_exact(ctrl, COOKIE_SIZE)
        send_state(ctrl, PARAM_EXCHANGE)
        params = recv_json(ctrl, MAX_PARAMS_JSON)

        if not params.get("tcp") or params.get("udp") or params.get("sctp") or params.get("bidirectional"):
            send_state(ctrl, SERVER_ERROR)
            ctrl.sendall(struct.pack("!ii", IEUNIMP, 0))
            kind = "UDP" if params.get("udp") else "bidirectional" if params.get("bidirectional") else "this"
            raise IperfError(f"{client} asked for a {kind} test, which this server does not support yet")

        parallel = max(1, min(int(params.get("parallel", 1)), 128))
        reverse = bool(params.get("reverse"))
        duration = float(params.get("time", 10) or 0)
        blksize = int(params.get("len", DEFAULT_BLKSIZE) or DEFAULT_BLKSIZE)
        self.event('client', {'address': client, 'parallel': parallel, 'reverse': reverse, 'duration': duration,
                              'version': params.get("client_version", "")})

        send_state(ctrl, CREATE_STREAMS)
        deadline = time.monotonic() + 10
        streams = []
        try:
            for stream_id in stream_ids(parallel):
                conn = self._accept_stream(cookie, deadline)
                streams.append(_Stream(conn, stream_id, sending=reverse, blksize=blksize))

            send_state(ctrl, TEST_START)
            send_state(ctrl, TEST_RUNNING)
            started = time.monotonic()
            for stream in streams:
                stream.start()

            limit = started + (duration if duration > 0 else self.max_duration) + 10
            last_time, last_bytes = started, 0
            while True:
                if self._stop.is_set():
                    send_state(ctrl, SERVER_TERMINATE)
                    raise IperfError("server stopped")
                if time.monotonic() > limit:
                    raise IperfError("the client did not end the test in time")
                readable, _, _ = select.select([ctrl, self.listener], [], [], 0.2)
                if self.listener in readable:
                    try:
                        extra, _ = self.listener.accept()
                        send_state(extra, ACCESS_DENIED)
                        extra.close()
                    except OSError:
                        pass
                now = time.monotonic()
                if now - last_time >= 1.0:
                    total = sum(s.bytes for s in streams)
                    self.event('interval', {'address': client, 't': round(now - started, 2),
                                            'mbps': round(mbps(total - last_bytes, now - last_time), 2),
                                            'reverse': reverse})
                    last_time, last_bytes = now, total
                if ctrl in readable:
                    state = recv_state(ctrl)
                    if state == TEST_END:
                        break
                    if state == CLIENT_TERMINATE:
                        raise IperfError("the client terminated the test")
                    if state in (IPERF_DONE,):
                        raise IperfError("the client ended the session early")

            for stream in streams:
                stream.finish()
            send_state(ctrl, EXCHANGE_RESULTS)
            client_results = recv_json(ctrl)
            send_json(ctrl, _results_message(streams, sender=reverse))
            send_state(ctrl, DISPLAY_RESULTS)
            try:
                recv_state(ctrl)   # IPERF_DONE
            except (IperfError, OSError):
                pass

            local_bytes = sum(s.bytes for s in streams)
            local_seconds = max((s.end_time - s.start_time for s in streams), default=0)
            peer_bytes, peer_seconds, _ = _peer_totals(client_results)
            self.event('result', {
                'address': client, 'reverse': reverse, 'parallel': parallel,
                'direction': 'server sent (client download)' if reverse else 'server received (client upload)',
                'local_bytes': local_bytes, 'local_mbps': round(mbps(local_bytes, local_seconds), 2),
                'peer_bytes': peer_bytes, 'peer_mbps': round(mbps(peer_bytes, peer_seconds), 2),
                'seconds': round(local_seconds, 2),
            })
        finally:
            for stream in streams:
                stream.finish()
