#!/usr/bin/env python3
"""match_iwram.py — find where RAM-resident code was copied from.

Cartridge and BIOS code is routinely copied into IWRAM and executed there.
The recompiler cannot see that copy statically, so it needs reviewed
`[[code_copy]]` metadata (runtime_start / source_start / size). This tool
supplies the evidence: it byte-matches a 32 KiB IWRAM dump against the
cartridge image and reports every maximal run that appears verbatim in ROM.

Produce the dump with the shared runtime, which writes it at exit:

    GBARECOMP_IWRAM_DUMP=logs/routes/iwram-900.bin \
      WarioLand4Recomp.exe --no-window --rom <rom> --bios <bios> --config game.toml --frames 900

Read-only: it prints, and never edits a config.

Usage
    python tools/validation/match_iwram.py --rom "<rom.gba>" --iwram logs/routes/iwram-900.bin
    python tools/validation/match_iwram.py --rom "<bios.bin>" --rom-base 0x00000000 --iwram ...
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys

IWRAM_BASE = 0x03000000
ROM_BASE_DEFAULT = 0x08000000
SEED = 16
MIN_RUN = 32


def parse_addr(text: str) -> int:
    return int(text, 0)


def coverage_report(iwram: bytes, base: int, page: int = 0x400) -> None:
    print(f"IWRAM occupancy by {page:#x} page (non-zero / 0xFF / other):")
    for start in range(0, len(iwram), page):
        chunk = iwram[start:start + page]
        nonzero = sum(1 for b in chunk if b != 0)
        ones = sum(1 for b in chunk if b == 0xFF)
        if nonzero:
            print(f"  {base + start:#010x}-{base + start + len(chunk) - 1:#010x} "
                  f"nonzero={nonzero:5d} ff={ones:5d}")


def find_runs(rom: bytes, iwram: bytes, iwram_base: int, rom_base: int,
              min_run: int) -> list[tuple[int, int, int]]:
    """Return (iwram_addr, rom_addr, length) for maximal verbatim runs."""
    claimed = bytearray(len(iwram))   # bytes already covered by a reported run
    runs: list[tuple[int, int, int]] = []
    for pos in range(0, len(iwram) - SEED, 2):
        if claimed[pos]:
            continue
        seed = iwram[pos:pos + SEED]
        if seed == b"\x00" * SEED or seed == b"\xff" * SEED:
            continue
        rom_off = rom.find(seed)
        if rom_off < 0:
            continue
        # extend forward
        n = SEED
        while (pos + n < len(iwram) and rom_off + n < len(rom)
               and iwram[pos + n] == rom[rom_off + n]):
            n += 1
        # extend backward (only into unclaimed space)
        s = 0
        while (pos - s - 1 >= 0 and rom_off - s - 1 >= 0
               and iwram[pos - s - 1] == rom[rom_off - s - 1]
               and not claimed[pos - s - 1]):
            s += 1
        if n >= min_run:
            runs.append((iwram_base + pos - s, rom_base + rom_off - s, n + s))
            for k in range(pos - s, pos + n):
                if 0 <= k < len(claimed):
                    claimed[k] = 1
    return sorted(runs)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True, help="image to match against")
    ap.add_argument("--rom-base", type=parse_addr, default=ROM_BASE_DEFAULT)
    ap.add_argument("--iwram", required=True, help="32 KiB IWRAM dump")
    ap.add_argument("--iwram-base", type=parse_addr, default=IWRAM_BASE)
    ap.add_argument("--min-run", type=int, default=MIN_RUN)
    args = ap.parse_args(argv)

    with open(args.rom, "rb") as fh:
        rom = fh.read()
    with open(args.iwram, "rb") as fh:
        iwram = fh.read()

    print(f"rom    : {args.rom} ({len(rom)} bytes, base {args.rom_base:#010x})")
    print(f"iwram  : {args.iwram} ({len(iwram)} bytes, base {args.iwram_base:#010x})")
    print()
    coverage_report(iwram, args.iwram_base)
    print()

    runs = find_runs(rom, iwram, args.iwram_base, args.rom_base, args.min_run)
    if not runs:
        print(f"no verbatim run of >= {args.min_run} bytes was found.")
        return 1

    print(f"{len(runs)} verbatim run(s) of >= {args.min_run} bytes "
          f"(candidate [[code_copy]] spans):")
    for iw, rd, n in runs:
        data = iwram[iw - args.iwram_base: iw - args.iwram_base + n]
        digest = hashlib.sha256(data).hexdigest()[:16]
        print(f"  iwram {iw:#010x} <- rom {rd:#010x}   size {n:#06x} "
              f"({n:5d})   sha256[:16]={digest}")
    print()
    print("review: a real [[code_copy]] needs the copy to be *code* (not a data")
    print("buffer that happens to match) — confirm with a memory-write trace")
    print("(GBARECOMP_RUNTIME_TRACE) before writing it down.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
