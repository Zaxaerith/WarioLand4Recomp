#!/usr/bin/env python3
"""thumb_dump.py — dependency-free Thumb (ARMv4T) window disassembler.

Why this exists: the workspace has no `arm-none-eabi-objdump` and no WSL, so
`third_party/lilDavid-warioland4/tools/disassembler.py` (which shells out to
objdump) cannot run, and the shared framework must stay read-only. Reading a
dispatcher's bound out of the cartridge image is exactly the evidence needed to
size a `[[jump_table]]`, so this small decoder covers Thumb formats 1-19
(ARMv4T: no BLX-immediate, no Thumb-2).

It is a *reader*: it prints, and never writes a config or patches a ROM.

Usage
    python tools/validation/thumb_dump.py --rom "<rom.gba>" --thumb 0x080014D0 --count 40
    python tools/validation/thumb_dump.py --rom "<rom.gba>" --arm 0x080000C0 --count 16
"""

from __future__ import annotations

import argparse
import struct
import sys

ROM_BASE_DEFAULT = 0x08000000

ALU_OPS = ["and", "eor", "lsl", "lsr", "asr", "adc", "sbc", "ror",
           "tst", "neg", "cmp", "cmn", "orr", "mul", "bic", "mvn"]
SHIFT_OPS = ["lsl", "lsr", "asr"]
COND = ["eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc",
        "hi", "ls", "ge", "lt", "gt", "le", "", "nv"]


def rm(v: int | None) -> str:
    return "-" if v is None else f"r{v}"


def decode_thumb(hw: int, pc: int) -> str:
    """Decode one 16-bit Thumb halfword at address `pc`."""
    hi5 = hw >> 11
    # Format 2: add/subtract (bits 15-11 = 00011) — MUST be tested before
    # format 1, whose bits 15-13 are also 000.
    if hi5 == 0b00011:
        imm = (hw >> 10) & 1
        sub = (hw >> 9) & 1
        rn = (hw >> 6) & 0x7
        rs = (hw >> 3) & 0x7
        rd = hw & 0x7
        op = "sub" if sub else "add"
        if imm:
            return f"{op} r{rd}, r{rs}, #{rn}"
        return f"{op} r{rd}, r{rs}, r{rn}"
    # Format 1: move shifted register (bits 15-13 = 000)
    if (hw >> 13) == 0b000:
        op = (hw >> 11) & 0x3
        off = (hw >> 6) & 0x1F
        rs = (hw >> 3) & 0x7
        rd = hw & 0x7
        return f"{SHIFT_OPS[op]} r{rd}, r{rs}, #{off}"
    # Format 3: mov/cmp/add/sub immediate
    if (hw >> 13) == 0b001:
        op = (hw >> 11) & 0x3
        rd = (hw >> 8) & 0x7
        off = hw & 0xFF
        name = ["mov", "cmp", "add", "sub"][op]
        return f"{name} r{rd}, #{off:#04x}"
    # Format 4: ALU operations
    if (hw >> 10) == 0b010000:
        op = (hw >> 6) & 0xF
        rs = (hw >> 3) & 0x7
        rd = hw & 0x7
        if op in (8, 10, 11):        # tst, cmp, cmn: no writeback
            return f"{ALU_OPS[op]} r{rd}, r{rs}"
        return f"{ALU_OPS[op]} r{rd}, r{rs}"
    # Format 5: hi register operations / BX
    if (hw >> 10) == 0b010001:
        op = (hw >> 8) & 0x3
        h1 = (hw >> 7) & 1
        h2 = (hw >> 6) & 1
        rs = ((hw >> 3) & 0x7) | (h2 << 3)
        rd = (hw & 0x7) | (h1 << 3)
        if op == 0b11:
            if h1:
                # BLX Rs (ARMv5) is not ARMv4T; treat as bx for decoding only
                return f"blx r{rs}"
            return f"bx r{rs}"
        name = ["add", "cmp", "mov"][op]
        if op == 0:      # ADD is the only one that writes a destination
            return f"add {rm(rd)}, r{rs}"
        return f"{name} {rm(rd)}, r{rs}"
    # Format 6: PC-relative load
    if (hw >> 11) == 0b01001:
        rd = (hw >> 8) & 0x7
        word8 = hw & 0xFF
        ea = ((pc + 4) & ~0x2) + (word8 << 2)
        return f"ldr r{rd}, [pc, #{word8 << 2:#x}]   @ literal @ {ea:#010x}"
    # Format 7/8: load/store with register offset / sign-extended
    if (hw >> 12) == 0b0101:
        op = (hw >> 9) & 0x7
        ro = (hw >> 6) & 0x7
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        names = ["str", "strh", "strb", "ldrsb", "ldr", "ldrh", "ldrb", "ldrsh"]
        return f"{names[op]} r{rd}, [r{rb}, r{ro}]"
    # Format 9: load/store with immediate offset (word/byte)
    if (hw >> 13) == 0b011:
        byte = (hw >> 12) & 1
        load = (hw >> 11) & 1
        off = ((hw >> 6) & 0x1F) * (1 if byte else 4)
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        op = ("ldr" if load else "str") + ("b" if byte else "")
        return f"{op} r{rd}, [r{rb}, #{off:#x}]"
    # Format 10: load/store halfword
    if (hw >> 12) == 0b1000:
        load = (hw >> 11) & 1
        off = ((hw >> 6) & 0x1F) * 2
        rb = (hw >> 3) & 0x7
        rd = hw & 0x7
        op = "ldrh" if load else "strh"
        return f"{op} r{rd}, [r{rb}, #{off:#x}]"
    # Format 11: SP-relative load/store
    if (hw >> 12) == 0b1001:
        load = (hw >> 11) & 1
        rd = (hw >> 8) & 0x7
        off = (hw & 0xFF) * 4
        op = "ldr" if load else "str"
        return f"{op} r{rd}, [sp, #{off:#x}]"
    # Format 12: load address
    if (hw >> 12) == 0b1010:
        sp = (hw >> 11) & 1
        rd = (hw >> 8) & 0x7
        off = (hw & 0xFF) * 4
        base = "sp" if sp else "pc"
        return f"add r{rd}, {base}, #{off:#x}"
    # Format 13: add offset to SP
    if (hw >> 8) == 0b10110000:
        sub = (hw >> 7) & 1
        off = (hw & 0x7F) * 4
        return f"{'sub' if sub else 'add'} sp, #{off:#x}"
    # Format 14: push/pop
    if (hw >> 12) == 0b1011:
        load = (hw >> 11) & 1
        rlist = hw & 0xFF
        extra = (hw >> 8) & 1
        regs = [f"r{i}" for i in range(8) if rlist & (1 << i)]
        if extra:
            regs.append("pc" if load else "lr")
        return f"{'pop' if load else 'push'} {{{', '.join(regs)}}}"
    # Format 15: multiple load/store
    if (hw >> 12) == 0b1100:
        load = (hw >> 11) & 1
        rb = (hw >> 8) & 0x7
        rlist = hw & 0xFF
        op = "ldmia" if load else "stmia"
        return f"{op} r{rb}!, {{{rlist:#04x}}}"
    # Format 16: conditional branch (+ SWI when cond == 0b1111)
    if (hw >> 12) == 0b1101:
        cond = (hw >> 8) & 0xF
        if cond == 0b1111:
            return f"swi #{hw & 0xFF:#04x}"
        if cond == 0b1110:
            return "undefined"
        off = hw & 0xFF
        if off & 0x80:
            off -= 0x100
        return f"b{COND[cond]} {pc + 4 + off * 2:#010x}"
    # Format 18: unconditional branch
    if (hw >> 11) == 0b11100:
        off = hw & 0x7FF
        if off & 0x400:
            off -= 0x800
        return f"b {pc + 4 + off * 2:#010x}"
    # Format 19: long branch with link
    if (hw >> 11) == 0b11111:
        h = (hw >> 11) & 1
        off = hw & 0x7FF
        if off & 0x400:
            off -= 0x800
        if h:
            return f"blhi/bl pair hi={h} off={off:#x}"
        return f"bl lo off={off:#x}"
    return f"?? (0x{hw:04x})"


