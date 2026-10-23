"""iperf3-compatible TCP client and server written in Python.

This is an independent implementation of the iperf3 control protocol, written from the
protocol as implemented in ESnet's iperf3 (https://github.com/esnet/iperf, BSD-3-Clause):
a TCP control connection with one-byte state messages and length-prefixed JSON, plus one
TCP connection per data stream. No iperf3 code is copied. See THIRD_PARTY_NOTICES.md.

Supported: TCP, upload (client sends) and download (-R, server sends), parallel streams,
fixed duration; the server also takes byte and block count tests (-n, -k). Not supported yet:
UDP, bidirectional mode, authentication.
"""
import errno
import json
import math
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
MAX_BLKSIZE = 1024 * 1024      # iperf3's MAX_BLOCKSIZE
MAX_STREAMS = 128              # iperf3's MAX_STREAMS
POLL = 0.2                     # control sockets wake up this often to notice stop()
STOPPED_TEXT = "The test was stopped."

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
IEDURATION = 5
IENUMSTREAMS = 6
IEBLOCKSIZE = 7
IEUNIMP = 13
ERROR_TEXT = {
    IEDURATION: "invalid test duration",
    IENUMSTREAMS: f"number of parallel streams must be 1 to {MAX_STREAMS}",
    IEBLOCKSIZE: f"block size must be 1 to {MAX_BLKSIZE} bytes",
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


def recv_exact(sock, size, cancel=None, timeout=15):
    """Read exactly size bytes.

    With cancel (a callable), sock must have a short timeout such as POLL: the read then gives up
    with IperfError when cancel() turns true, or with socket.timeout after timeout seconds without data.
    """
    data = bytearray()
    deadline = time.monotonic() + timeout
    while len(data) < size:
        try:
            chunk = sock.recv(size - len(data))
        except socket.timeout:
            if cancel is None:
                raise
            if cancel():
                raise IperfError(STOPPED_TEXT)
            if time.monotonic() >= deadline:
                raise
            continue
        if not chunk:
            if cancel and cancel():
                raise IperfError(STOPPED_TEXT)
            raise IperfError("the connection was closed by the other side")
        data += chunk
        deadline = time.monotonic() + timeout
    return bytes(data)


def send_state(sock, state):
    sock.sendall(struct.pack("b", state))


def recv_state(sock, cancel=None, timeout=15):
    return struct.unpack("b", recv_exact(sock, 1, cancel, timeout))[0]


def send_json(sock, obj):
    payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def recv_json(sock, max_size=0, cancel=None, timeout=15):
    size = struct.unpack("!I", recv_exact(sock, 4, cancel, timeout))[0]
    if size == 0 or (max_size and size > max_size):
        raise IperfError(f"unexpected JSON message size {size}")
    return json.loads(recv_exact(sock, size, cancel, timeout).decode("utf-8"))


def _shutdown(sock):
    """Wake up any thread blocked on sock; the owner still closes it."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _error_text(code):
    if os.name == "nt":
        import ctypes
        return ctypes.FormatError(code).strip()
    return os.strerror(code)


def mbps(byte_count, seconds):
    return byte_count * 8 / seconds / 1_000_000 if seconds > 0 else 0.0


class _SendBudget:
    """Bytes the sending streams of a byte or block count test (iperf3 -n / -k) may still send together."""

    def __init__(self, total):
        self.remaining = total
        self._lock = threading.Lock()

    def take(self, size):
        with self._lock:
            size = min(size, self.remaining)
            self.remaining -= size
            return size

    def give_back(self, size):
        with self._lock:
            self.remaining += size


class _Stream:
    """One TCP data connection with a sender or receiver thread.

    A sending stream with a budget (_SendBudget) stops once the budget is used up.
    """

    def __init__(self, sock, stream_id, sending, blksize, budget=None):
        self.sock = sock
        self.id = stream_id
        self.sending = sending
        self.blksize = blksize
        self.budget = budget
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
                    size = self.budget.take(self.blksize) if self.budget else self.blksize
                    if size == 0:
                        break   # byte / block count reached; the client ends the test with TEST_END
                    try:
                        sent = self.sock.send(buffer[:size])
                    except socket.timeout:
                        sent = 0
                    except OSError:
                        if self.budget:
                            self.budget.give_back(size)
                        raise
                    self.bytes += sent
                    if self.budget and sent < size:
                        self.budget.give_back(size - sent)
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
        self._forced = False
        self._graceful = False      # True while the test runs: stop() then still exchanges the results
        self._lock = threading.Lock()
        self._sockets = []
        self.ctrl = None
        self.streams = []

    def stop(self, force=False):
        """End the test early.

        While the test is running the results so far are still exchanged. During setup, or with
        force=True, the sockets are shut down so run() returns within a fraction of a second.
        """
        self._forced = self._forced or force
        self._stop.set()
        if self._cancelled():
            with self._lock:
                sockets = list(self._sockets)
            for sock in sockets:
                _shutdown(sock)

    def _cancelled(self):
        return self._stop.is_set() and (self._forced or not self._graceful)

    def _check_cancel(self):
        if self._cancelled():
            raise IperfError(STOPPED_TEXT)

    def _connect(self):
        """Non-blocking connect that notices stop() and gives up after connect_timeout."""
        deadline = time.monotonic() + self.connect_timeout
        last_error = None
        for family, kind, proto, _name, address in socket.getaddrinfo(self.host, self.port, 0, socket.SOCK_STREAM):
            self._check_cancel()
            sock = socket.socket(family, kind, proto)
            with self._lock:
                self._sockets.append(sock)
            try:
                sock.setblocking(False)
                code = sock.connect_ex(address)
                if code not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY):
                    raise OSError(code, _error_text(code))
                while code != 0:
                    self._check_cancel()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise socket.timeout("timed out")
                    _, writable, failed = select.select([], [sock], [sock], min(POLL, remaining))
                    if writable or failed:
                        code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                        if code:
                            raise OSError(code, _error_text(code))
                        break
                self._check_cancel()
                sock.settimeout(POLL)
                return sock
            except (OSError, IperfError) as e:
                with self._lock:
                    self._sockets.remove(sock)
                sock.close()
                if isinstance(e, (IperfError, socket.timeout)):
                    raise
                last_error = e
        raise last_error or OSError(f"Could not resolve {self.host}")

    def _recv_state(self):
        return recv_state(self.ctrl, self._cancelled)

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
            test_started = None

            while True:
                self._check_cancel()
                state = self._recv_state()
                if state == PARAM_EXCHANGE:
                    params = {"tcp": True, "omit": 0, "time": self.duration, "num": 0, "blockcount": 0,
                              "parallel": self.parallel, "len": self.blksize, "client_version": CLIENT_VERSION}
                    if self.reverse:
                        params["reverse"] = True
                    send_json(self.ctrl, params)
                elif state == CREATE_STREAMS:
                    for stream_id in stream_ids(self.parallel):
                        self._check_cancel()
                        sock = self._connect()
                        sock.sendall(cookie)
                        self.streams.append(_Stream(sock, stream_id, sending=not self.reverse,
                                                    blksize=self.blksize))
                    self.log(f"Connected {self.parallel} stream(s), "
                             f"{'server sends (download)' if self.reverse else 'client sends (upload)'}")
                elif state == TEST_START:
                    pass
                elif state == TEST_RUNNING:
                    self._graceful = True
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
                    result['server_results'] = recv_json(self.ctrl, cancel=self._cancelled)
                elif state == DISPLAY_RESULTS:
                    send_state(self.ctrl, IPERF_DONE)
                    break
                elif state == IPERF_DONE:
                    break
                elif state == ACCESS_DENIED:
                    raise IperfError("The server is busy running a test. Try again later or pick another server.")
                elif state == SERVER_ERROR:
                    code, errno_value = struct.unpack("!ii", recv_exact(self.ctrl, 8, self._cancelled))
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
            with self._lock:
                sockets, self._sockets = self._sockets, []
            for sock in sockets:
                try:
                    sock.close()
                except OSError:
                    pass
        if result['error'] and self._cancelled():
            result['error'] = STOPPED_TEXT

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
                state = self._recv_state()
                if state == SERVER_TERMINATE:
                    raise IperfError("The server terminated the test.")
                if state == SERVER_ERROR:
                    code, _errno = struct.unpack("!ii", recv_exact(self.ctrl, 8, self._cancelled))
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
        self._lock = threading.Lock()
        self._handshakes = set()    # sockets that may sit in a blocking read; stop() shuts them down
        self.listener = None

    def stop(self):
        """Stop serving. A running test is ended with SERVER_TERMINATE; serve_forever() returns within a
        fraction of a second, even while a client is half-way through its handshake."""
        self._stop.set()
        with self._lock:
            sockets = list(self._handshakes)
        for sock in sockets:
            _shutdown(sock)

    def _track(self, sock, active=True):
        with self._lock:
            if active:
                self._handshakes.add(sock)
            else:
                self._handshakes.discard(sock)
        if active and self._stop.is_set():
            _shutdown(sock)

    def _stopped(self):
        return self._stop.is_set()

    def _listen(self):
        try:
            if self.bind_address and ":" not in self.bind_address:
                raise OSError("an IPv4 bind address needs an IPv4 socket")
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
                self._track(conn)
                try:
                    self._handle_test(conn, addr)
                except (IperfError, OSError, ValueError) as e:
                    if self._stop.is_set():
                        e = "the server was stopped"
                    self.event('error', f"Test from {addr[0].removeprefix('::ffff:')} failed: {e}")
                finally:
                    self._track(conn, False)
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
            except OSError:
                break
            conn.settimeout(POLL)
            self._track(conn)
            try:
                received = recv_exact(conn, COOKIE_SIZE, self._stopped, timeout=5)
                if received == cookie:
                    return conn
                send_state(conn, ACCESS_DENIED)   # someone else while we are busy
            except (IperfError, OSError):
                pass
            finally:
                self._track(conn, False)
            conn.close()
        raise IperfError("the client did not open its data streams")

    def _reject(self, ctrl, code, message):
        send_state(ctrl, SERVER_ERROR)
        ctrl.sendall(struct.pack("!ii", code, 0))
        raise IperfError(message)

    def _check_params(self, ctrl, client, params):
        """Validate the client's test parameters; returns
        (parallel, reverse, duration, blksize, clamped, byte_limit).

        Invalid values are answered with SERVER_ERROR. A duration above max_duration is clamped: the
        server then ends the test with SERVER_TERMINATE when max_duration has passed. byte_limit is the
        total of a byte or block count test (iperf3 -n / -k, sent with time 0), else 0: the client ends
        such a test with TEST_END, and in reverse mode the server stops sending at the limit.
        """
        def number(key, default, integer):
            value = params.get(key, default)
            if value is None:
                return default
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(key)
            if integer and value != int(value):
                raise ValueError(key)
            return int(value) if integer else float(value)

        if not isinstance(params, dict):
            self._reject(ctrl, IEUNIMP, f"{client} sent invalid test parameters")
        if not params.get("tcp") or params.get("udp") or params.get("sctp") or params.get("bidirectional"):
            kind = "UDP" if params.get("udp") else "bidirectional" if params.get("bidirectional") else "this"
            self._reject(ctrl, IEUNIMP, f"{client} asked for a {kind} test, which this server does not support yet")
        try:
            parallel = number("parallel", 1, True)
        except ValueError:
            parallel = 0
        if not 1 <= parallel <= MAX_STREAMS:
            self._reject(ctrl, IENUMSTREAMS, f"{client} asked for an invalid number of streams")
        try:
            blksize = number("len", DEFAULT_BLKSIZE, True) or DEFAULT_BLKSIZE
        except ValueError:
            blksize = -1
        if not 1 <= blksize <= MAX_BLKSIZE:
            self._reject(ctrl, IEBLOCKSIZE, f"{client} asked for an invalid block size")
        try:
            duration = number("time", 10, False)
        except ValueError:
            duration = -1
        if duration < 0:
            self._reject(ctrl, IEDURATION, f"{client} asked for an invalid test duration")
        try:
            byte_count = number("bytes", 0, True)
            block_count = number("blockcount", 0, True)
        except ValueError:
            byte_count = block_count = -1
        if byte_count < 0 or block_count < 0:
            self._reject(ctrl, IEUNIMP, f"{client} asked for an invalid byte or block count")
        # Both set: whichever is reached first ends the test, as in iperf3
        byte_limit = min([limit for limit in (byte_count, block_count * blksize) if limit > 0], default=0)
        # time 0 is a byte / block count test, or an endless one (iperf3 -t 0); neither may run longer
        # than max_duration
        if duration == 0 or duration > self.max_duration:
            return parallel, bool(params.get("reverse")), float(self.max_duration), blksize, True, byte_limit
        return parallel, bool(params.get("reverse")), duration, blksize, False, byte_limit

    def _handle_test(self, ctrl, addr):
        client = addr[0].removeprefix("::ffff:")
        ctrl.settimeout(POLL)
        ctrl.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        cookie = recv_exact(ctrl, COOKIE_SIZE, self._stopped, timeout=10)
        send_state(ctrl, PARAM_EXCHANGE)
        params = recv_json(ctrl, MAX_PARAMS_JSON, self._stopped, timeout=10)
        parallel, reverse, duration, blksize, clamped, byte_limit = self._check_params(ctrl, client, params)
        if clamped and params.get("time"):
            self.event('error', f"{client}: test limited to the server maximum of {duration:.0f} s")
        self.event('client', {'address': client, 'parallel': parallel, 'reverse': reverse, 'duration': duration,
                              'bytes': byte_limit, 'version': str(params.get("client_version", ""))[:80]})
        budget = _SendBudget(byte_limit) if byte_limit and reverse else None

        send_state(ctrl, CREATE_STREAMS)
        deadline = time.monotonic() + 10
        streams = []
        try:
            for stream_id in stream_ids(parallel):
                conn = self._accept_stream(cookie, deadline)
                streams.append(_Stream(conn, stream_id, sending=reverse, blksize=blksize, budget=budget))

            send_state(ctrl, TEST_START)
            send_state(ctrl, TEST_RUNNING)
            started = time.monotonic()
            for stream in streams:
                stream.start()

            # A clamped test ends at max_duration; otherwise the client gets some slack to send TEST_END
            limit = started + duration + (0 if clamped else 10)
            last_time, last_bytes = started, 0
            self._track(ctrl, False)   # the loop below polls; stop() lets it send SERVER_TERMINATE
            while True:
                if self._stop.is_set():
                    send_state(ctrl, SERVER_TERMINATE)
                    raise IperfError("the server was stopped")
                if time.monotonic() > limit:
                    send_state(ctrl, SERVER_TERMINATE)
                    raise IperfError(f"the test reached the server's maximum of {duration:.0f} s" if clamped
                                     else "the client did not end the test in time")
                readable, _, _ = select.select([ctrl, self.listener], [], [], POLL)
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
                    state = recv_state(ctrl, self._stopped)
                    if state == TEST_END:
                        break
                    if state == CLIENT_TERMINATE:
                        raise IperfError("the client terminated the test")
                    if state in (IPERF_DONE,):
                        raise IperfError("the client ended the session early")
            self._track(ctrl)

            for stream in streams:
                stream.finish()
            send_state(ctrl, EXCHANGE_RESULTS)
            client_results = recv_json(ctrl, MAX_PARAMS_JSON * 16, self._stopped, timeout=10)
            send_json(ctrl, _results_message(streams, sender=reverse))
            send_state(ctrl, DISPLAY_RESULTS)
            try:
                recv_state(ctrl, self._stopped, timeout=5)   # IPERF_DONE
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
