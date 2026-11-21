"""Fake RTMP endpoints for testing the stream-key gate (no ffmpeg needed)."""
import os
import socket
import struct
import threading
import time


def amf0_string(s):
    b = s.encode()
    return b"\x02" + struct.pack(">H", len(b)) + b


def amf0_number(n):
    return b"\x00" + struct.pack(">d", n)


def amf0_object(d):
    out = b"\x03"
    for k, v in d.items():
        kb = k.encode()
        out += struct.pack(">H", len(kb)) + kb + amf0_string(v)
    return out + b"\x00\x00\x09"


def chunked(csid, msg_type, payload, stream_id=0, chunk_size=128):
    """fmt-0 first chunk, fmt-3 continuation chunks."""
    head = bytes([csid]) + (0).to_bytes(3, "big") + len(payload).to_bytes(3, "big") + bytes([msg_type]) \
        + stream_id.to_bytes(4, "little")
    out = bytearray(head + payload[:chunk_size])
    rest = payload[chunk_size:]
    while rest:
        out += bytes([0xC0 | csid]) + rest[:chunk_size]
        rest = rest[chunk_size:]
    return bytes(out)


def connect_message(app, tc_url):
    payload = amf0_string("connect") + amf0_number(1) + amf0_object({"app": app, "type": "nonprivate",
                                                                      "flashVer": "FMLE/3.0", "tcUrl": tc_url})
    return chunked(3, 20, payload)


def publish_message(stream_name):
    payload = amf0_string("publish") + amf0_number(5) + b"\x05" + amf0_string(stream_name) + amf0_string("live")
    return chunked(4, 20, payload, stream_id=1)


def video_message(size=300):
    return chunked(6, 9, b"\x17" + os.urandom(size - 1), stream_id=1)


class FakeUpstream:
    """Stands in for `ffmpeg -listen`: answers the handshake and records what arrives."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.received = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        data = bytearray()
        self.received.append(data)
        try:
            c0c1 = self._exact(c, 1537)
            c.sendall(b"\x03" + bytes(1536) + c0c1[1:])
            self._exact(c, 1536)
            c.settimeout(3)
            while True:
                part = c.recv(65536)
                if not part:
                    break
                data.extend(part)
        except OSError:
            pass

    @staticmethod
    def _exact(c, n):
        out = bytearray()
        while len(out) < n:
            part = c.recv(n - len(out))
            if not part:
                raise OSError("closed")
            out.extend(part)
        return bytes(out)


def push(port, messages, settle=0.6):
    """A camera pushing: handshake, then the given messages. Returns True if still connected."""
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"\x03" + bytes(8) + os.urandom(1528))
    s0s1s2 = b""
    while len(s0s1s2) < 3073:
        part = s.recv(3073 - len(s0s1s2))
        if not part:
            return False
        s0s1s2 += part
    s.sendall(s0s1s2[1:1537])
    alive = True
    for m in messages:
        try:
            s.sendall(m)
            time.sleep(0.15)
        except OSError:
            alive = False
            break
    time.sleep(settle)
    try:
        s.settimeout(0.3)
        if s.recv(1) == b"":
            alive = False
    except socket.timeout:
        pass
    except OSError:
        alive = False
    s.close()
    return alive