def decode_arm(word: int, pc: int) -> str:
    """Only the branch shapes matter for entry points; everything else is raw."""
    cond = (word >> 28) & 0xF
    if (word & 0x0FFFFFF0) == 0x012FFF10:
        return f"bx r{word & 0xF}"
    if (word & 0x0E000000) == 0x0A000000:
        off = word & 0x00FFFFFF
        if off & 0x00800000:
            off -= 0x01000000
        return f"b{COND[cond] if cond != 14 else ''} {pc + 8 + off * 4:#010x}"
    if (word & 0x0F000000) == 0x0F000000:
        return f"swi #{word & 0x00FFFFFF:#x}"
    if (word & 0x0C000000) == 0x04000000:
        return f"ldr/str (single) cond={COND[cond]}"
    if (word & 0x0E000000) == 0x08000000:
        return f"ldm/stm cond={COND[cond]}"
    return f".word {word:#010x}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--rom-base", type=lambda s: int(s, 0),
                    default=ROM_BASE_DEFAULT)
    ap.add_argument("--thumb", type=lambda s: int(s, 0))
    ap.add_argument("--arm", type=lambda s: int(s, 0))
    ap.add_argument("--count", type=int, default=32,
                    help="number of instructions (not bytes)")
    ap.add_argument("--literal-pool", action="store_true",
                    help="label words that look like in-image pointers")
    args = ap.parse_args(argv)

    with open(args.rom, "rb") as fh:
        rom = fh.read()
    lo, hi = args.rom_base, args.rom_base + len(rom)

    if args.thumb is None and args.arm is None:
        ap.error("give --thumb ADDR or --arm ADDR")

    if args.thumb is not None:
        step, pc = 2, args.thumb
        print(f"Thumb @ {pc:#010x}  ({args.count} instructions)")
        for _ in range(args.count):
            off = pc - args.rom_base
            if off < 0 or off + 2 > len(rom):
                print(f"  {pc:#010x}  past end of image")
                break
            hw = struct.unpack_from("<H", rom, off)[0]
            print(f"  {pc:#010x}  {hw:04x}  {decode_thumb(hw, pc)}")
            pc += step

    if args.arm is not None:
        step, pc = 4, args.arm
        print(f"ARM @ {pc:#010x}  ({args.count} instructions)")
        for _ in range(args.count):
            off = pc - args.rom_base
            if off < 0 or off + 4 > len(rom):
                print(f"  {pc:#010x}  past end of image")
                break
            word = struct.unpack_from("<I", rom, off)[0]
            extra = ""
            if args.literal_pool and lo <= word < hi and word % 4 == 0:
                extra = f"   @ in-image pointer -> {word:#010x}"
            print(f"  {pc:#010x}  {word:08x}  {decode_arm(word, pc)}{extra}")
            pc += step
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
