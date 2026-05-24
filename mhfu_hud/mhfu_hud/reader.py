"""Background memory poller.

Runs in its own daemon thread. Connects to PPSSPP, polls a small set of
batched memory regions at a fixed rate, parses them into a GameSnapshot, and
publishes the latest snapshot. The pygame thread reads `reader.snapshot`
every frame, so render rate and poll rate are decoupled.

Reads are batched into a handful of region reads to keep WebSocket
round-trips low. Debugger reads never pause emulation; the client is
read-only, so polling cannot affect gameplay.
"""

import math
import struct
import threading
import time

from . import addresses as A
from .calibration import Calibration
from .monster_db import identify
from .ppsspp import PPSSPPClient, PPSSPPError
from .state import BagSlot, Context, GameSnapshot, MonsterHUD, PlayerHUD, Vec3

# The snow map is currently the only one with calibrated anchors. When
# the section tracker can't tell which map we're on (no live indicator
# yet), it assumes this slug — matches the active HUD default.
_DEFAULT_QUEST_MAP_SLUG = "snowy_mountains"

# Anchor-snap distance used when classifying the cam target right after
# a gate transition. Spawn cells observed in the discovery run sat
# within ~30 units of their nominal anchor — 1500 is generous slack.
_SECTION_SNAP_DIST = 1500.0

# Wait this long (seconds) after screen_state returns to 17 before we
# trust cam_target as "settled on a spawn point" enough to snap.
_SECTION_SETTLE_SECS = 0.6

# Fallback bar maxima when a true cap has not been observed yet. The reader
# tracks a running max from live values and prefers that.
HP_MAX_FALLBACK = 150
STAMINA_MAX_FALLBACK = 320
# Tight plausible upper bounds for the live cells. A read above these is
# treated as zone-load garbage and skipped — otherwise a transient huge
# value latches into the running max and never goes back down.
HP_MAX_SANE = 1000
STAMINA_MAX_SANE = 2000


def _vec3(buf: bytes, off: int) -> Vec3:
    x, y, z = struct.unpack_from("<fff", buf, off)
    return Vec3(x, y, z)


def _finite(v: Vec3) -> bool:
    for c in (v.x, v.y, v.z):
        if c != c or abs(c) > 1e7:   # NaN or absurd magnitude
            return False
    return True


