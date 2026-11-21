"""
RTMP stream-key gatekeeper (RBAC Phase 7, H7).

ffmpeg's built-in RTMP listener accepts any push: a wrong app or stream name only
produces a warning. So the key is checked here, in front of it:

    camera ──► 0.0.0.0:1935  [RTMPKeyGate]  ──► 127.0.0.1:<upstream>  ffmpeg -listen

* The gate answers the RTMP handshake itself, then connects to ffmpeg and replays it.
* It reads the chunk stream and forwards control and command messages (connect,
  createStream, publish ...) so the session can be set up, but no audio, video or
  metadata message is forwarded until a command message has carried the secret key
  (in the server URL / app, or in the "stream key" field - either works).
* A push without the key is closed before a single frame reaches ffmpeg, ANPR or
  counting. Every refusal is logged (address only, never the key).
* After the key is seen the two sockets are piped byte for byte; the frame loop in
  rtmp_service.py is unchanged.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger("rtmp_gate")

HANDSHAKE_SIZE = 1536
VERDICT_TIMEOUT_S = 10.0
MAX_PREFIX_BYTES = 256 * 1024
MEDIA_TYPES = {8, 9, 18, 15, 22}          # audio, video, data/metadata (AMF0/AMF3), aggregate
COMMAND_TYPES = {20, 17}                  # AMF0 / AMF3 command


class ChunkReader:
    """Minimal RTMP chunk-stream parser: yields (raw_chunk_bytes, msg_type, completed_payload)."""

    def __init__(self):
        self.chunk_size = 128
        self.buf = bytearray()
        self.streams: Dict[int, Dict] = {}

    def feed(self, data: bytes):
        self.buf.extend(data)

    def chunks(self):
        while True:
            parsed = self._next()
            if parsed is None:
                return
            yield parsed

    def _next(self) -> Optional[Tuple[bytes, int, Optional[bytes]]]:
        b = self.buf
        if not b:
            return None
        pos = 0
        fmt, csid = b[0] >> 6, b[0] & 0x3F
        pos = 1
        if csid == 0:
            if len(b) < 2:
                return None
            csid, pos = b[1] + 64, 2
        elif csid == 1:
            if len(b) < 3:
                return None
            csid, pos = b[1] + b[2] * 256 + 64, 3
        st = self.streams.setdefault(csid, {"len": 0, "type": 0, "ts_ext": False, "data": bytearray(), "left": 0})
        hdr = {0: 11, 1: 7, 2: 3, 3: 0}[fmt]
        if len(b) < pos + hdr:
            return None
        ts_field = None
        if fmt in (0, 1, 2):
            ts_field = int.from_bytes(b[pos:pos + 3], "big")
        if fmt in (0, 1):
            st["len"] = int.from_bytes(b[pos + 3:pos + 6], "big")
            st["type"] = b[pos + 6]
        pos += hdr
        ext = (ts_field == 0xFFFFFF) if ts_field is not None else st["ts_ext"]
        if ts_field is not None:
            st["ts_ext"] = ext
        if ext:
            if len(b) < pos + 4:
                return None
            pos += 4
        if st["left"] <= 0:
            st["left"] = st["len"]
            st["data"] = bytearray()
        take = min(self.chunk_size, st["left"])
        if len(b) < pos + take:
            return None
        payload = bytes(b[pos:pos + take])
        raw = bytes(b[:pos + take])
        del b[:pos + take]
        st["data"].extend(payload)
        st["left"] -= take
        done = None
        if st["left"] <= 0:
            done = bytes(st["data"])
            if st["type"] == 1 and len(done) >= 4:            # Set Chunk Size
                self.chunk_size = max(1, int.from_bytes(done[:4], "big") & 0x7FFFFFFF)
        return raw, st["type"], done


def _recv_exact(sock: socket.socket, n: int, deadline: float) -> bytes:
    out = bytearray()
    while len(out) < n:
        sock.settimeout(max(0.05, deadline - time.monotonic()))
        part = sock.recv(n - len(out))
        if not part:
            raise ConnectionError("closed during handshake")
        out.extend(part)
    return bytes(out)


def _pipe(src: socket.socket, dst: socket.socket):
    try:
        src.settimeout(None)
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class RTMPKeyGate:
    def __init__(self, key_provider: Callable[[], str], listen_host: str = "0.0.0.0", listen_port: int = 1935,
                 upstream_host: str = "127.0.0.1", upstream_port: int = 19350):
        self.key_provider = key_provider
        self.listen_host, self.listen_port = listen_host, listen_port
        self.upstream = (upstream_host, upstream_port)
        self.refused = 0
        self.accepted = 0
        self._sock: Optional[socket.socket] = None
        self._running = False

    # ------------------------------------------------------------------ server
    def start(self) -> "RTMPKeyGate":
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.listen_host, self.listen_port))
        self._sock.listen(8)
        self.listen_port = self._sock.getsockname()[1]
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True, name="RTMP-Key-Gate").start()
        logger.info(f"RTMP key gate listening on {self.listen_host}:{self.listen_port} -> {self.upstream[0]}:{self.upstream[1]}")
        return self

    def stop(self):
        self._running = False
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass

    def _accept_loop(self):
        while self._running:
            try:
                client, addr = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client, addr), daemon=True, name="RTMP-Key-Gate-Conn").start()

    # ------------------------------------------------------------------ one connection
    def _refuse(self, client: socket.socket, addr, why: str):
        self.refused += 1
        logger.warning(f"[RTMP] refused push from {addr[0]}: {why}")
        try:
            client.close()
        except OSError:
            pass

    def _handle(self, client: socket.socket, addr):
        key = (self.key_provider() or "").encode()
        deadline = time.monotonic() + VERDICT_TIMEOUT_S
        upstream = None
        ok = False
        try:
            c0c1 = _recv_exact(client, 1 + HANDSHAKE_SIZE, deadline)
            if c0c1[0] != 3:
                return self._refuse(client, addr, "not an RTMP client")
            s1 = bytes(8) + os.urandom(HANDSHAKE_SIZE - 8)
            client.sendall(b"\x03" + s1 + c0c1[1:])          # S0 + S1 + S2 (echo of C1)
            _recv_exact(client, HANDSHAKE_SIZE, deadline)    # C2

            upstream = socket.create_connection(self.upstream, timeout=5)
            upstream.sendall(c0c1)
            s0s1s2 = _recv_exact(upstream, 1 + 2 * HANDSHAKE_SIZE, deadline)
            upstream.sendall(s0s1s2[1:1 + HANDSHAKE_SIZE])    # C2 = echo of ffmpeg's S1
            threading.Thread(target=_pipe, args=(upstream, client), daemon=True).start()

            reader = ChunkReader()
            seen = 0
            while True:
                if not key:
                    return self._refuse(client, addr, "no stream key configured")
                client.settimeout(max(0.05, deadline - time.monotonic()))
                data = client.recv(65536)
                if not data:
                    return
                seen += len(data)
                reader.feed(data)
                for raw, mtype, payload in reader.chunks():
                    if mtype in MEDIA_TYPES:
                        return self._refuse(client, addr, "media before a valid stream key")
                    upstream.sendall(raw)
                    if payload is not None and mtype in COMMAND_TYPES and key in payload:
                        self.accepted += 1
                        ok = True
                        logger.info(f"[RTMP] push accepted from {addr[0]}")
                        if reader.buf:
                            upstream.sendall(bytes(reader.buf))
                        _pipe(client, upstream)
                        return
                if seen > MAX_PREFIX_BYTES or time.monotonic() > deadline:
                    return self._refuse(client, addr, "no valid stream key")
        except (OSError, ConnectionError) as e:
            self._refuse(client, addr, f"connection error before a valid stream key ({e.__class__.__name__})")
        finally:
            if upstream is not None and not ok:
                try:
                    upstream.close()
                except OSError:
                    pass
