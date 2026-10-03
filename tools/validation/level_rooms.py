#!/usr/bin/env python3
"""level_rooms.py — decode a stage's room table, room headers and sprite lists.

Read-only ROM analysis. Answers the question a guest-memory watchpoint cannot:
*which rooms does this stage have, and what is in each of them?* The recompiler
is not involved; everything here is a static decode of the cartridge image,
so a wrong answer is a decode bug and not a game/recompiler behaviour.

Decoded from the decompilation, not guessed:

* `func_806B410` (`asm/disasm_0x06AF4C.s:563`) is the room-header loader:

      r1 = sUnk_878F280            @ .L_6b474   u32 index of level blocks
      r0 = gUnk_3000023            @ .L_6b478   which level block
      r1 = gCurrentRoom            @ .L_6b47c
      r2 = sUnk_878F280[gUnk_3000023]           u32 -> first RoomHeader
      r1 = r2 + gCurrentRoom * 0x2C              sizeof(struct RoomHeader)

  so the level's rooms are a flat array of 0x2C-byte headers, and
  `gUnk_3000023` selects the level.

* `struct RoomHeader` (`include/global_data.h:88`) is 0x2C bytes:

      +0x00 u8  tileset            +0x18 u8  cameraControl
      +0x01 u8  bg0Param           +0x19 u8  layer3Scrolling
      +0x02 u8  bg1Param           +0x1A u8  bgPriorityAlpha
      +0x03 u8  bg2Param           +0x1C u32 pHardSpriteData
      +0x04 u8  bg3Param           +0x20 u32 pNormalSpriteData
      +0x08 u32 pBg0Data           +0x24 u32 pSHardSpriteData
      +0x0C u32 pBg1Data           +0x28 u8  raster
      +0x10 u32 pBg2Data           +0x29 u8  water
      +0x14 u32 pBg3Data           +0x2A u16 musicVolume

* Sprite lists are 3-byte entries `[y, x, spawnId]` terminated by `FF FF FF`.
  The order was *not* taken on trust: level 1 room 0's hard and normal lists are
  the same pointer and end exactly where `pBg1Data` begins — 3 entries plus the
  3-byte terminator is 12 bytes, and `0x085991DC - 0x085991D0 == 12`. The three
  triples are `0F 1A 08`, `0F 1F 11`, `13 07 14`. Reading them as
  `[spawn, y, x]` yields spawn 0x0F at block (26, 8), which no live sprite
  matches; reading them as `[y, x, spawn]` yields spawn 0x08 at block (15, 26),
  which is the live `PSPRITE_SWITCH` the runtime reports at x=1696 y=1024, and
  spawn 0x11 at block (15, 31) is the live vortex at x=2016 y=1024 — with
  `x = block*64 + 32` and `y = block*64 + 64`. Two independent live sprites
  matching is the evidence for the field order. `func_801E060`
  (`asm/disasm_sprite.s:1325-1379`) copies the list three bytes at a time and
  tests `FF` on byte 0, and `func_801E0EC` reads the id from
  `gUnk_3000964 + 2` — byte 2 is the id, byte 0 is y.

* `func_801E0EC` (`asm/disasm_sprite.s:1407-1519`) is the spawn-id -> sprite-type
  translation, and it is *not* a single flat table:

      r0 = spawnId                                  @ gUnk_3000964 + 2, stride 3
      cmp r0, #16 ; bls .L_1e178
      sub r0, #1                                   @ small ids:  id = spawnId - 1
      strb r0, [sprite, #0x17]                     @ gSpriteData[].globalID
      b   .L_1e1b0
  .L_1e178 / the >=17 arm instead does

      r1 = spawnId - 17
      sprite[0x19] = gUnk_3000544[r1]               @ IWRAM 0x03000544
      globalID     = gUnk_3000524[r1]               @ IWRAM 0x03000544 - 0x20

  Both tables are 32 bytes of IWRAM that are rewritten per level
  (`asm/disasm_sprite.s:1238`, `asm/sprite_ai/disasm_bowler.s:685`) and saved in
  the save file (`asm/disasm_save_file.s:976/978/1599/1601`), so the high ids can
  only be named from a guest snapshot of the level in question — hence `--iwram`.
  The low arm is confirmed against two independent live sprites: spawn 0x08 -> id
  7 = `PSPRITE_SWITCH` and spawn 0x11 -> `gUnk_3000524[0] = 0x29` = 41 =
  `PSPRITE_VORTEX`, both of which the runtime reports for that room.

Usage
    python tools/validation/level_rooms.py --rom "<rom.gba>" --level 0
    python tools/validation/level_rooms.py --rom "<rom.gba>" --level 0 --room 0
    python tools/validation/level_rooms.py --rom "<rom.gba>" --levels
    python tools/validation/level_rooms.py --rom "<rom.gba>" --level 0 \
        --iwram logs/routes/obs-explore/obs-explore-iwram-f011601.bin
    python tools/validation/level_rooms.py --rom "<rom.gba>" \
        --check-snapshot logs/routes/obs-explore/obs-explore-iwram-f011601.bin

`--check-snapshot` needs no `--level`: it reads `gUnk_3000023` and `gCurrentRoom`
out of the snapshot and therefore always checks the room the guest was actually in.

The ROM is addressed at 0x08000000; file offset = guest_addr - ROM_BASE.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

ROM_BASE = 0x08000000
ROM_END = 0x08800000
IWRAM_BASE = 0x03000000

# gUnk_3000023 -> u32 -> first struct RoomHeader.  See func_806B410.
LEVEL_TABLE = 0x0878F280

# struct RoomHeader (global_data.h:88)
HEADER_SIZE = 0x2C
# struct PersistentSpriteData is 16 rooms x 64 slots; gCurrentRoom indexes it.
MAX_ROOMS_HINT = 64

# gSpriteData slot stride used by func_806E3BC's callers, and the live sprite
# fields this decode reports, kept in one place so the numbers stay in sync.
SPRITE_ENTRY_SIZE = 3
SPRITE_LIST_TERMINATOR = b"\xff\xff\xff"

X_ORIGIN, X_SCALE = 32, 64
Y_ORIGIN, Y_SCALE = 64, 64

# IWRAM globals the decode needs from a guest snapshot (linker.ld).
IWRAM_ROOM_HEADER = 0x03000074  # struct RoomHeader, copied by func_806B410
IWRAM_STAGE = 0x03000023  # gUnk_3000023, which level block
IWRAM_ROOM = 0x03000024  # gCurrentRoom
IWRAM_SPAWN_TO_TYPE = 0x03000524  # gUnk_3000524, 32 bytes
IWRAM_SPAWN_TO_POSE = 0x03000544  # gUnk_3000544, 32 bytes
SPAWN_TABLE_LEN = 32

# A room-table spawn id at or below this is translated arithmetically by
# func_801E0EC (globalID = spawnId - 1); above it the level's own IWRAM table
# decides, so it can only be named from a snapshot of that level.
SPAWN_ID_INLINE_MAX = 16

DEFAULT_SPRITE_HEADER = "third_party/lilDavid-warioland4/include/sprite.h"

_ENUM_RE = re.compile(
    r"enum\s+PrimarySpriteID\s*\{(?P<body>.*?)\n\}", re.DOTALL
)
_ENUM_ITEM_RE = re.compile(r"^\s*(?P<name>PSPRITE_[A-Za-z0-9_]+)\s*(?:=\s*(?P<value>0x[0-9A-Fa-f]+|\d+))?\s*,?",
                          re.MULTILINE)


def load_primary_sprite_ids(header_path: str) -> dict[int, str]:
    """`enum PrimarySpriteID` from the decompilation, as {id: name}.

    The names come from the reference source, not from a table typed into this
    tool, so they cannot drift from the enum the rest of the project uses.
    """
    try:
        text = Path(header_path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        die(f"cannot read {header_path}: {exc}")
    match = _ENUM_RE.search(text)
    if not match:
        die(f"no `enum PrimarySpriteID` block in {header_path}")
    ids: dict[int, str] = {}
    next_id = 0
    for item in _ENUM_ITEM_RE.finditer(match.group("body")):
        if item.group("value") is not None:
            next_id = int(item.group("value"), 0)
        ids[next_id] = item.group("name")
        next_id += 1
    if not ids:
        die(f"`enum PrimarySpriteID` in {header_path} parsed to zero names")
    return ids


class SpawnNamer:
    """Spawn id -> `PSPRITE_*` name, following `func_801E0EC`.

    Ids 1..16 are arithmetic. Ids 17..48 need the level's own
    `gUnk_3000524`, which is rebuilt per level, so without a snapshot they are
    reported as raw ids -- inventing a name would be worse than the number.
    """

    def __init__(self, ids: dict[int, str], snapshot: bytes | None = None) -> None:
        self.ids = ids
        self.table: list[int] | None = None
        if snapshot is not None:
            off = IWRAM_SPAWN_TO_TYPE - IWRAM_BASE
            if off < 0 or off + SPAWN_TABLE_LEN > len(snapshot):
                die(
                    "snapshot is %d bytes; gUnk_3000524 needs IWRAM offset 0x%X..0x%X"
                    % (len(snapshot), off, off + SPAWN_TABLE_LEN)
                )
            self.table = list(snapshot[off : off + SPAWN_TABLE_LEN])

    @property
    def described(self) -> str:
        if self.table is None:
            return "ids > 16 unnamed (pass --iwram for this level's gUnk_3000524)"
        return "ids > 16 named from the level's gUnk_3000524"

    def __call__(self, spawn: int) -> str:
        if 1 <= spawn <= SPAWN_ID_INLINE_MAX:
            return self.ids.get(spawn - 1, f"PSPRITE_?{spawn - 1:#04x}")
        if self.table is not None:
            index = spawn - SPAWN_ID_INLINE_MAX - 1
            if 0 <= index < len(self.table):
                return self.ids.get(self.table[index], f"PSPRITE_?{self.table[index]:#04x}")
        return f"spawn#{spawn:02d}?"



def die(message: str) -> "NoReturn":  # type: ignore[valid-type]
    print("level_rooms.py: " + message, file=sys.stderr)
    raise SystemExit(2)


def need(rom: bytes, addr: int, size: int, what: str) -> int:
    off = addr - ROM_BASE
    if addr < ROM_BASE or off < 0 or off + size > len(rom):
        die(f"{what} 0x{addr:08X}+{size} is outside the cartridge image")
    return off


def u8(rom: bytes, addr: int) -> int:
    return rom[addr - ROM_BASE]


def u16(rom: bytes, addr: int) -> int:
    return struct.unpack_from("<H", rom, need(rom, addr, 2, "word"))[0]


def u32(rom: bytes, addr: int) -> int:
    return struct.unpack_from("<I", rom, need(rom, addr, 4, "word"))[0]


def level_base(rom: bytes, level: int) -> int:
    if level < 0 or level > 0xFF:
        die(f"level index {level} out of range")
    return u32(rom, LEVEL_TABLE + level * 4)


def is_rom_ptr(addr: int, alignment: int = 4) -> bool:
    """A ROM pointer: inside the cartridge image and naturally aligned.

    `alignment` matters and the two values are not interchangeable.  A level
    block in `sUnk_878F280` is a `u32[]`, so its base is word-aligned.  Inside
    a room header the BG and sprite pointers are **halfword**-aligned — the
    cartridge's BG maps are tile data, e.g. level 1 room 1's `pBg1Data` is
    0x085994CB — so demanding word alignment there invents a one-room level.
    Odd values are the real end-of-level signal: rooms 11, 12, 13 and 15 all
    carry `pBg0Data = 0x083F2263`, which is the byte pattern behind the level
    data rather than a pointer into it.
    """
    return ROM_BASE <= addr < ROM_END and addr % alignment == 0


def read_header(rom: bytes, addr: int) -> dict:
    need(rom, addr, HEADER_SIZE, "RoomHeader")
    return {
        "addr": addr,
        "tileset": u8(rom, addr + 0x00),
        "bgParams": [u8(rom, addr + 0x01 + i) for i in range(4)],
        "bg": [u32(rom, addr + 0x08 + 4 * i) for i in range(4)],
        "cameraControl": u8(rom, addr + 0x18),
        "layer3Scrolling": u8(rom, addr + 0x19),
        "bgPriorityAlpha": u8(rom, addr + 0x1A),
        "hard": u32(rom, addr + 0x1C),
        "normal": u32(rom, addr + 0x20),
        "shard": u32(rom, addr + 0x24),
        "raster": u8(rom, addr + 0x28),
        "water": u8(rom, addr + 0x29),
        "music": u16(rom, addr + 0x2A),
    }


def read_sprite_list(rom: bytes, addr: int, namer: SpawnNamer) -> list[dict]:
    """Decode `[y, x, spawnId]` entries up to the FF FF FF terminator."""
    if not is_rom_ptr(addr, 2):
        return []
    out: list[dict] = []
    pos = addr
    for _ in range(256):  # a room cannot hold more slots than the sprite array
        need(rom, pos, SPRITE_ENTRY_SIZE, "sprite list")
        entry = rom[pos - ROM_BASE : pos - ROM_BASE + SPRITE_ENTRY_SIZE]
        if entry == SPRITE_LIST_TERMINATOR:
            return out
        y, x, spawn = entry
        out.append(
            {
                "spawn": spawn,
                "type": namer(spawn),
                "yBlock": y,
                "xBlock": x,
                "y": y * Y_SCALE + Y_ORIGIN,
                "x": x * X_SCALE + X_ORIGIN,
                "pos": pos,
            }
        )
        pos += SPRITE_ENTRY_SIZE
    return out


def level_block_bound(rom: bytes, level: int) -> int | None:
    """Room count of `level`, bounded by where the next level block starts.

    `sUnk_878F280[0] = 0x083F4F38` and `sUnk_878F280[1] = 0x083F5174` differ by
    0x23C, which is exactly 13 x 0x2C — the level's rooms are a contiguous,
    0x2C-stride array, so the *next block's address* is the room count rather
    than a guess.  This matters: a plausibility scan of the pointers alone
    reported 16 rooms and invented four of them, and a stricter scan reported
    one.  Returns None when the next entry is not a usable bound (the last
    level, or the sentinel region past index 23).
    """
    base = level_base(rom, level)
    nxt = level_base(rom, level + 1) if level + 1 <= 0xFF else 0
    if nxt > base and (nxt - base) % HEADER_SIZE == 0:
        return (nxt - base) // HEADER_SIZE
    return None


def level_rooms(rom: bytes, level: int, quiet: bool = False) -> list[dict]:
    """Every RoomHeader of the level, in gCurrentRoom order.

    `quiet` suppresses the complaint about an undecodable level. The `--levels`
    scan uses it: "the next index is a sentinel" is the expected shape of the
    table's end, and printing it as an error makes a clean exit look like a
    failure.
    """
    base = level_base(rom, level)
    if not is_rom_ptr(base):
        die(f"level {level}: sUnk_878F280[{level:#04x}] = 0x{base:08X} is not a ROM pointer")
    count = level_block_bound(rom, level)
    rooms: list[dict] = []
    for index in range(count if count else MAX_ROOMS_HINT):
        addr = base + index * HEADER_SIZE
        header = read_header(rom, addr)
        # A real header points at BG data and at sprite lists.  These are
        # halfword-aligned tile-data pointers, so alignment cannot separate a
        # room from the bytes behind it -- `count` does that job.  The check is
        # kept as a last-resort bound for a level with no successor block.
        if count is None and not all(is_rom_ptr(p, 2) for p in header["bg"]):
            break
        if not all(is_rom_ptr(header[k], 2) for k in ("hard", "normal", "shard")):
            break
        header["room"] = index
        rooms.append(header)
    if not rooms and not quiet:
        die(f"level {level}: no plausible room header at 0x{base:08X}")
    return rooms


def print_level(
    rom: bytes,
    level: int,
    only_room: int | None,
    show_sprites: bool,
    namer: SpawnNamer,
) -> None:
    base = level_base(rom, level)
    print(f"level {level}: sUnk_878F280[{level:#04x}] = 0x{base:08X} (gUnk_3000023 = {level})")
    rooms = level_rooms(rom, level)
    bound = level_block_bound(rom, level)
    if bound is None:
        print(
            f"  rooms: {len(rooms)} (0..{len(rooms) - 1}) - NOT bounded by a successor "
            "block, so this count is a scan and may be short"
        )
    else:
        print(
            f"  rooms: {len(rooms)} (0..{len(rooms) - 1}) - bounded by the next level "
            f"block at 0x{level_base(rom, level + 1):08X} ({bound} x 0x2C bytes)"
        )
    if len(rooms) >= MAX_ROOMS_HINT:
        print(
            f"  NOTE: the decode hit its {MAX_ROOMS_HINT}-room cap, so the real room count "
            "is at least this large; raise MAX_ROOMS_HINT to see whether more exist."
        )
    if show_sprites:
        print(f"  spawn ids: {namer.described}")
    for header in rooms:
        if only_room is not None and header["room"] != only_room:
            continue
        print(
            "  room %d @ 0x%08X tileset=0x%02X bgParams=%s camera=%d layer3=%d "
            "prioAlpha=%d raster=%d water=%d music=0x%04X"
            % (
                header["room"],
                header["addr"],
                header["tileset"],
                "".join("%02X" % p for p in header["bgParams"]),
                header["cameraControl"],
                header["layer3Scrolling"],
                header["bgPriorityAlpha"],
                header["raster"],
                header["water"],
                header["music"],
            )
        )
        print(
            "    bg0=0x%08X bg1=0x%08X bg2=0x%08X bg3=0x%08X"
            % tuple(header["bg"])
        )
        if not show_sprites:
            continue
        for kind in ("hard", "normal", "shard"):
            entries = read_sprite_list(rom, header[kind], namer)
            print(
                "    %-6s 0x%08X: %d entr%s"
                % (kind, header[kind], len(entries), "y" if len(entries) == 1 else "ies")
            )
            for entry in entries:
                print(
                    "        spawn 0x%02X %-30s block(y=%3d x=%3d) raw(y=%5d x=%5d) @0x%08X"
                    % (
                        entry["spawn"],
                        entry["type"],
                        entry["yBlock"],
                        entry["xBlock"],
                        entry["y"],
                        entry["x"],
                        entry["pos"],
                    )
                )


def check_snapshot(rom: bytes, snapshot: bytes, level: int, room: int) -> int:
    """Cross-check a guest IWRAM snapshot against the ROM decode.

    `func_806B410` copies the level's 0x2C-byte RoomHeader from the cartridge
    into `gCurrentRoomHeader` (IWRAM 0x03000074) and every byte of it, so the
    snapshot must equal the ROM record for that room exactly.  This is the
    tool's own correctness gate: without it a mis-decoded struct would look
    like a game behaviour.  It is what caught the sprite field order being
    wrong (`[spawn, y, x]` instead of `[y, x, spawn]`) on the first run.
    """
    rooms = level_rooms(rom, level)
    if room >= len(rooms):
        die(f"level {level} has {len(rooms)} rooms; room {room} does not exist")
    rom_addr = rooms[room]["addr"]
    off = IWRAM_ROOM_HEADER - IWRAM_BASE
    if off < 0 or off + HEADER_SIZE > len(snapshot):
        die(
            "snapshot is %d bytes; gCurrentRoomHeader needs IWRAM offset 0x%X..0x%X"
            % (len(snapshot), off, off + HEADER_SIZE)
        )
    live = snapshot[off : off + HEADER_SIZE]
    rom_record = rom[rom_addr - ROM_BASE : rom_addr - ROM_BASE + HEADER_SIZE]
    what = "gCurrentRoomHeader (IWRAM 0x%08X) vs ROM room %d (0x%08X)" % (
        IWRAM_ROOM_HEADER,
        room,
        rom_addr,
    )
    if live == rom_record:
        print("  OK  %s: %d/%d bytes identical" % (what, HEADER_SIZE, HEADER_SIZE))
        return 0
    print("  MISMATCH %s" % what)
    for i in range(HEADER_SIZE):
        if live[i] != rom_record[i]:
            print("    +0x%02X  guest 0x%02X  rom 0x%02X" % (i, live[i], rom_record[i]))
    return 1


def snapshot_stage(snapshot: bytes) -> int:
    """`gUnk_3000023`, the level block the guest was actually in."""
    off = IWRAM_STAGE - IWRAM_BASE
    if off < 0 or off >= len(snapshot):
        die("snapshot is too small to hold gUnk_3000023")
    return snapshot[off]


def snapshot_room(snapshot: bytes) -> int:
    """`gCurrentRoom`, the room the guest was actually in."""
    off = IWRAM_ROOM - IWRAM_BASE
    if off < 0 or off >= len(snapshot):
        die("snapshot is too small to hold gCurrentRoom")
    return snapshot[off]


def read_file(path: str) -> bytes:
    try:
        return open(path, "rb").read()
    except OSError as exc:
        die(f"cannot read {path}: {exc}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--rom", required=True, help="path to the .gba image")
    ap.add_argument("--level", type=int, help="gUnk_3000023 value to decode")
    ap.add_argument("--room", type=int, help="only this room of the level")
    ap.add_argument("--levels", action="store_true", help="list every level block")
    ap.add_argument("--no-sprites", action="store_true", help="skip the sprite lists")
    ap.add_argument(
        "--iwram",
        help=(
            "IWRAM snapshot of this level; supplies the gUnk_3000524 spawn-id table "
            "so ids > 16 can be named (func_801E0EC)"
        ),
    )
    ap.add_argument(
        "--sprite-header",
        default=DEFAULT_SPRITE_HEADER,
        help="sprite.h holding `enum PrimarySpriteID` (default: %(default)s)",
    )
    ap.add_argument("--check-snapshot", help="IWRAM snapshot to cross-check against")
    ap.add_argument(
        "--check-room",
        type=int,
        help="room whose guest gCurrentRoomHeader to cross-check (default: the snapshot's gCurrentRoom)",
    )
    args = ap.parse_args(argv)

    rom = read_file(args.rom)

    if args.levels:
        for level in range(0x100):
            base = level_base(rom, level)
            if not is_rom_ptr(base):
                break
            try:
                bound = level_block_bound(rom, level)
                if bound == 0:
                    # Past the real blocks the table stops being level blocks:
                    # index 23 is a sentinel and index 25+ points into code
                    # (0x0806D7xx, which decodes to no plausible room at all).
                    break
                note = ""
                if bound is None:
                    bound = len(level_rooms(rom, level, quiet=True))
                    if bound == 0:
                        break
                    note = "  (scan, unbounded)"
            except SystemExit:
                # index 23 is a sentinel: its bytes decode to no room at all.
                # Ending the listing here is the answer, not a tool failure.
                break
            print("level %3d  block 0x%08X  rooms %3d%s" % (level, base, bound, note))
        print(
            "  (the table stops at the first entry that is not a level block; "
            "index 23 is a sentinel and 25+ point into code)"
        )
        return 0

    # A check with no --level is the common case: the snapshot says which level
    # and room the guest was in, so the gate always tests the real one.
    snapshot = read_file(args.check_snapshot) if args.check_snapshot else None
    if args.check_snapshot is not None and not args.check_snapshot.endswith(".bin"):
        die("--check-snapshot expects an IWRAM .bin snapshot")
    if snapshot is not None and args.check_room is None:
        args.check_room = snapshot_room(snapshot)
    if args.level is None:
        if snapshot is None:
            die("give --level N, --levels, or --check-snapshot")
        args.level = snapshot_stage(snapshot)
        print(
            "  (no --level given: taking the level and room from the snapshot: "
            "gUnk_3000023=%d gCurrentRoom=%d)" % (args.level, args.check_room)
        )

    namer = SpawnNamer(
        load_primary_sprite_ids(args.sprite_header),
        read_file(args.iwram) if args.iwram else None,
    )
    print_level(rom, args.level, args.room, not args.no_sprites, namer)

    if snapshot is not None:
        return check_snapshot(rom, snapshot, args.level, args.check_room)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
