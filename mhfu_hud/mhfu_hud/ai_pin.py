"""Pinned-write engine for live AI modding.

A pin holds a single (address, kind, value) tuple in memory by writing it
back at a fixed cadence. The engine runs a daemon thread that wakes only
while at least one pin is active — pure-read sessions pay zero overhead.

Cadence: 30 Hz (matches MHFU game-logic rate; the popo_growth PRX mod
proved that any slower lets the engine clobber size-mirror cells mid-cycle).
Each tick takes a snapshot of the pin dict under a lock, releases the
lock, then issues writes outside the critical section so a slow PPSSPP
debugger socket never blocks UI-thread pin/unpin actions.

Pin kinds:
  - u8 / u16 / u32 / f32 — primitive writes at a single address
  - size — writes the same f32 to all four sticky size mirrors of an
    entity (+0x220 / +0x224 / +0x228 / +0x270). The volatile +0x024
    is intentionally skipped (engine re-derives it; see Section 15.16
    of agent_session_log).
  - multi — writes the same primitive value to a list of addresses.

Errors during writes are swallowed per-pin — a bad address must never
take down the writer thread or starve other pins.
"""

from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional


def _pack_vec3(x: float, y: float, z: float) -> bytes:
    return struct.pack("<fff", float(x), float(y), float(z))


PIN_KINDS = ("u8", "u16", "u32", "f32", "size", "multi", "vec3",
             "heading_track")

# 3 Hz cadence. Investigation 2026-05-26 (sweet-spot sweep, snow_quest
# popo) found that AI cells (state, anim_id, heading) HALT the popo
# completely when written at 8-60 Hz — debugger writes appear to land on
# AI-engine frames and trigger an internal reset. At 3 Hz, popo follows
# our heading writes with tracking score 0.86 (committed PURSUE);
# 10-15 Hz produces strong FLEE because natural flee aligns. Slow is
# better for AI override — engine still picks its own state between
# writes, but our heading directs each new state into the chosen
# direction. Size-mirror pins (popo_growth pattern) also work at 3 Hz
# because once written the mirrors stick.
WRITER_HZ = 3.0
_WRITER_DT = 1.0 / WRITER_HZ


@dataclass
class Pin:
    key: str             # unique pin identifier (caller-chosen)
    kind: str            # one of PIN_KINDS
    addr: int            # primary address (or first of `addrs` for multi)
    value: int | float   # value to enforce (or tuple for vec3)
    addrs: list = field(default_factory=list)   # for kind="multi" / "size"
    label: str = ""      # short UI description
    last_error: str = ""
    # heading_track-specific extras. Resolver receives nothing and must
    # return a (ux, uz) tuple — the pin engine reads it on every tick
    # so the heading vec can track a moving target. `entity_addr` is the
    # popo's struct ptr (heading offset is added by the writer).
    entity_addr: int = 0
    resolver: object = None    # callable() -> (ux, uz)
    heading_offset: int = 0    # OFF_M_HEADING (12 bytes — vec3 of f32)


