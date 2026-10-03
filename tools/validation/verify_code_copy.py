#!/usr/bin/env python3
"""Read-only verifier for a claimed [[code_copy]] (runtime_start, source_start, size).

Why this exists
---------------
The runtime zero-fills RAM (observed: a BIOS clear loop writing 0x00000000
sequentially, pc=0x00000C08) before cartridge code is copied in.  A naive
byte-matcher that looks for "the longest run of RAM bytes that also appear in
the ROM image" therefore reports *zero-filled* regions as copies, because a run
of zeros matches any run of zeros.  A byte-identical run is only evidence when
the bytes are not all zero.

For each claim this tool prints, independently:
  * nonzero byte counts on both sides,
  * sha256 of both spans,
  * whether the spans are byte-identical,
  * the first differing offset,
  * and a verdict that refuses to call a zero run a copy.

It never writes anything.
"""
from __future__ import annotations

import argparse
import hashlib
import sys

ROM_BASE = 0x08000000
IWRAM_BASE = 0x03000000


def load(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def span(data: bytes, addr: int, size: int, base: int, label: str) -> bytes | None:
    off = addr - base
    if off < 0:
        print(f"  !! {label}: address 0x{addr:08X} is below its base 0x{base:08X}")
        return None
    if off + size > len(data):
        print(
            f"  !! {label}: 0x{addr:08X}+0x{size:X} runs past the end of the "
            f"{len(data)}-byte image (offset 0x{off:X})"
        )
        return None
    return data[off : off + size]


def describe(tag: str, blob: bytes) -> None:
    nz = sum(1 for b in blob if b)
    print(f"  {tag}: bytes={len(blob)} nonzero={nz} ({100.0 * nz / max(1, len(blob)):.2f}%)")
    print(f"  {tag}: sha256={hashlib.sha256(blob).hexdigest()}")


def check(rom: bytes, iwram: bytes, runtime_start: int, source_start: int, size: int) -> bool:
    print(f"== code_copy runtime_start=0x{runtime_start:08X} "
          f"source_start=0x{source_start:08X} size=0x{size:X} ==")
    ram = span(iwram, runtime_start, size, IWRAM_BASE, "iwram")
    src = span(rom, source_start, size, ROM_BASE, "rom")
    if ram is None or src is None:
        print("  verdict: UNVERIFIABLE (out of range)\n")
        return False

    describe("iwram", ram)
    describe("rom  ", src)

    identical = ram == src
    first_diff = next((i for i, (a, b) in enumerate(zip(ram, src)) if a != b), None)
    print(f"  identical={identical}"
          + ("" if identical else f" first_difference=+0x{first_diff:X}"))

    ram_nz = sum(1 for b in ram if b)
    src_nz = sum(1 for b in src if b)
    if ram_nz == 0 and src_nz == 0:
        print("  verdict: SUSPECT_ZERO_FILL — both spans are all zero; a byte match "
              "here proves nothing (the RAM was probably cleared, never copied)\n")
        return False
    if ram_nz < size // 16:
        print(f"  verdict: WEAK — the RAM span is {100.0 * ram_nz / size:.2f}% nonzero; "
              "verify by tracing the copy instruction, not by matching bytes\n")
        return False
    if not identical:
        print("  verdict: MISMATCH — the RAM span is not this ROM span; the claimed "
              "source or size is wrong\n")
        return False
    print("  verdict: BYTE_IDENTICAL_AND_NONZERO — real evidence, still worth "
          "confirming against the copy instruction\n")
    return True


def parse_copy(text: str) -> tuple[int, int, int]:
    parts = text.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected RUNTIME:SOURCE:SIZE")
    try:
        return (int(parts[0], 0), int(parts[1], 0), int(parts[2], 0))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True, help="cartridge image")
    ap.add_argument("--iwram", required=True, help="32768-byte IWRAM dump")
    ap.add_argument("--copy", action="append", default=[], type=parse_copy,
                    metavar="RUNTIME:SOURCE:SIZE", help="repeatable claim to verify")
    args = ap.parse_args(argv)

    rom = load(args.rom)
    iwram = load(args.iwram)
    if len(iwram) != 32768:
        print(f"note: IWRAM dump is {len(iwram)} bytes, expected 32768", file=sys.stderr)

    ok = True
    for runtime_start, source_start, size in args.copy:
        ok &= check(rom, iwram, runtime_start, source_start, size)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
