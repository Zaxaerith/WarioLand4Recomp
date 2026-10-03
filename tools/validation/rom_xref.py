#!/usr/bin/env python3
"""rom_xref.py — read-only ROM analysis for jump-table sizing.

Two modes, both evidence-producing (no config is ever written):

  --literal-range LO HI   every 4-byte little-endian literal in the image whose
                          value falls inside [LO,HI) — i.e. the code that
                          references a table living at that address range.
  --dump-table ADDR       dump COUNT words at guest address ADDR, decoded as
                          abs32 interworking pointers (raw & ~1, mode from
                          bit 0), plus a summary of the leading run that stays
                          inside a plausible code window.

Usage
    python tools/validation/rom_xref.py --rom "<rom.gba>" --literal-range 0x08095400 0x08095500
    python tools/validation/rom_xref.py --rom "<rom.gba>" --dump-table 0x08095424 --count 48
"""

from __future__ import annotations

import argparse
import struct
import sys

ROM_BASE_DEFAULT = 0x08000000


def parse_addr(text: str) -> int:
    return int(text, 0)


def load(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def cmd_literal_range(rom: bytes, lo: int, hi: int, rom_base: int,
                      limit: int) -> int:
    hits: list[tuple[int, int]] = []
    for off in range(0, len(rom) - 3, 2):
        v = struct.unpack_from("<I", rom, off)[0]
        if lo <= v < hi:
            hits.append((off, v))
            if len(hits) >= limit:
                break
    print(f"literals in [{lo:#010x},{hi:#010x}) : {len(hits)}" +
          (" (truncated)" if len(hits) >= limit else ""))
    for off, v in hits:
        guest = rom_base + off
        # 0x00000000-0x00003FFF is BIOS; below 0x08000000 is not cart code, so
        # the referencing instruction is the word BEFORE the literal in the
        # usual `ldr rT,[pc,#imm]` layout.
        print(f"  literal at rom {guest:#010x} (file {off:#08x}) = {v:#010x}"
              f"   -> referencing word at {guest - 4:#010x}: "
              f"{struct.unpack_from('<I', rom, off - 4)[0]:#010x}")
    return 0


def cmd_dump_table(rom: bytes, addr: int, count: int, rom_base: int) -> int:
    off0 = addr - rom_base
    if off0 < 0 or off0 + count * 4 > len(rom):
        print(f"table {addr:#010x} count {count} runs past the image")
        return 1
    print(f"table @ {addr:#010x}  count={count}  stride=4  format=abs32")
    print("  idx   slot        raw value   target      mode   note")
    prev: int | None = None
    monotonic = True
    for i in range(count):
        off = off0 + i * 4
        raw = struct.unpack_from("<I", rom, off)[0]
        tgt = raw & ~1
        mode = "thumb" if raw & 1 else "arm"
        note = ""
        if tgt == 0:
            note = "NULL/pad"
        elif not (rom_base <= tgt < rom_base + len(rom)):
            note = "outside cartridge image"
        if prev is not None and tgt < prev and tgt != 0:
            monotonic = False
        if tgt:
            prev = tgt
        print(f"  [{i:3d}] {rom_base + off:#010x}  {raw:#010x}  {tgt:#010x}  "
              f"{mode:5s}  {note}")
    print()
    print(f"targets strictly increasing across the whole window: {monotonic}")
    print("If the window's tail turns into non-pointer words, the table ends "
          "there; trim --count accordingly.")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--rom-base", type=parse_addr, default=ROM_BASE_DEFAULT)
    ap.add_argument("--literal-range", nargs=2, type=parse_addr,
                    metavar=("LO", "HI"))
    ap.add_argument("--limit", type=int, default=64)
    ap.add_argument("--dump-table", type=parse_addr)
    ap.add_argument("--count", type=int, default=32)
    args = ap.parse_args(argv)

    if not args.literal_range and args.dump_table is None:
        ap.error("give --literal-range LO HI and/or --dump-table ADDR")

    rom = load(args.rom)
    if args.literal_range:
        cmd_literal_range(rom, args.literal_range[0], args.literal_range[1],
                          args.rom_base, args.limit)
    if args.dump_table is not None:
        if args.literal_range:
            print()
        cmd_dump_table(rom, args.dump_table, args.count, args.rom_base)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
