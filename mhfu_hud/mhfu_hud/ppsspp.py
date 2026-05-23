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
import time
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

    def close(self):
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    # --- request/response --------------------------------------------------

    def _request(self, event: str, **params) -> dict:
        if self._ws is None:
            raise PPSSPPError("not connected")
        ticket = uuid.uuid4().hex[:12]
        try:
            self._ws.send(json.dumps({"event": event, "ticket": ticket,
                                      **params}))
        except (WebSocketException, OSError) as e:
            raise PPSSPPError(f"send {event}: {e}") from e

        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PPSSPPError(f"{event} timed out")
            try:
                raw = self._ws.recv(timeout=remaining)
            except TimeoutError as e:
                raise PPSSPPError(f"{event} timed out") from e
            except (WebSocketException, OSError) as e:
                raise PPSSPPError(f"{event}: {e}") from e
            try:
                msg = json.loads(raw)
            except (ValueError, TypeError):
                continue
            # PPSSPP emits unsolicited input.analog / log / cpu events every
            # frame — skip anything that is not the reply to our ticket.
            if msg.get("ticket") != ticket:
                continue
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
