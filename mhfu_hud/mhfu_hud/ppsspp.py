"""Standalone, read-only PPSSPP debugger client.

A self-contained copy of the WebSocket debugger protocol — the HUD does not
import the project's `mhfu_bot` toolkit. Deliberately READ-ONLY: it exposes
memory reads only, never input injection, breakpoints, or memory writes.
Debugger memory reads do not pause emulation, so polling cannot influence
gameplay.
"""

import base64
import json
import struct
import threading
import urllib.request
import uuid
from typing import Optional, Tuple

from websockets.sync.client import connect as ws_connect
from websockets.exceptions import WebSocketException

DISCOVERY_URL = "https://report.ppsspp.org/match/list?match=debugger"


class PPSSPPError(RuntimeError):
    """Any connection / protocol / read failure."""


class PPSSPPClient:
    """Synchronous request/response client for one PPSSPP debugger session."""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None,
                 timeout: float = 4.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._ws = None
        # Background recv-drain — PPSSPP emits unsolicited input.analog / log
        # / cpu events every frame; if nothing is reading the socket between
        # polls the send buffer fills and PPSSPP's main thread blocks on
        # emit_event (visible as the game ignoring input + savestate loads
        # hanging). The drain thread keeps the socket flushed and parks
        # ticket replies in `_pending` so `_request` can pick them up.
        self._recv_thread: Optional[threading.Thread] = None
        self._stop_recv = threading.Event()
        self._pending: dict = {}                # ticket -> {event, result}
        self._pending_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._recv_error: Optional[Exception] = None

    # --- connection --------------------------------------------------------

    @staticmethod
    def discover(timeout: float = 3.0) -> Optional[Tuple[str, int]]:
        """Return (host, port) of a running PPSSPP debugger, or None.

        PPSSPP advertises its debugger on a dynamic port via this endpoint.
        A non-default User-Agent is required (urllib's default gets a 403).
        """
        req = urllib.request.Request(
            DISCOVERY_URL, headers={"User-Agent": "mhfu-hud/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                entries = json.loads(r.read())
        except Exception:
            return None
        for entry in entries or []:
            ip = entry.get("ip", "")
            if ip and ":" not in ip and entry.get("p"):
                return ip, int(entry["p"])
        return None

    def connect(self):
        """Connect, auto-discovering host/port if not supplied. Raises on failure."""
        host, port = self.host, self.port
        if not host or not port:
            found = self.discover()
            if not found:
                raise PPSSPPError(
                    "no PPSSPP debugger advertised — start PPSSPP and enable "
                    "Settings > Tools > Developer Tools > Allow remote debugger")
            host, port = found
        self.host, self.port = host, port
        uri = f"ws://{host}:{port}/debugger"
        try:
            self._ws = ws_connect(uri, max_size=2 ** 24,
                                  open_timeout=self.timeout)
        except (OSError, WebSocketException) as e:
            self._ws = None
            raise PPSSPPError(f"connect to {uri} failed: {e}") from e
        self._stop_recv.clear()
        self._recv_error = None
        self._recv_thread = threading.Thread(
            target=self._recv_loop, name="mhfu-hud-ws-drain", daemon=True)
        self._recv_thread.start()

    def close(self):
        self._stop_recv.set()
        ws, self._ws = self._ws, None
        # Wake parked waiters *first* so the reader thread can exit its
        # in-flight _request immediately, before we touch the socket.
        with self._pending_lock:
            for slot in self._pending.values():
                slot["event"].set()
            self._pending.clear()
        if ws is not None:
            # close_socket() drops the underlying TCP socket without
            # doing the WebSocket close handshake. The full close() would
            # block on a peer ack — and when PPSSPP is itself shutting
            # down the ack never comes, hanging both processes until
            # force-quit. Force-shutdown is what we actually want here.
            try:
                ws.close_socket()
            except Exception:
                pass
            try:
                ws.close()
            except Exception:
                pass
        if self._recv_thread is not None and \
                self._recv_thread is not threading.current_thread():
            self._recv_thread.join(timeout=1.0)
            self._recv_thread = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._recv_error is None

    # --- background drain --------------------------------------------------

    def _recv_loop(self):
        """Continuously drain the WebSocket. Park ticket replies into
        `_pending`; discard everything else."""
        while not self._stop_recv.is_set():
            ws = self._ws
            if ws is None:
                break
            try:
                raw = ws.recv(timeout=0.5)
            except TimeoutError:
                continue
            except (WebSocketException, OSError) as e:
                self._recv_error = e
                break
            if raw is None or raw == "":
                continue
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            ticket = msg.get("ticket")
            if not ticket:
                # unsolicited notification — discard.
                continue
            with self._pending_lock:
                slot = self._pending.pop(ticket, None)
            if slot is not None:
                slot["result"] = msg
                slot["event"].set()
            # else: late reply for a request that already timed out — drop.
        # on exit, fail any still-pending waiters so they don't hang.
        with self._pending_lock:
            for slot in self._pending.values():
                slot["event"].set()
            self._pending.clear()

    # --- request/response --------------------------------------------------

    def _request(self, event: str, **params) -> dict:
        if self._ws is None:
            raise PPSSPPError("not connected")
        if self._recv_error is not None:
            raise PPSSPPError(f"recv loop dead: {self._recv_error}")

        ticket = uuid.uuid4().hex[:12]
        evt = threading.Event()
        slot = {"event": evt, "result": None}
        with self._pending_lock:
            self._pending[ticket] = slot

        payload = json.dumps({"event": event, "ticket": ticket, **params})
        try:
            with self._send_lock:
                self._ws.send(payload)
        except (WebSocketException, OSError) as e:
            with self._pending_lock:
                self._pending.pop(ticket, None)
            raise PPSSPPError(f"send {event}: {e}") from e

        if not evt.wait(self.timeout):
            with self._pending_lock:
                self._pending.pop(ticket, None)
            raise PPSSPPError(f"{event} timed out")
        msg = slot["result"]
        if msg is None:
            # recv loop died while we were waiting.
            raise PPSSPPError(f"{event} aborted: {self._recv_error}")
        if msg.get("event") == "error":
            raise PPSSPPError(msg.get("message", "debugger error"))
        return msg

    # --- read-only API surface --------------------------------------------

    def game_status(self) -> dict:
        return self._request("game.status")

    def read_memory(self, address: int, size: int) -> bytes:
        msg = self._request("memory.read", address=address, size=size)
        b64 = msg.get("base64", "")
        return base64.b64decode(b64) if b64 else b""

    def read_u8(self, address: int) -> int:
        return self._request("memory.read_u8", address=address).get("value", 0)

    def read_u16(self, address: int) -> int:
        return self._request("memory.read_u16", address=address).get("value", 0)

    def read_u32(self, address: int) -> int:
        return self._request("memory.read_u32", address=address).get("value", 0)

    def read_f32(self, address: int) -> float:
        data = self.read_memory(address, 4)
        return struct.unpack("<f", data)[0] if len(data) == 4 else 0.0