class PinEngine:
    """Threaded write-back engine. Construct with a callable returning
    the live PPSSPPClient (or None when disconnected). start()/stop()
    are idempotent."""

    def __init__(self, client_provider: Callable[[], "object | None"]):
        self._client_provider = client_provider
        self._pins: dict[str, Pin] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()    # signals new pin / shutdown
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._writes_total = 0
        self._errors_total = 0

    # --- lifecycle ---------------------------------------------------------

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="mhfu-hud-ai-pin", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=1.0)
        self._thread = None

    # --- pin API ----------------------------------------------------------

    def pin(self, key: str, kind: str, addr: int, value,
            addrs: list | None = None, label: str = "",
            entity_addr: int = 0, resolver=None,
            heading_offset: int = 0) -> None:
        """Create or replace a pin. Writes start on the next tick."""
        if kind not in PIN_KINDS:
            raise ValueError(f"unknown pin kind: {kind}")
        with self._lock:
            self._pins[key] = Pin(
                key=key, kind=kind, addr=addr, value=value,
                addrs=list(addrs) if addrs else [], label=label,
                entity_addr=entity_addr, resolver=resolver,
                heading_offset=heading_offset)
        self._wake.set()

    def unpin(self, key: str) -> None:
        with self._lock:
            self._pins.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._pins.clear()

    def update_value(self, key: str, value) -> None:
        """Change the value of an existing pin without recreating it."""
        with self._lock:
            p = self._pins.get(key)
            if p is not None:
                p.value = value

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._pins

    def get(self, key: str) -> Optional[Pin]:
        with self._lock:
            p = self._pins.get(key)
            if p is None:
                return None
            return Pin(key=p.key, kind=p.kind, addr=p.addr, value=p.value,
                       addrs=list(p.addrs), label=p.label,
                       last_error=p.last_error)

    def snapshot(self) -> list[Pin]:
        with self._lock:
            return [Pin(key=p.key, kind=p.kind, addr=p.addr, value=p.value,
                        addrs=list(p.addrs), label=p.label,
                        last_error=p.last_error)
                    for p in self._pins.values()]

    # --- one-shot writes (not pinned — fire once + return) -----------------

    def oneshot_write(self, addr: int, kind: str, value) -> bool:
        """Fire a single write outside the pin loop. Returns True on success.

        Used for buttons like "Force flee" or "Apply state literal" — the
        write should land immediately and survive only as long as the
        game doesn't overwrite it. Caller decides whether to also pin.
        """
        c = self._client_provider()
        if c is None:
            return False
        try:
            self._write_one(c, addr, kind, value)
            self._writes_total += 1
            return True
        except Exception:
            self._errors_total += 1
            return False

    def oneshot_multi(self, addrs: list, kind: str, value) -> int:
        """Fire several primitive writes (same kind+value, distinct addrs).
        Returns the number of writes that succeeded. Useful for the
        seed-pair literal write (0x324 + 0x326)."""
        c = self._client_provider()
        if c is None:
            return 0
        ok = 0
        for a in addrs:
            try:
                self._write_one(c, a, kind, value)
                ok += 1
                self._writes_total += 1
            except Exception:
                self._errors_total += 1
        return ok

    # --- stats ------------------------------------------------------------

    @property
    def writes_total(self) -> int:
        return self._writes_total

    @property
    def errors_total(self) -> int:
        return self._errors_total

    def count(self) -> int:
        with self._lock:
            return len(self._pins)

    # --- thread body ------------------------------------------------------

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                pins = list(self._pins.values())
            if not pins:
                # Park until something pins or we're asked to stop.
                self._wake.wait(0.25)
                self._wake.clear()
                continue
            c = self._client_provider()
            if c is None:
                # Disconnected — wait a beat and retry rather than spinning.
                self._stop.wait(0.5)
                continue
            t0 = time.monotonic()
            for p in pins:
                try:
                    self._write_pin(c, p)
                    self._writes_total += 1
                    if p.last_error:
                        # Clear stale error on first successful write back.
                        with self._lock:
                            live = self._pins.get(p.key)
                            if live is not None:
                                live.last_error = ""
                except Exception as e:
                    self._errors_total += 1
                    with self._lock:
                        live = self._pins.get(p.key)
                        if live is not None:
                            live.last_error = str(e)[:64]
            elapsed = time.monotonic() - t0
            self._stop.wait(max(0.0, _WRITER_DT - elapsed))

    # --- write primitives -------------------------------------------------

    @staticmethod
    def _write_one(client, addr: int, kind: str, value) -> None:
        if kind == "u8":
            client.write_u8(addr, int(value) & 0xFF)
        elif kind == "u16":
            client.write_u16(addr, int(value) & 0xFFFF)
        elif kind == "u32":
            client.write_u32(addr, int(value) & 0xFFFFFFFF)
        elif kind == "f32":
            client.write_f32(addr, float(value))
        else:
            raise ValueError(f"_write_one cannot handle kind {kind}")

    def _write_pin(self, client, pin: Pin) -> None:
        if pin.kind in ("u8", "u16", "u32", "f32"):
            self._write_one(client, pin.addr, pin.kind, pin.value)
            return
        if pin.kind == "size":
            # All four sticky size mirrors at +0x220 / +0x224 / +0x228 / +0x270
            # written together — Section 15.16 / popo_growth lesson.
            v = float(pin.value)
            for a in pin.addrs:
                client.write_f32(a, v)
            return
        if pin.kind == "multi":
            for a in pin.addrs:
                # Default to u32 for multi; if the caller stashed a hint
                # like "_kind=u16" via label, decode that.
                client.write_u32(a, int(pin.value) & 0xFFFFFFFF)
            return
        if pin.kind == "vec3":
            # Static heading-vec write — value is (x, y, z) tuple.
            x, y, z = pin.value
            client.write_memory(pin.addr, _pack_vec3(x, y, z))
            return
        if pin.kind == "heading_track":
            # Recompute toward-target unit vector at write time so the
            # heading tracks a moving target. Resolver returns (ux, uz).
            try:
                ux, uz = pin.resolver()
            except Exception as e:
                pin.last_error = f"resolver: {e}"[:64]
                return
            client.write_memory(pin.entity_addr + pin.heading_offset,
                                 _pack_vec3(ux, 0.0, uz))
            return
        raise ValueError(f"unhandled pin kind: {pin.kind}")
