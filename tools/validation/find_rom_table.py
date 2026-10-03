#!/usr/bin/env python3
"""find_rom_table.py — locate a computed-jump table in the cartridge image.

Read-only ROM analysis used to replace "21 guessed [[extra_func]] entries" with
one reviewed [[jump_table]] block. Given the guest PCs that the runtime reported
as dispatch misses, this finds where the cartridge stores them and prints the
surrounding table so a human can size it (`addr`, `stride`, `count`, `format`).

It never writes a config and never modifies the ROM.

Usage
    python tools/validation/find_rom_table.py --rom "<rom.gba>" \
        --addr 0x080015CC --addr 0x080015D2 ...

The ROM is addressed at 0x08000000; file offset = guest_addr - rom_base.
"""

from __future__ import annotations

import argparse
import struct
import sys

ROM_BASE_DEFAULT = 0x08000000


def parse_addr(text: str) -> int:
    return int(text, 0)


def find_occurrences(rom: bytes, value: int) -> list[int]:
    """All file offsets holding `value` as a little-endian 32-bit word."""
    needle = struct.pack("<I", value & 0xFFFFFFFF)
    offsets: list[int] = []
    start = 0
    while True:
        i = rom.find(needle, start)
        if i < 0:
            return offsets
        # Only 4-byte aligned offsets are plausible table slots in GBA data.
        if i % 2 == 0:
            offsets.append(i)
        start = i + 1


def dump_words(rom: bytes, offset: int, before: int, after: int,
               rom_base: int) -> list[str]:
    lines: list[str] = []
    first = offset - before * 4
    last = offset + after * 4
    for o in range(max(0, first), min(len(rom), last) + 1, 4):
        word = struct.unpack_from("<I", rom, o)[0]
        mark = "  <== target" if o == offset else ""
        lines.append(f"    [{o:#08x}] {rom_base + o:#010x}: {word:#010x}{mark}")
    return lines


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True, help="path to the cartridge image")
    ap.add_argument("--addr", action="append", required=True, type=parse_addr,
                    help="guest PC that missed (repeatable)")
    ap.add_argument("--rom-base", type=parse_addr, default=ROM_BASE_DEFAULT)
    ap.add_argument("--before", type=int, default=4, help="words to show before")
    ap.add_argument("--after", type=int, default=12, help="words to show after")
    ap.add_argument("--min-run", type=int, default=3,
                    help="consecutive known targets that make a slot table-like")
    args = ap.parse_args(argv)

    with open(args.rom, "rb") as fh:
        rom = fh.read()

    targets = sorted(set(args.addr))
    print(f"rom            : {args.rom} ({len(rom)} bytes)")
    print(f"rom base       : {args.rom_base:#010x}")
    print(f"missed guests  : {len(targets)}")
    print()

    # A thumb target is reached as either the bare address or address|1; the
    # table may store either, so look for both.
    hits: dict[int, list[tuple[str, int]]] = {}
    for addr in targets:
        for label, value in (("even", addr), ("thumb", addr | 1)):
            for off in find_occurrences(rom, value):
                hits.setdefault(off, []).append((label, addr))

    if not hits:
        print("no 32-bit occurrence of any missed PC was found in the image.")
        print("=> the cluster is NOT an abs32 table; look for a pcrel table or")
        print("   a truncated function body instead.")
        return 1

    print(f"{len(hits)} candidate slot(s):")
    for off in sorted(hits):
        stored = ", ".join(f"{a:#010x}({lbl})" for lbl, a in hits[off])
        print(f"  file {off:#08x} -> rom {args.rom_base + off:#010x} stores {stored}")

    print()
    # Rank slots by how many of the missed PCs appear within a short window of
    # contiguous 4-byte slots: that is what a real table looks like.
    ranked: list[tuple[int, int]] = []
    for off in hits:
        run = 0
        for k in range(args.min_run):
            if (off + k * 4) in hits:
                run += 1
        ranked.append((run, off))
    ranked.sort(reverse=True)

    for run, off in ranked[:4]:
        window_start = off - args.before * 4
        covered = [o for o in sorted(hits)
                   if window_start <= o <= off + args.after * 4]
        print(f"--- candidate table near rom {args.rom_base + off:#010x} "
              f"(contiguous hit run={run}, {len(covered)} target slot(s) in window) ---")
        for line in dump_words(rom, off, args.before, args.after, args.rom_base):
            print(line)
        print()

    best_run, best_off = ranked[0]
    print("review hint:")
    print(f"  base  = {args.rom_base + best_off:#010x}")
    print("  stride = 4, format = \"abs32\"  (confirm the entries are absolute)")
    print("  count  = <width of the dispatcher's CMP bound>  (NOT guessed here;")
    print("           read the dispatcher and its bound before writing it down)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