class MemoryReader:
    """Owns the PPSSPP connection and the polling thread."""

    def __init__(self, host=None, port=None, poll_hz: float = 3.0):
        self.host = host
        self.port = port
        self.poll_interval = 1.0 / max(0.5, poll_hz)
        self._client = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._snapshot = GameSnapshot()
        self._poll_count = 0
        self._hp_max = 0
        self._stamina_max = 0
        self._game_title = ""
        self._game_loaded = False
        # Section tracker — see _update_section. Survives across polls;
        # reset by calling reset_section_tracking() from the HUD.
        self._calib = Calibration()
        self._tracked_section = None
        self._tracked_section_source = "init"
        self._last_screen_state = -1
        self._settle_at = 0.0
        self._pending_initial_snap = True

    # --- lifecycle ---------------------------------------------------------

    def start(self):
        self._thread = threading.Thread(target=self._run, name="mhfu-reader",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        # Close the WebSocket FIRST. The reader thread may be mid-poll
        # blocked in PPSSPPClient._request waiting on a ticket reply; if
        # we joined first we'd burn up to `client.timeout` seconds waiting
        # for it. Closing the client wakes parked waiters and the reader
        # thread exits within one loop iteration.
        self._stop.set()
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)

    @property
    def snapshot(self) -> GameSnapshot:
        with self._lock:
            return self._snapshot

    def _publish(self, snap: GameSnapshot):
        with self._lock:
            self._snapshot = snap

    # --- thread body -------------------------------------------------------

    def _run(self):
        while not self._stop.is_set():
            if self._client is None or not self._client.connected:
                self._connect_loop()
                if self._stop.is_set():
                    break
            cycle_start = time.monotonic()
            try:
                snap = self._poll()
                self._publish(snap)
            except PPSSPPError as e:
                if self._client:
                    self._client.close()
                self._client = None
                self._publish(GameSnapshot(
                    connected=False, context=Context.DISCONNECTED,
                    status_text=f"connection lost: {e}"))
            elapsed = time.monotonic() - cycle_start
            self._stop.wait(max(0.0, self.poll_interval - elapsed))

    def _connect_loop(self):
        attempt = 0
        while not self._stop.is_set():
            attempt += 1
            self._publish(GameSnapshot(
                connected=False, context=Context.DISCONNECTED,
                status_text=f"waiting for PPSSPP debugger (attempt {attempt})…"))
            client = PPSSPPClient(self.host, self.port)
            try:
                client.connect()
                self.host, self.port = client.host, client.port
                self._client = client
                return
            except PPSSPPError:
                client.close()
                self._stop.wait(2.0)

    # --- one poll cycle ----------------------------------------------------

    def _poll(self) -> GameSnapshot:
        c = self._client
        t0 = time.monotonic()
        self._poll_count += 1

        # game.status is comparatively slow and rarely changes — refresh it
        # on the first poll and every ~2 s, not every cycle.
        if self._poll_count == 1 or self._poll_count % 20 == 0:
            self._game_title, self._game_loaded = self._read_game_status(c)
        title, game_loaded = self._game_title, self._game_loaded
        if not game_loaded:
            return self._meta(GameSnapshot(
                connected=True, context=Context.BOOT, game_title=title,
                status_text="PPSSPP connected — no game running"), t0)

        # Region A: low globals 0x08A8C6E0 .. 0x08A8DE4C+4
        a_base = A.SCENE_OBJECT_PTR
        a = c.read_memory(a_base, A.MAP_SECTION - a_base + 4)
        scene_ptr = struct.unpack_from("<I", a, 0)[0]
        screen_state = a[A.SCREEN_STATE - a_base]
        stamina = struct.unpack_from("<H", a, A.STAMINA - a_base)[0]
        map_section = a[A.MAP_SECTION - a_base]
        # Region A2: area_index (the real visible-section ID). Sits ~6 KiB
        # above the previous region — separate read keeps region A small
        # so we don't drag a full page worth of bytes per poll.
        area_index = c.read_u16(A.AREA_INDEX)

        quest_timer = c.read_u32(A.QUEST_TIMER)
        carve = c.read_u8(A.CARVE_COUNT)

        # Region B: player heap block — one read covers current HP
        # (0x090B3724), recov+max pair (0x090B385C..0x090B385F), and the
        # weapon-drawn flag (0x090B3A52). Coalesced into a single fetch
        # so the poll cycle stays cheap on the PPSSPP debugger socket
        # (a flood of small reads visibly hitches emulation).
        b_base = 0x090B3700
        b_size = 0x400
        b = c.read_memory(b_base, b_size)
        hp = struct.unpack_from("<H", b, A.PLAYER_HP - b_base)[0]
        hp_recov, hp_max_live = struct.unpack_from(
            "<HH", b, A.PLAYER_HP_RECOV - b_base)
        weapon_drawn = bool(b[A.WEAPON_DRAWN - b_base])

        # Bag — 24-slot in-quest inventory. One contiguous read (96 B)
        # at BAG_BASE; each slot decodes as u32 LE
        #     { item_id u16, count u8, flags u8 }.
        # Pinned 2026-05-24 by diffing `bag_empty` (all zero) against
        # `bag_one_paintball` (slot 0 = paintball, count 1).
        bag_raw = c.read_memory(A.BAG_BASE, A.BAG_SPAN)
        bag = []
        for i in range(A.BAG_SLOT_COUNT):
            raw = struct.unpack_from("<I", bag_raw, i * 4)[0]
            bag.append(BagSlot(
                idx=i,
                item_id=raw & 0xFFFF,
                count=(raw >> 16) & 0xFF,
                flags=(raw >> 24) & 0xFF,
            ))

        # Region C: player struct (vtable + position + rotation)
        pc = c.read_memory(A.PLAYER_STRUCT, A.PLAYER_STRUCT_SPAN)
        p_vtable = struct.unpack_from("<I", pc, 0)[0]
        p_loaded = p_vtable == A.PLAYER_VTABLE
        pos_local = _vec3(pc, A.OFF_P_POSITION)
        facing = None
        if p_loaded:
            rot = struct.unpack_from("<12f", pc, A.OFF_P_ROT)
            # Approx heading from the rotation basis. Convention not yet
            # confirmed in RE work — treated as a best-effort value.
            facing = math.atan2(rot[8], rot[10])

        # Region D: camera (target == player world position)
        d = c.read_memory(A.CAM_TARGET, A.CAM_SPAN)
        cam_target = _vec3(d, 0)
        cam_offset = _vec3(d, A.CAM_OFFSET - A.CAM_TARGET)

        # Only trust the live cells while the game is in a stable in-area
        # state (screen_state==17) with the player struct loaded. During
        # a zone-load (screen_state flips 17->1->17) the stats cells hold
        # transitional garbage; latching the running max to that value
        # leaves the bar broken until process restart.
        stable = (screen_state == 17) and p_loaded
        if stable and 0 < hp_max_live <= HP_MAX_SANE:
            self._hp_max = max(self._hp_max, hp_max_live)
        if stable and 0 < stamina <= STAMINA_MAX_SANE:
            self._stamina_max = max(self._stamina_max, stamina)
        hp_max = hp_max_live if 0 < hp_max_live <= HP_MAX_SANE else self._hp_max
        hp_max = hp_max or HP_MAX_FALLBACK
        # Reject obviously bogus live readings for the rendered bar — show
        # the last known good value instead of a 5-digit "current" stamina.
        stamina_render = stamina if 0 <= stamina <= STAMINA_MAX_SANE else None
        hp_render = hp if 0 <= hp <= HP_MAX_SANE else None

        player = PlayerHUD(
            loaded=p_loaded,
            pos_world=cam_target,
            pos_local=pos_local,
            facing_rad=facing,
            hp=hp_render if p_loaded else None,
            hp_recov=hp_recov if p_loaded and 0 <= hp_recov <= HP_MAX_SANE
                     else None,
            hp_max=hp_max,
            stamina=stamina_render,
            stamina_max=self._stamina_max or STAMINA_MAX_FALLBACK,
            weapon_drawn=weapon_drawn if p_loaded else None,
            bag=bag if p_loaded else [],
        )

        context = self._classify(screen_state, map_section, p_loaded, title)

        monsters = []
        if context == Context.QUEST:
            monsters = self._read_monsters(c)

        # Section tracking — primary path is the area_index lookup;
        # falls back to the gate-detected anchor snap when area_index is
        # not yet in the learnt table.
        self._update_section(screen_state, cam_target, p_loaded, context,
                             area_index)

        return self._meta(GameSnapshot(
            connected=True, context=context, game_title=title,
            status_text="ok",
            screen_state=screen_state, map_section=map_section,
            area_index=area_index,
            scene_object_ptr=scene_ptr,
            tracked_section=self._tracked_section,
            tracked_section_source=self._tracked_section_source,
            quest_timer_frames=quest_timer, carve_count=carve,
            player=player, monsters=monsters,
            camera_target=cam_target, camera_offset=cam_offset), t0)

    def _update_section(self, screen_state, cam_target, p_loaded, context,
                        area_index):
        """Move the tracked-section state machine forward.

        Primary signal: area_index (u16 at 0x08B0C7DC). Looked up in the
        learnt area_index -> labelled section table every poll. While in
        a quest, this gives the visible section directly — no anchor
        snapping needed.

        Secondary signal: gate transition (screen_state 17 -> !17 -> 17).
        When the new area_index is *not* in the learnt table, we snap to
        the nearest registered entry-point anchor and record the
        (area_index -> section) pair so subsequent visits resolve
        instantly without geometry.

        An override set via set_section_override() takes priority over
        both until the user clears it.
        """
        ls, ss = self._last_screen_state, screen_state
        if context != Context.QUEST:
            self._last_screen_state = ss
            return
        if self._tracked_section_source == "override":
            self._last_screen_state = ss
            return

        # Primary: area_index lookup every poll.
        if ss == 17 and area_index is not None:
            sec, found = self._calib.section_from_area_index(
                _DEFAULT_QUEST_MAP_SLUG, area_index)
            if found:
                self._tracked_section = sec
                self._tracked_section_source = "area_index"

        now = time.monotonic()
        # Secondary: gate transition. Schedule a settle-then-snap so we
        # can learn this area_index if it's novel.
        if ls != -1 and ls != 17 and ss == 17:
            self._settle_at = now + _SECTION_SETTLE_SECS
        elif self._pending_initial_snap and ss == 17 and p_loaded:
            self._settle_at = now + _SECTION_SETTLE_SECS
            self._pending_initial_snap = False

        if self._settle_at and now >= self._settle_at:
            sec, dist = self._calib.section_from_world(
                _DEFAULT_QUEST_MAP_SLUG, cam_target.x, cam_target.z,
                max_dist=_SECTION_SNAP_DIST)
            if sec is not None:
                # Learn the area_index <-> section pairing if novel.
                if (area_index is not None and
                        not self._calib.section_from_area_index(
                            _DEFAULT_QUEST_MAP_SLUG, area_index)[1]):
                    if self._calib.learn_area_index(
                            _DEFAULT_QUEST_MAP_SLUG, area_index, sec):
                        # Persist the new mapping so subsequent runs and
                        # tools see it.
                        self._calib.save()
                if (self._tracked_section_source != "area_index"
                        or self._tracked_section is None):
                    self._tracked_section = sec
                    self._tracked_section_source = "transition"
            self._settle_at = 0.0

        self._last_screen_state = ss

    def reset_section_tracking(self):
        """Force a re-snap on the next stable poll. Called by the HUD
        when the user explicitly drops the section override."""
        self._tracked_section = None
        self._tracked_section_source = "init"
        self._pending_initial_snap = True
        self._settle_at = 0.0

    def set_section_override(self, section):
        """Manual override from the HUD calibration mode."""
        self._tracked_section = int(section) if section is not None else None
        self._tracked_section_source = "override"
        self._pending_initial_snap = False
        self._settle_at = 0.0

    def _meta(self, snap: GameSnapshot, t0: float) -> GameSnapshot:
        snap.poll_latency_ms = (time.monotonic() - t0) * 1000.0
        snap.poll_count = self._poll_count
        snap.timestamp = time.time()
        return snap

    # --- sub-readers -------------------------------------------------------

    @staticmethod
    def _read_game_status(c: PPSSPPClient):
        try:
            gs = c.game_status()
        except PPSSPPError:
            return "", False
        game = gs.get("game") or {}
        title = game.get("title") or gs.get("title") or ""
        game_id = game.get("id") or gs.get("id") or ""
        return title, bool(game_id)

    @staticmethod
    def _classify(screen_state, map_section, player_loaded, title) -> Context:
        if screen_state == 17:
            if map_section == A.VILLAGE_MAP_SECTION:
                return Context.VILLAGE
            return Context.QUEST
        if screen_state == 1:
            # 1 is both 'main menu' and 'zone-load in progress'
            return Context.LOADING if player_loaded else Context.MENU
        if screen_state in (0, 2):
            return Context.BOOT
        if screen_state == 4:
            return Context.MENU
        # any other in-game value — treat as a quest area
        return Context.QUEST

    def _read_monsters(self, c: PPSSPPClient):
        out = []
        try:
            ea = c.read_memory(A.ENTITY_ARRAY, A.ENTITY_MAX_SLOTS * 4)
        except PPSSPPError:
            return out
        ptrs = struct.unpack_from("<%dI" % A.ENTITY_MAX_SLOTS, ea, 0)
        # Slot 0 never holds the player (it is a stale code address) — skip it.
        # The registry is sparse: when a monster despawns its slot zeroes
        # but later slots can still be live. Walk every slot and skip
        # invalid entries instead of breaking on the first zero.
        for slot in range(1, A.ENTITY_MAX_SLOTS):
            ptr = ptrs[slot]
            if ptr == 0 or not A.in_ram(ptr):
                continue
            try:
                mb = c.read_memory(ptr, A.MONSTER_STRUCT_SPAN)
            except PPSSPPError:
                continue
            if len(mb) < A.MONSTER_STRUCT_SPAN:
                continue
            m = self._parse_monster(slot, ptr, mb)
            if m is not None:
                out.append(m)
        return out

    def _parse_monster(self, slot, ptr, mb):
        vtable = struct.unpack_from("<I", mb, A.OFF_M_VTABLE)[0]
        if not A.looks_like_vtable(vtable):
            return None
        pos = _vec3(mb, A.OFF_M_POSITION)
        if not _finite(pos):
            return None
        hp = struct.unpack_from("<H", mb, A.OFF_M_HP)[0]
        type_byte = mb[A.OFF_M_TYPE]
        entity_id = mb[A.OFF_M_ENTITY_ID]
        ai_behav = struct.unpack_from("<H", mb, A.OFF_M_AI_BEHAV)[0]
        ai_324 = struct.unpack_from("<H", mb, A.OFF_M_AI_324)[0]
        ai_32c = struct.unpack_from("<H", mb, A.OFF_M_AI_32C)[0]
        size_scale = struct.unpack_from("<f", mb, A.OFF_M_SIZE_SCALE)[0]
        # Reject NaN / absurd values — render as None so the panel can
        # show "?" rather than burning a slot with garbage.
        if not (size_scale == size_scale and 0.05 < size_scale < 10.0):
            size_scale = None
        name, slug = identify(type_byte)
        category = A.monster_category(vtable)
        # Tigrex was found with a "Tigrex"-named type but the same struct
        # layout as small monsters — the docs warn that 0x1E8 varies by
        # state. If category disagrees with the name, defer to category.
        if category == "big" and name.startswith("Unknown"):
            name = A.MONSTER_VTABLE_BIG.get(vtable, name)
            slug = name.lower()
        return MonsterHUD(
            slot=slot, ptr=ptr, entity_id=entity_id, type_byte=type_byte,
            pos=pos, hp=hp, ai_behavior=ai_behav, ai_324=ai_324,
            ai_32c=ai_32c, vtable=vtable, category=category,
            name=name, icon_slug=slug, hp_max=hp, size_scale=size_scale)
