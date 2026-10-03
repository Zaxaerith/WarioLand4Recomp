#!/usr/bin/env python3
"""func_dump.py — list a generated function's instructions with its literal pool resolved.

Why this exists: the generated C++ is the authoritative decode, but reading it
means scrolling a 300k-line file of resume scaffolding, and the generator's
*branch-target* comments are known to be wrong (docs/KNOWN_ISSUES.md, the
0x08072B74 case). The instruction comments themselves are reliable, so this
prints just those -- and, for the `ldr rX,[r15,#imm]` form, appends the value
that literal actually holds, read from the cartridge image and named from
symbols/iwram_map.tsv.

The literal address is `((insn + 4) & ~3) + imm` (docs/VALIDATION.md rule 38:
attribute a load to the instruction performing it, and compute the literal
address from *that* instruction's PC). Doing it here rather than by hand is the
point -- the hand version of this same arithmetic has been wrong five times in
this project, and each error produced a confident wrong story.

It is a *reader*. It never writes a config and never patches the ROM.

Usage
    python tools/validation/func_dump.py --rom "<rom.gba>" --fn 0x0806B90C
    python tools/validation/func_dump.py --rom "<rom.gba>" --fn 0x0806DE5E:0x0806DF40
    python tools/validation/func_dump.py --self-test --rom "<rom.gba>"
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import struct
import sys

ROM_BASE = 0x08000000

# The generator writes one comment per *halfword*, bare hex, no 0x prefix:
#   /* 0806B92C  0806b92c T strb r0,[r1] */
INSN = re.compile(r"/\* ([0-9A-Fa-f]{8})\s+([0-9a-f]{8})\s+([TA])\s+(.+?) \*/")
# The literal-pool form. Thumb only; an ARM ldr uses a PC-relative word instead
# and is left alone rather than decoded wrongly.
LDR_LIT = re.compile(r"^ldr\s+(r\d+),\[r15,#(0x[0-9a-fA-F]+)\]$")
IWRAM = re.compile(r"^(g[A-Za-z0-9_]+)\s*$")


def load_iwram_names(path: str) -> dict[int, str]:
    """Map IWRAM addresses to decomp symbol names.

    The file is TAB separated (`address | name | gap` when rendered as a
    table); splitting on whitespace alone is what once made this return 554
    entries and then, a moment later, zero, depending on how the caller had
    re-rendered the same lines.
    """
    names: dict[int, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            try:
                addr = int(parts[0].strip(), 16)
            except ValueError:
                continue
            names[addr] = parts[1].strip()
    return names


def literal_addr(insn: int, imm: int) -> int:
    """`ldr rX,[r15,#imm]` reads from Align(PC,4)+imm where PC = insn+4."""
    return ((insn + 4) & ~3) + imm


def read_u32(rom: bytes, addr: int) -> int | None:
    off = addr - ROM_BASE
    if off < 0 or off + 4 > len(rom):
        return None
    return struct.unpack_from("<I", rom, off)[0]


def rom_ldr_imm8(rom: bytes, insn: int) -> int | None:
    """The imm8 the cartridge image actually encodes at `insn`, if it is a
    Thumb `LDR (literal)`.

    Kept separate from the comment on purpose. See `dump()`: the generator's
    printed immediate and the ROM's encoded imm8 disagree at every one of the
    13,118 literal loads in the ROM, so a tool that silently picks one of them
    is picking a side of an open question without saying so.
    """
    off = insn - ROM_BASE
    if off < 0 or off + 2 > len(rom):
        return None
    hw = struct.unpack_from("<H", rom, off)[0]
    if (hw >> 11) != 0b01001:
        return None
    return hw & 0xFF


def collect_instructions(generated: str) -> dict[int, tuple[str, str]]:
    """address -> (mode letter, text) for every instruction comment in generated/cart."""
    out: dict[int, tuple[str, str]] = {}
    for path in sorted(glob.glob(os.path.join(generated, "recompiled_*.cpp"))):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = INSN.search(line)
                if m:
                    out[int(m.group(1), 16)] = (m.group(3), m.group(4))
    return out


def dump(insns: dict[int, tuple[str, str]], rom: bytes, names: dict[int, str],
         lo: int, hi: int, show_literals: bool = True) -> list[str]:
    lines: list[str] = []
    for addr in sorted(a for a in insns if lo <= a < hi):
        mode, text = insns[addr]
        suffix = ""
        mismatch = ""
        if show_literals and mode == "T":
            m = LDR_LIT.match(text)
            if m:
                lit = literal_addr(addr, int(m.group(2), 16))
                val = read_u32(rom, lit)
                if val is None:
                    suffix = "  ; = <outside the image>"
                else:
                    nm = names.get(val)
                    suffix = f"  ; pool@{lit:08X} = 0x{val:08X}" + (f"  {nm}" if nm else "")
                # The open question, stated at the point of use (KNOWN_ISSUES
                # G21). The comment's immediate is what the generated C++ uses
                # and the trace confirms it; the ROM encodes a different imm8.
                enc = rom_ldr_imm8(rom, addr)
                if enc is not None and enc != int(m.group(2), 16):
                    alt = read_u32(rom, literal_addr(addr, enc))
                    mismatch = (f"\n         !! G21: the ROM encodes imm8=0x{enc:02X} at this "
                                f"PC -> 0x{literal_addr(addr, enc):08X} = "
                                f"{'0x%08X' % alt if alt is not None else 'oob'}, "
                                f"but the comment implies 0x{val:08X}")
        lines.append(f"{addr:08X}  {mode}  {text}{suffix}{mismatch}")
    return lines


def self_test(rom: bytes, generated: str, symbols: str) -> int:
    """Gate the literal arithmetic against the GUEST, not against itself.

    A live run of the attract demo with GBARECOMP_ABORT_ON_MEM_WRITE_ADDR on
    0x03000024 recorded

        #38564131 mem_w pc=0x0806B90E ... addr=0x03000046
        #38564132 mem_w pc=0x0806B92C ... addr=0x03000024

    so at those two PCs the *executed* effective addresses were 0x03000046 and
    0x03000024. The two are computed here from the ROM through the formula, and
    are compared against what the CPU actually did. A formula copied out of a
    spec and checked against itself proves nothing; this one is checked against
    the guest.
    """
    bad = 0
    names = load_iwram_names(symbols)
    if not names:
        print(f"  FAIL load_iwram_names() read 0 symbols from {symbols}")
        return 1
    print(f"  ok   load_iwram_names() read {len(names)} IWRAM symbols")

    # Against the GUEST, not against this tool. A live run recorded
    #   #38564131 mem_w pc=0x0806B90E ... addr=0x03000046
    #   #38564132 mem_w pc=0x0806B92C ... addr=0x03000024
    # so those two PCs really did hold 0x03000046 and 0x03000024. The value
    # this tool prints for a given PC must be the one the CPU used, or it is
    # describing a different program than the one that ran.
    for insn, guest_val in ((0x0806B90C, 0x03000046), (0x0806B928, 0x03000024)):
        got = read_u32(rom, literal_addr(insn, {0x0806B90C: 0x9C, 0x0806B928: 0x8C}[insn]))
        ok = got == guest_val
        print(f"  {'ok  ' if ok else 'FAIL'} 0x{insn:08X} resolves to 0x{(got or 0):08X}  "
          f"(the guest loaded 0x{guest_val:08X})")
        if not ok:
            bad += 1

    # G21, stated as a detection rather than a verdict. This tool does NOT get
    # to decide which convention is right -- the generator and the ROM disagree
    # at all 13,118 literal loads, and two of this project's own tools agreeing
    # with each other is not evidence. What the tool must do is notice and say
    # so, at every site, rather than picking one silently.
    enc = rom_ldr_imm8(rom, 0x08000278)
    cmt_val = read_u32(rom, literal_addr(0x08000278, 0x08))
    alt = read_u32(rom, literal_addr(0x08000278, enc)) if enc is not None else None
    ok = enc is not None and enc != 0x08 and cmt_val == 0x03000C3A and alt != 0x03000C3A
    print(f"  {'ok  ' if ok else 'FAIL'} rom_ldr_imm8() sees the disagreement at "
          f"0x08000278 (rom imm8=0x{(enc or 0):02X} -> "
          f"{'0x%08X' % alt if alt is not None else 'oob'}; comment -> 0x{cmt_val:08X})")
    if not ok:
        bad += 1
    rows = dump(insns := collect_instructions(generated), rom, names,
                0x08000278, 0x08000280)
    ok = bool(rows) and any("!! G21" in r for r in rows)
    print(f"  {'ok  ' if ok else 'FAIL'} dump() flags the convention mismatch in its "
          f"output ({len(rows)} instruction(s))")
    if not ok:
        bad += 1

    insns = collect_instructions(generated)
    if not insns:
        print(f"  FAIL collect_instructions() read 0 comments from {generated}")
        return 1
    print(f"  ok   collect_instructions() read {len(insns)} instruction comments")

    # 0x0806B90C..0x0806B940 is 0x34 = 52 bytes, and every instruction in a
    # Thumb function is 2 bytes, so 26 comments is the right count. The earlier
    # "13" came from counting as if they were 4-byte ARM words -- the same
    # mistake that produced G21, which is worth a self-test of its own.
    rows = dump(insns, rom, names, 0x0806B90C, 0x0806B940)
    ok = len(rows) == (0x0806B940 - 0x0806B90C) // 2 == 26
    print(f"  {'ok  ' if ok else 'FAIL'} dump() lists all 26 Thumb instruction(s) of "
          f"gf_tfunc_0806B90C (got {len(rows)})")
    if not ok:
        bad += 1
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", help="the base ROM (required)")
    ap.add_argument("--fn", action="append", default=[], metavar="START[:END]",
                    help="function start, or an explicit START:END span; repeatable")
    ap.add_argument("--generated", default=os.path.join("generated", "cart"))
    ap.add_argument("--symbols", default=os.path.join("symbols", "iwram_map.tsv"))
    ap.add_argument("--no-literals", action="store_true",
                    help="print the instructions without resolving the literal pool")
    ap.add_argument("--self-test", action="store_true",
                    help="check the literal arithmetic against a traced run and exit")
    args = ap.parse_args(argv)

    if args.self_test:
        if not args.rom:
            print("--self-test needs --rom", file=sys.stderr)
            return 2
        rom = open(args.rom, "rb").read()
        print(f"func_dump self-test against {args.rom}")
        rc = self_test(rom, args.generated, args.symbols)
        print("PASS" if rc == 0 else f"FAIL ({rc} check(s))")
        return 0 if rc == 0 else 1

    if not args.rom:
        print("--rom is required", file=sys.stderr)
        return 2
    if not args.fn:
        print("--fn is required (repeatable; START[:END])", file=sys.stderr)
        return 2

    rom = open(args.rom, "rb").read()
    names = load_iwram_names(args.symbols)
    insns = collect_instructions(args.generated)
    if not insns:
        print(f"no instruction comments found under {args.generated}", file=sys.stderr)
        return 2

    total = 0
    for spec in args.fn:
        lo_s, _, hi_s = spec.partition(":")
        lo = int(lo_s, 0)
        hi = int(hi_s, 0) if hi_s else lo + 0x400
        rows = dump(insns, rom, names, lo, hi, show_literals=not args.no_literals)
        # Trim trailing padding: stop at the last address that is not contiguous.
        print(f"== 0x{lo:08X}..0x{hi:08X}  ({len(rows)} instruction(s))")
        prev = None
        for i, r in enumerate(rows):
            a = int(r[:8], 16)
            if prev is not None and a - prev > 2:
                print("   ...")
            prev = a
            print(r)
        total += len(rows)
    print(f"\n   {total} instruction(s) over {len(args.fn)} span(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
