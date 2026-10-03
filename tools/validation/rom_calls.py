#!/usr/bin/env python3
"""Who calls a given Thumb function? Scan the ROM for call sites.

The G14 blocker was a chicken-and-egg problem: the attract demo's own room
traversal runs through code the decompilation does not cover, so there is no
function name to grep for. A watchpoint gives one level of the call chain (it
prints lr), and this gives the rest of it statically: decode every BL/B in the
ROM, keep the ones that land on a requested address, and name each call site by
the dispatch function that contains it.

Both halves are gated. The decoder is checked against a hand-decoded BL in
--self-test; the call-site naming is checked by --why, which shows the dispatch
entry that owns the address. A scanner that cannot be shown to be right is worse
than no scanner, because a wrong "nobody calls this" is a very convincing lie.

Usage
  rom_calls.py --rom ROM.gba --target 0x0806B410
  rom_calls.py --rom ROM.gba --target 0x0806B410,0x0801C26C --why
  rom_calls.py --self-test
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROM_BASE = 0x08000000
IWRAM_BASE = 0x03000000
# The regions that hold code. The ROM is 8 MiB and IWRAM is 32 KiB, and both are
# scanned: IWRAM code is copied into RAM at boot, so a call into it can be encoded
# as a branch to 0x03xxxxxx in the ROM *or* only exist in the running image.
CODE_RANGES = ((ROM_BASE, ROM_BASE + 0x0080_0000), (IWRAM_BASE, IWRAM_BASE + 0x8000))

_ENTRY = re.compile(r"^\{\s*(0x[0-9A-Fa-f]+)u\s*,\s*(\d+)u\s*,\s*(\d+)u\s*,\s*([A-Za-z_]\w*)\s*\}")


class DisasmError(RuntimeError):
    pass


def bl_targets(rom: bytes, addr: int) -> list[tuple[str, int, int]]:
    """Return [(kind, instruction_address, target)] for the branch at `addr`.

    Only the 16-bit Thumb encodings are decoded: `B`, conditional `B`, and the
    `BL`/`BLX` halfword pair. ARM-mode `B`/`BL` are handled by
    `arm_branch_targets`, because the reset vector is ARM and everything after it
    is Thumb.

    WHAT THIS DOES NOT DECODE -- a negative is only as good as its blind spot,
    and this is the blind spot (VALIDATION rule 32):
      * `TBB`/`TBH`, the table-branch instructions. A switch lowered to a byte or
        halfword offset table is a *computed* branch: no literal pointer in the
        ROM, and no `B`/`BL` pointing at it. The room-load chain's own
        dispatcher did not need one -- it used `cmps r0,#0x8 / bls` and an
        explicit compare chain -- but another dispatch table in this ROM might,
        and a negative here would be silent about it.
      * The target of `BX Rm` / `BLX Rm`. `blx_reg` names the register; nothing
        here resolves what was loaded into it.
      * A pointer table built in IWRAM at run time, which is why `--indirect`
        exists and why a pointer-table target needs `xrefs` as well as a scan.

    HOW IT IS GATED: three call sites are checked against bytes read out of the
    ROM, and one of them -- 0x0801C228 -> 0x080746C0 -- is checked against the
    *guest itself*, using a `runtime_trace` dispatch event captured from a real
    run. A decoder checked only against itself is a decoder that agrees with its
    own arithmetic.

    FOUR instances of the same field-width bug have been made in this file, and
    the third was the worst because it was *inside* the decoder: the B test read
    `0xE000 <= top <= 0xE7FF` with `top = hw1 >> 11`, a 5-bit value that can
    never exceed 31, so the branch was unreachable and every 16-bit B in the ROM
    was silently undecoded. A 16-bit B is `top == 0x1C`; a conditional one is
    `top in (0x1A, 0x1B)`. The lesson is not "test your decoder" -- the decoder
    was unit-tested -- it is that *a decoder path needs a test that feeds it the
    instruction it claims to decode*. A branch nobody takes has no test.
    """
    off = addr - ROM_BASE
    if off < 0 or off + 4 > len(rom):
        raise DisasmError(f"address 0x{addr:08X} is outside the ROM")
    hw1 = rom[off] | (rom[off + 1] << 8)
    top = hw1 >> 11

    def sign_extend(value: int, bits: int) -> int:
        return value - (1 << bits) if value & (1 << (bits - 1)) else value

    if top == 0x1C:  # 16-bit unconditional B, `11100 imm11`
        offset = sign_extend(hw1 & 0x7FF, 11) << 1
        return [("B", addr, addr + 4 + offset)]
    if top in (0x1A, 0x1B):  # 16-bit conditional B, `1101 cond imm8`, cond < 0b1110
        offset = sign_extend(hw1 & 0xFF, 8) << 1
        cond = (hw1 >> 8) & 0xF
        names = {0x0: "BEQ", 0x1: "BNE", 0x2: "BCS", 0x3: "BCC", 0x4: "BMI",
                 0x5: "BPL", 0x6: "BVS", 0x7: "BVC", 0x8: "BHI", 0x9: "BLS",
                 0xA: "BGE", 0xB: "BLT", 0xC: "BGT", 0xD: "BLE"}
        return [(names.get(cond, f"B{cond}"), addr, addr + 4 + offset)]

    # BL: hw1 in F000-F7FF. The upper bound is F7FF, *not* FFFF, and that is
    # deliberate. A BL pair is F000-F7FF followed by F800-FFFF, so widening the
    # first-halfword test to FFFF would make a halfword-aligned scan decode the
    # *second* halfword of every BL pair as a fresh first halfword and invent a
    # call site for each one. The scan cannot know instruction boundaries, so the
    # filter has to be the narrower of the two shapes.
    if not (0xF000 <= hw1 <= 0xF7FF):
        return []
    hw2 = rom[off + 2] | (rom[off + 3] << 8)

    # Offset arithmetic, and the fourth instance of this file's field-width bug.
    # There was a branch here reading `0xD000 <= (hw2 >> 11) <= 0xD7FF` and
    # returning a separate "BL32" kind: `hw2 >> 11` is five bits, so that test is
    # false for every possible halfword and the branch was dead. It was the same
    # mistake as the three before it, in the same function, and it hid behind a
    # docstring that promised a behaviour ("reported as ('BL32?', ...)") the code
    # could never perform. The arithmetic below is the one that runs; it is now
    # gated against the guest itself (0x0801C228 -> 0x080746C0, a target read out
    # of a runtime_trace dispatch event, not out of this decoder).
    #
    #   S  = hw1 bit 10
    #   I1 = NOT(J1 XOR S),  I2 = NOT(J2 XOR S),  J1 = hw2 bit 13, J2 = hw2 bit 11
    #   imm = (S<<24)|(I1<<23)|(I2<<22)|((hw1 & 0x3FF)<<12)|((hw2 & 0x7FF)<<1)
    #   target = addr + 4 + SignExtend(imm, 25)
    s = (hw1 >> 10) & 1
    i1 = 1 - (((hw2 >> 13) & 1) ^ s)
    i2 = 1 - (((hw2 >> 11) & 1) ^ s)
    imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((hw1 & 0x3FF) << 12) | ((hw2 & 0x7FF) << 1)
    target = addr + 4 + sign_extend(imm, 25)
    # hw2 bits 15..12 are 1111 for BL and 11J1 0 for BLX, so this distinguishes
    # them. A BLX switches to ARM state, which means bit 0 of the target is 0.
    if (hw2 >> 12) & 0xF == 0xF:
        return [("BL", addr, target)]
    return [("BLX", addr, target & ~1)]


def blx_reg(rom: bytes, addr: int) -> tuple[str, int] | None:
    """Decode the register-indirect `BX Rm` / `BLX Rm` at `addr`.

    `010001 11 L Rm` -> BX Rm when L=0, BLX Rm when L=1. The target is not in
    the instruction, so the only answer is *which register* -- which is the
    question worth asking. Anything reached only through one of these has no
    literal in the ROM and no branch pointing at it, so a scanner that decodes
    only B/BL reports "nobody calls this" for every function-pointer target.

    Returns ("BXREG"|"BLXREG", rm). The REG suffix keeps it distinct from the
    immediate `BLX` that `bl_targets` reports under the same mnemonic.
    """
    off = addr - ROM_BASE
    if off < 0 or off + 2 > len(rom):
        raise DisasmError(f"address 0x{addr:08X} is outside the ROM")
    hw = rom[off] | (rom[off + 1] << 8)
    # bits 15..10 = 010001, bit 9 = L, bits 8..7 = 11, bits 6..3 = 0000, bits 2..0 = Rm.
    # The distinguishing bits are 15..7, so the mask is 0xFF80: BX rN is 0x4700|n,
    # BLX rN is 0x4780|n. (Masking 0xFC00 -- bits 15..10 -- cannot tell the two
    # apart from a MOV, and returns None for every real BX.)
    if (hw & 0xFF80) not in (0x4700, 0x4780):
        return None
    if (hw >> 3) & 0xF:
        return None
    return ("BLXREG" if hw & 0x0080 else "BXREG", hw & 0xF)


def load_dispatch(path: str) -> list[tuple[int, str]]:
    """Parse generated/cart/dispatch_table.cpp into sorted [(addr, name)].

    The name field is captured by the regex, not by splitting on a comma: an
    earlier version took `rsplit(',', 1)` on a line that ends in `},`, got the
    empty tail, and reported every call site as `+0x0` with no function name --
    a silently nameless answer is worse than an unnamed one.
    """
    rows: list[tuple[int, str]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _ENTRY.match(line.strip())
            if m:
                rows.append((int(m.group(1), 16), m.group(4)))
    rows.sort()
    return rows


def enclosing(dispatch: list[tuple[int, str]], addr: int) -> str:
    """The dispatch function that owns `addr` (thumb addresses, bit 0 clear)."""
    a = addr & ~1
    lo, hi = 0, len(dispatch) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if dispatch[mid][0] <= a:
            best = dispatch[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None or a - best[0] > 0x4000:
        return "<no dispatch entry within 16 KiB>"
    return f"{best[1]}+0x{a - best[0]:X}"


def arm_branch_targets(word: int, addr: int) -> tuple[str, int] | None:
    """Decode an ARM-mode B/BL at `addr` whose 32-bit word is `word`.

    BL is `cond 1011 imm24`; B is `cond 1010 imm24`. The target is
    `pc + 8 + (sign_extend(imm24) << 2)`, where pc is the instruction address.
    Needed because the reset vector is ARM, so a caller of a low-address ROM
    routine may be an ARM-mode branch that a Thumb-only scan misses.
    """
    op = (word & 0x0F00_0000) >> 24
    if op == 0x0B:
        kind = "BL"
    elif op == 0x0A:
        kind = "B"
    else:
        return None
    imm = word & 0x00FF_FFFF
    if imm & 0x0080_0000:
        imm -= 0x0100_0000
    return kind, addr + 8 + (imm << 2)


_ROW_RE = re.compile(r"\{\s*0x([0-9A-Fa-f]{8})u\s*,\s*(\d+)u\s*,\s*(\d+)u\s*,\s*(\w+)\s*\}")


def strides_of(root: str = ".") -> dict[int, int]:
    """`{address: instruction stride}` from the generated dispatch table.

    STRIDE is `1u` for a Thumb function (2-byte instructions) and `0u` for ARM
    (4-byte). The third field is a resume-row flag, not an instruction size, and
    the two must not be confused.
    """
    out: dict[int, int] = {}
    dis_path = os.path.join(root, "generated", "cart", "dispatch_table.cpp")
    if not os.path.exists(dis_path):
        return out
    with open(dis_path, encoding="utf-8", errors="replace") as fh:
        for m in _ROW_RE.finditer(fh.read()):
            out[int(m.group(1), 16)] = int(m.group(2))
    return out


def load_arm_ranges(root: str = ".") -> list[tuple[int, int]]:
    """ROM byte ranges that hold **ARM** code, so the Thumb scan can skip them.

    WHY THIS EXISTS. `scan` walks every *halfword* and decodes Thumb, because
    that is how it finds a call site without an instruction-boundary map. In an
    ARM region that is not a weaker decoder, it is a wrong one: the scanner
    reaches the upper halfword of every ARM word, and `0xE211`-style data
    processing words have `hw1 >> 11 == 0x1C`, which is exactly the 16-bit
    unconditional `B` opcode. Concretely, it reported
    `0x0800017A B -> 0x080005A0` -- a *false* call site. The halfword at
    0x0800017A is the top half of the ARM word `0xE2110C01` at 0x08000178, which
    is `tst r1,#0x100`. One invented call site was published as the sole caller
    of a function, and a whole round of work was built on it.

    WHERE THE GROUND TRUTH IS. The dispatch table is it. Rows in
    `generated/cart/dispatch_table.cpp` read `{0xADDRu, STRIDEu, FLAGu, NAME},`
    and STRIDE is the instruction size the generator used for that function:
    `1u` for Thumb (2-byte instructions), `0u` for ARM (4-byte). That is a
    statement about the instruction set made by the toolchain that consumed the
    ROM, not an inference made here, and it covers every compiled function --
    `0x03000C58` is `0u` (ARM), `0x08004342` is `1u` (Thumb).

    `game.toml` is used for one thing only: ARM functions that were DMA-copied
    into IWRAM are compiled at their IWRAM addresses, so a ROM range for them
    needs the copy. Each `[[code_copy]]` gives `source_start` (ROM),
    `runtime_start` (IWRAM) and `size`, and a run is translated only if it lies
    wholly inside one destination span of that declared size. `recompiled_*.cpp`
    headers (`/* 0xADDR  mode=arm  end=0xEND */`) are counted and reported as
    an independent cross-check, not used to place anything.

    Returns merged, sorted `[(lo, hi)]` in ROM address space.
    """
    def merge(rs: list[tuple[int, int]]) -> list[tuple[int, int]]:
        rs.sort()
        out: list[tuple[int, int]] = []
        for lo, hi in rs:
            if out and lo <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], hi))
            else:
                out.append((lo, hi))
        return out

    # --- source 1 (primary): the dispatch table's own per-function stride ------
    # `generated/cart/dispatch_table.cpp` rows are `{0xADDRu, STRIDEu, FLAGu,
    # NAME},` and STRIDE is the *instruction size* the generator used: 1u for a
    # Thumb function (2-byte instructions), 0u for ARM (4-byte). That is
    # ground truth about the instruction set, produced by the toolchain itself
    # rather than inferred here, and it covers the whole ROM.
    strides = strides_of(root)

    # --- source 2: game.toml DMA copies, (source_start, runtime_start, size) ---
    # Only used to translate an IWRAM ARM run back to the ROM bytes it was
    # copied from. `size` is taken from the same block, not assumed: an earlier
    # version used a 0x10000 slack test instead, which silently admitted ARM
    # functions that lie outside every destination and produced a nonsense
    # delta -- it claimed ROM 0x08004178..0x08004360 was ARM when the dispatch
    # table labels 0x08004342 a Thumb function entry.
    copies: list[tuple[int, int, int]] = []
    toml_path = os.path.join(root, "game.toml")
    if os.path.exists(toml_path):
        with open(toml_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        blk_re = re.compile(
            r"\[\[code_copy\]\](?P<body>.*?)(?=\n\[\[|\Z)", re.S)
        for b in blk_re.finditer(text):
            body = b.group("body")
            g = lambda k: (int(m.group(1), 16) if (m := re.search(
                rf"{k}\s*=\s*(0x[0-9A-Fa-f]+)", body)) else None)
            src, dst, size = g("source_start"), g("runtime_start"), g("size")
            if src is not None and dst is not None:
                copies.append((src, dst, size if size is not None else 0))

    # --- source 3 (cross-check only): the generated per-function headers ------
    hdr = re.compile(r"/\* 0x([0-9A-Fa-f]{8})  mode=arm  end=0x([0-9A-Fa-f]{8}) ")
    hdr_arm: list[tuple[int, int]] = []
    gen_dir = os.path.join(root, "generated", "cart")
    for name in sorted(os.listdir(gen_dir)) if os.path.isdir(gen_dir) else []:
        if not name.startswith("recompiled_") or not name.endswith(".cpp"):
            continue
        with open(os.path.join(gen_dir, name), encoding="utf-8", errors="replace") as fh:
            for m in hdr.finditer(fh.read()):
                lo, hi = int(m.group(1), 16), int(m.group(2), 16)
                if 0 < hi - lo < 0x8000:
                    hdr_arm.append((lo, hi))

    # Build the ARM runs from the stride field, per address space. A stride-0
    # row names the first byte of a 4-byte ARM *instruction*, so the row's own
    # extent is 2 bytes wide and is not enough: the 4-byte word covers two
    # halfwords, and it is the upper one (`hw1 >> 11 == 0x1C`, the 16-bit
    # unconditional-B opcode) that the halfword walk mis-decodes. Widening to 4
    # bytes is what makes the guard actually cover the word it must protect.
    arm_runs: list[tuple[int, int]] = []
    for lo, hi in merge([(a, a + 4) for a, s in strides.items() if s == 0]):
        arm_runs.append((lo, hi))

    rom_ranges: list[tuple[int, int]] = [(lo, hi) for lo, hi in arm_runs
                                         if ROM_BASE <= lo < ROM_BASE + 0x800_0000]
    n_rom_direct = len(rom_ranges)
    for lo, hi in arm_runs:
        for src, dst, size in copies:
            if size and dst <= lo and hi <= dst + size:
                delta = src - dst
                rom_ranges.append((lo + delta, hi + delta))
                break
    merged = merge(rom_ranges)

    # Rule 39: print the item counts, and treat zero-on-non-empty as a failure
    # of the extraction rather than as evidence that the ROM has no ARM code.
    print(f"   arm_ranges: {len(strides)} dispatch rows "
          f"({sum(1 for s in strides.values() if s == 0)} ARM), {len(arm_runs)} ARM run(s) "
          f"({n_rom_direct} in ROM, {len(copies)} copy pair(s)), "
          f"{len(hdr_arm)} generated header(s) -> {len(merged)} ROM range(s)"
          + ("" if merged else "  <-- NONE DERIVED: ARM regions will be Thumb-decoded"))
    for lo, hi in merged:
        print(f"     arm  0x{lo:08X}..0x{hi:08X}")

    # Rule 32: state the blind spot. The runs above cover only functions that
    # have dispatch rows. ARM code the generator never compiled (or that has no
    # rows at all) is still Thumb-decoded here, and cannot be detected as such
    # from these files.
    if not strides:
        print("     (no dispatch table: ARM ranges fell back to ZERO, not to a guess)")
    return merged


def scan(rom: bytes, targets: set[int], ranges: tuple[tuple[int, int], ...],
         dispatch: list[tuple[int, str]], want_why: bool,
         ind_branch: bool = False,
         arm_ranges: list[tuple[int, int]] | None = None) -> list[tuple[str, int, int, str]]:
    """Every Thumb or ARM B/BL that lands on a target, with its call site.

    Scans both instruction sets because the reset vector is ARM and everything
    else is Thumb. Returns [(kind, site_addr, target, owner)].

    With `ind_branch`, also returns every register-indirect `BX Rm` / `BLX Rm`
    as (kind, site_addr, rm, owner). Those have no target in the instruction, so
    they cannot be matched against `--target`; they are the *only* trace left by
    a function that is reached through a pointer table, which is why a target
    with no branch and no literal is not yet a target with no caller.
    """
    hits: list[tuple[str, int, int, str]] = []
    rom_len = len(rom)
    arm_ranges = arm_ranges or []

    def in_arm(a: int) -> bool:
        return any(lo <= a < hi for lo, hi in arm_ranges)

    for lo, hi in ranges:
        start = max(0, lo - ROM_BASE)
        stop = min(rom_len - 8, hi - ROM_BASE)
        for off in range(start, stop, 2):
            addr = ROM_BASE + off
            # Inside a declared ARM region the Thumb decode is not a weaker
            # decoder but a wrong one: the walk reaches the upper halfword of
            # every ARM word, and an ARM data-processing word has hw1>>11 ==
            # 0x1C, which is the 16-bit unconditional-B opcode. Skip it. The
            # ARM decode below already covers this address space.
            if in_arm(addr):
                continue
            hw1 = rom[off] | (rom[off + 1] << 8)
            # Cheap pre-filter. `hw1 >> 11` is a 5-bit opcode field, so the masks
            # must be 5-bit too: 0b11101 = B/uncond-BL, 0b11110 = BL pair,
            # 0b11111 = BL pair. (An earlier version compared this 5-bit value
            # against 16-bit masks like 0xF7FF, matched nothing, and printed a
            # confident "nobody calls this" -- the exact false negative a unit
            # test of the decoder cannot catch, because the decoder was right and
            # the loop around it was wrong.)
            top = hw1 >> 11
            if top in (0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F):
                for kind, at, target in bl_targets(rom, addr):
                    if target & ~1 in targets:
                        hits.append((kind, at, target & ~1,
                                     enclosing(dispatch, at) if want_why else ""))
            # ARM-mode candidate: `cond 1011 imm24` (BL) or `cond 1010 imm24` (B).
            if off % 4 == 0:
                word = int.from_bytes(rom[off:off + 4], "little")
                got = arm_branch_targets(word, addr)
                if got and got[1] & ~1 in targets:
                    kind, target = got
                    hits.append((kind, addr, target & ~1,
                                 enclosing(dispatch, addr) if want_why else ""))
            # Register-indirect BX/BLX: the target is not in the instruction, so
            # these cannot be matched against `--target` -- but for a function
            # reached through a pointer table they are the *only* trace left.
            if ind_branch:
                got_reg = blx_reg(rom, addr)
                if got_reg:
                    hits.append((got_reg[0], addr, got_reg[1],
                                 enclosing(dispatch, addr) if want_why else ""))
    return hits


def parse_targets(spec: str, *, align: bool) -> set[int]:
    """Parse a `--target` list.

    `align=True` masks off bit 0, which a **branch** target needs because a
    Thumb entry point carries it. A **data** address must not be masked:
    0x03000025 and 0x03000024 are different IWRAM byte fields, so applying the
    branch rule to a literal lookup makes `--xrefs 0x03000025` search for
    0x03000024 and report a clean "no references" for the wrong field. That is
    not a wrong answer, it is a wrong *question* that prints like a finding.
    """
    out = {int(t, 0) for t in spec.split(",") if t.strip()}
    return {t & ~1 for t in out} if align else out


def xrefs(rom: bytes, targets: set[int], base: int, dispatch: list[tuple[int, str]],
          why: bool) -> list[tuple[int, int, int, str]]:
    """Find literal-pool references: 32-bit words equal to a target address.

    The companion to `scan`: if nothing branches to a target, it may be reached
    indirectly through a function-pointer table -- exactly the shape the
    framework's own `[[jump_table]]` models. A pointer table leaves a second,
    easier trace, because the address appears as a literal in the ROM.

    Returns [(word_offset_in_rom, literal_value, word_address, owner)].
    """
    wanted: dict[int, int] = {}
    for t in targets:
        wanted[t] = t
        # A thumb function pointer keeps bit 0 set, so a code address must be
        # matched both ways. A DATA address must NOT be: 0x03000025 and
        # 0x03000026 are two different IWRAM byte fields, and the |1 variant
        # would report one as a reference to the other.
        if ROM_BASE <= t < ROM_BASE + 0x01000000:
            wanted[t | 1] = t | 1
    hits: list[tuple[int, int, int, str]] = []
    # `len(rom) - 4` as the exclusive bound drops the final aligned word of the
    # image: the loop needs off+4 <= len(rom), so the bound is len(rom) - 3.
    # A 4-byte literal in the last 4 bytes was therefore unsearchable.
    for off in range(0, len(rom) - 3, 4):
        word = int.from_bytes(rom[off:off + 4], "little")
        if word not in wanted:
            continue
        addr = ROM_BASE + off
        owner = enclosing(dispatch, addr) if why else ""
        hits.append((off, word, addr, owner))
    return hits


def self_test(rom: bytes) -> int:
    """Check the decoder against hand-decoded ROM bytes.

    * **Positive 1.** 0x0806B418 holds `F000 FA24`. `s=0`, `imm10=0`,
      `hw2=0xFA24` gives `j1=1`, `j2=1`, `imm11=0x224`; `i1=i2=1^(1^s)=0`, so
      the offset is `0x224<<1 = 0x448` and the target is
      `0x0806B418+4+0x448 = 0x0806B864`. That is the entry of
      `gf_tfunc_0806B864`, and an independent watchpoint trace of the same run
      shows `dispatch pc=0x0806B8FA` and `mem_w pc=0x0806B92C` inside that
      sequence, so the two instruments agree on the neighbourhood.
    * **Positive 2.** 0x0806B4AC holds `F000 FB10`. `s=0`, `imm10=0`,
      `hw2=0xFB10` gives `j1=1`, `j2=1`, `imm11=0x310`; `i1=i2=1^(1^s)=0`, so
      the offset is `0x310<<1 = 0x620` and the target is
      `0x0806B4AC+4+0x620 = 0x0806BAD0`, which is inside the ROM.
    * **Negative.** 0x0806B41C holds `4C14` = `LDR r4,[pc,#0x50]`, which is not a
      branch and must decode to nothing.
    * **ARM, against the documented ROM identity.** 0x08000000 holds `EA00002E`,
      an unconditional ARM `B`; the target is `0x08000000+8+(0x2E<<2) =
      0x080000C0`, which is the entry point recorded independently in
      `docs/ROM_IDENTITY.json`. A decoder that agrees with the ROM's documented
      identity is not agreeing with itself. 0x080000C0 holds `E3A00012` =
      `mov r0,#0x12`, which is not a branch and must decode to nothing.

    * **B, the path that was silently dead.** The 16-bit `B` test once read
      `0xE000 <= top <= 0xE7FF` with `top = hw1 >> 11`. `top` is five bits, so
      that comparison is false for every possible input and the branch was
      unreachable -- no `B` in the ROM was ever decoded, and `--target` on a
      function reached only by a tail-call `B` reported "nobody calls this".
      Both encodings are now fed to the decoder explicitly below.

    Both Thumb positives were found by reading the ROM bytes, not by trusting the
    decoder: the first is corroborated from the other side by a watchpoint trace of
    the same code path, and an earlier version of this test *failed* because its
    hand-written expectation was off by 2 bytes. That is why the arithmetic is
    written out in full -- a self-test whose expectations were copied from its own
    output tests nothing.

    The G15 case, 0x0801C228, is gated one level better: its expected target was
    read out of a live run's trace rather than out of the ROM, so the decoder is
    compared against the guest instead of against itself. That distinction earned
    its keep immediately -- a hand-decode of that same instruction using
    imm10<<19 instead of imm10<<12 disagreed with the guest, and the first
    instinct was to blame the code generator for agreeing with the trace rather
    than with the hand-decode.
    """
    cases = [
        (0x0806B418, "BL", 0x0806B864),
        (0x0806B4AC, "BL", 0x0806BAD0),
        (0x0806B41C, None, None),
        # Gated against the GUEST, not against this decoder. Halfwords
        # hw1=0xF058, hw2=0xFA4A at file offset 0x1C228. A live run of the attract
        # demo with GBARECOMP_ABORT_ON_MEM_WRITE_ADDR on 0x03000024 recorded
        #   #33010804 call     pc=0x0801C22C
        #   #33010805 dispatch pc=0x080746C0 <gf_tfunc_080746C0+0x0>
        # i.e. the branch at 0x0801C228 was taken and landed at 0x080746C0.
        # That expectation was read out of logs/routes/g15-room3.err.log and was
        # never checked against a decoder before it was used here -- which is how
        # a wrong hand-decode (imm10<<19 instead of imm10<<12) came to look like
        # proof that the generator was broken. The arithmetic is written out in
        # bl_targets; this entry is the check that it agrees with the CPU.
        (0x0801C228, "BL", 0x080746C0),
        # Corroborated from the same trace by a different field. The BL at
        # 0x0801BBE6 links 0x0801BBEA|1 = 0x0801BBEB, and #33010770 records
        #   dispatch pc=0x0801BBEA lr=0x0801BBEB
        # so 0x0801BBE6 is the only BL in the ROM that can have produced that
        # link value, and gf_tfunc_0801BBEA is entered by *returning* from
        # 0x08000C14 rather than by being called. The trace pins the return
        # address here; the target below comes from the same offset arithmetic
        # already gated by 0x0801C228 and 0x0806B418.
        (0x0801BBE6, "BL", 0x08000C14),
    ]
    bad = 0

    # A decoder path that never receives the instruction it claims to decode has
    # no test. `E7FE` is `b #-4` (top5 = 0x1C, imm11 = 0x7FE -> -2 -> *2 -> -4)
    # and `DAFD` is `bge #-6` (top5 = 0x1B, cond = 0xA, imm8 = 0xFD -> -3 -> -6).
    # Both sit at 0x08000000 so that pc+4+offset lands back on 0x08000000, which
    # makes the expected target checkable by eye rather than by running it.
    synth = (0xE7FE).to_bytes(2, "little") + (0xDAFD).to_bytes(2, "little") + b"\x00\x00"
    got_b = bl_targets(synth, 0x08000000)
    got_cond = bl_targets(synth, 0x08000002)
    ok = bool(got_b) and got_b[0][0] == "B" and got_b[0][2] == 0x08000000
    print(f"  {'ok  ' if ok else 'FAIL'} bl_targets() decodes the 16-bit unconditional B "
          f"(got {got_b})")
    if not ok:
        bad += 1
    ok = bool(got_cond) and got_cond[0][0] == "BGE" and got_cond[0][2] == 0x08000000
    print(f"  {'ok  ' if ok else 'FAIL'} bl_targets() decodes the 16-bit conditional B "
          f"(got {got_cond})")
    if not ok:
        bad += 1

    # `0x4703` = BX r3, `0x4784` = BLX r4. A pointer-table call site has no
    # target in the instruction at all, so this is the only question askable.
    synth2 = (0x4703).to_bytes(2, "little") + (0x4784).to_bytes(2, "little") + b"\x00\x00"
    ok = blx_reg(synth2, ROM_BASE) == ("BXREG", 3) and \
        blx_reg(synth2, ROM_BASE + 2) == ("BLXREG", 4) and \
        blx_reg(synth2, 0x08000004) is None
    print(f"  {'ok  ' if ok else 'FAIL'} blx_reg() decodes BX/BLX Rm and rejects a "
          f"non-branch (got {blx_reg(synth2, ROM_BASE)}, {blx_reg(synth2, ROM_BASE+2)}, "
          f"{blx_reg(synth2, ROM_BASE+4)})")
    if not ok:
        bad += 1

    # BL and BLX-immediate share hw1 exactly; they differ only in hw2 bits 15..12
    # (1111 = BL, 11J1 0 = BLX). hw2=0xE800 is a BLX and hw2=0xF800 the same BL:
    # both have J1=J2=1 (bits 13 and 11) and S=0, so I1=I2=0 and the offset is
    # 0 -- the target is the following instruction either way, and only the kind
    # differs. Feeding the decoder both is the point. Nothing in the ROM was
    # checked for this, because no run has been traced through a BLX-immediate,
    # and a path with no observed instance is exactly the path that stayed broken
    # for six bugs. The first version of this test expected hw2=0xE000, derived by
    # hand and wrong: bit 11 is J2, and 0xE000 has it clear, so that halfword is a
    # BLX with I2=1 and an offset of 0x400000. The decoder was right and the
    # expectation was not.
    synth_blx = (0xF000).to_bytes(2, "little") + (0xE800).to_bytes(2, "little")
    synth_bl = (0xF000).to_bytes(2, "little") + (0xF800).to_bytes(2, "little")
    got_blx = bl_targets(synth_blx, ROM_BASE)
    got_bl = bl_targets(synth_bl, ROM_BASE)
    ok = bool(got_blx) and got_blx[0][0] == "BLX" and bool(got_bl) and \
        got_bl[0][0] == "BL" and got_blx[0][2] == got_bl[0][2] == ROM_BASE + 4
    print(f"  {'ok  ' if ok else 'FAIL'} bl_targets() separates BLX-immediate from BL "
          f"(got {got_blx}, {got_bl})")
    if not ok:
        bad += 1
    # The ARM/Thumb boundary. This is the one that cost a whole round, and it is
    # the only check here that needs the *project* rather than synthetic bytes,
    # because the failure is a property of where the instruction boundary falls,
    # not of the decoder. 0x08000178 holds the ARM word 0xE2110C01 =
    # `tst r1,#0x100` (opcode 0b1000, rotate 0xC, imm8 0x01 -> 0x100). Its upper
    # halfword, 0xE211, has `hw1 >> 11 == 0x1C`, which is the 16-bit
    # unconditional-B opcode, so a halfword walk decodes it as `B 0x080005A0` and
    # invents a call site. Checked three ways: the range is derived, the range
    # covers the word, and a scan of that range with the ranges applied reports
    # no call site inside the blob.
    armr = load_arm_ranges(".")
    dis_strides = strides_of(".")
    blob = 0x08000178
    covered = any(lo <= blob < hi for lo, hi in armr)
    ok = bool(armr) and covered
    print(f"  {'ok  ' if ok else 'FAIL'} load_arm_ranges() derives {len(armr)} ROM ARM "
          f"range(s); 0x{blob:08X} covered={covered}")
    if not ok:
        bad += 1
    # The suppression itself: scan the blob's own extent with and without the
    # ranges. Without them the halfword walk must produce the false positive
    # (that is the regression being pinned); with them it must produce nothing.
    span = (blob, blob + 0x40)
    dis = load_dispatch(os.path.join("generated", "cart", "dispatch_table.cpp")) \
        if os.path.exists(os.path.join("generated", "cart", "dispatch_table.cpp")) else []
    with_arm = scan(rom, {0x080005A0}, (span,), dis, False, False, armr)
    without = scan(rom, {0x080005A0}, (span,), dis, False, False, [])
    ok = not with_arm and bool(without)
    print(f"  {'ok  ' if ok else 'FAIL'} ARM ranges suppress the invented 0x0800017A "
          f"call site (with={len(with_arm)} hits, without={len(without)} hits)")
    if not ok:
        bad += 1
    # The over-derivation. Suppressing too little leaves false positives; but
    # suppressing too much is its own silent failure -- it can hide a real Thumb
    # call site. The check: no derived range may contain an address the dispatch
    # table itself labels Thumb. 0x08004342 is `gf_tfunc_08004342` with stride
    # 1u, and an earlier version of this function claimed 0x08004178..0x08004360
    # was ARM because it paired an IWRAM ARM function with a DMA copy using a
    # 0x10000 slack test instead of the declared `size`.
    thumb_leak = [a for a, s in dis_strides.items()
                  if s == 1 and any(lo <= a < hi for lo, hi in armr)]
    ok = not thumb_leak
    print(f"  {'ok  ' if ok else 'FAIL'} ARM ranges claim no address the dispatch table "
          f"labels Thumb ({len(thumb_leak)} leak(s)"
          + (f", e.g. 0x{thumb_leak[0]:08X}" if thumb_leak else "") + ")")
    if not ok:
        bad += 1

    # The same class of error one layer out: the target list itself. Bit 0 is
    # part of a *branch* target and is NOT part of a data address. A single
    # `& ~1` applied to every --target made `--xrefs 0x03000025` search for
    # 0x03000024 -- a different IWRAM byte field -- and print "no references",
    # which reads as a finding about the game and is a finding about the query.
    got = parse_targets("0x03000025", align=False)
    ok = got == {0x03000025}
    print(f"  {'ok  ' if ok else 'FAIL'} parse_targets() keeps a data address's bit 0 "
          f"for --xrefs (got {[hex(t) for t in sorted(got)]})")
    if not ok:
        bad += 1
    got = parse_targets("0x080005A1", align=True)
    ok = got == {0x080005A0}
    print(f"  {'ok  ' if ok else 'FAIL'} parse_targets() drops bit 0 for a branch "
          f"target (got {[hex(t) for t in sorted(got)]})")
    if not ok:
        bad += 1

    # And the mirror image inside xrefs(): matching `t | 1` is what makes a
    # thumb function pointer findable, but for a data address it manufactures
    # a reference to the *next* byte field. Built synthetically so both halves
    # are in one buffer: 0x03000025 next to 0x03000026, and 0x080005A0 next to
    # its own thumb spelling 0x080005A1.
    synth3 = b"".join(w.to_bytes(4, "little") for w in
                      (0x03000025, 0x03000026, 0x080005A0, 0x080005A1)) + b"\x00" * 4
    words = {off: int.from_bytes(synth3[off:off + 4], "little") for off in (0, 4, 8, 12)}
    data_hits = {w for _, w, _, _ in xrefs(synth3, {0x03000025}, ROM_BASE, [], False)}
    ok = data_hits == {0x03000025}
    print(f"  {'ok  ' if ok else 'FAIL'} xrefs() does not report 0x03000026 as a "
          f"reference to the field 0x03000025 (got "
          f"{[hex(w) for w in sorted(data_hits)]})")
    if not ok:
        bad += 1
    code_hits = {w for _, w, _, _ in xrefs(synth3, {0x080005A0}, ROM_BASE, [], False)}
    ok = code_hits == {0x080005A0, 0x080005A1}
    print(f"  {'ok  ' if ok else 'FAIL'} xrefs() still matches both spellings of a "
          f"thumb code address (got {[hex(w) for w in sorted(code_hits)]})")
    if not ok:
        bad += 1

    for addr, want_kind, want_target in cases:
        got = bl_targets(rom, addr)
        if want_kind is None:
            if got:
                print(f"  FAIL 0x{addr:08X}: LDR decoded as {got[0][0]} 0x{got[0][2]:08X}")
                bad += 1
            else:
                print(f"  ok   0x{addr:08X} not a branch -> no target")
            continue
        if not got:
            print(f"  FAIL 0x{addr:08X}: decoder found nothing")
            bad += 1
            continue
        kind, at, target = got[0]
        ok = kind == want_kind and target == want_target
        print(f"  {'ok  ' if ok else 'FAIL'} 0x{addr:08X} -> {kind} 0x{target:08X}")
        if not ok:
            print(f"        expected {want_kind} 0x{want_target:08X}")
            bad += 1

    # The ARM decoder gets the strongest available check: the reset vector at
    # 0x08000000 holds `EA00002E`, an unconditional B whose decoded target is
    # 0x080000C0 -- the entry point recorded independently in
    # docs/ROM_IDENTITY.json. A decoder that agrees with the documented identity
    # of the ROM is not agreeing with itself.
    for addr, want_kind, want_target in [(0x08000000, "B", 0x080000C0),
                                          (0x080000C0, None, None)]:
        off = addr - ROM_BASE
        word = int.from_bytes(rom[off:off + 4], "little")
        got = arm_branch_targets(word, addr)
        if want_kind is None:
            print(f"  {'ok  ' if got is None else 'FAIL'} 0x{addr:08X} arm 0x{word:08X}"
                  f"{' not a branch' if got is None else ' decoded as %s' % (got,)}")
            if got is not None:
                bad += 1
            continue
        if got is None:
            print(f"  FAIL 0x{addr:08X} arm 0x{word:08X} -> no branch found")
            bad += 1
            continue
        kind, target = got
        ok = kind == want_kind and target == want_target
        print(f"  {'ok  ' if ok else 'FAIL'} 0x{addr:08X} arm 0x{word:08X} -> "
              f"{kind} 0x{target:08X}")
        if not ok:
            print(f"        expected {want_kind} 0x{want_target:08X} "
                  f"(the entry point in docs/ROM_IDENTITY.json)")
            bad += 1

    # End-to-end: the scan loop must actually FIND the two call sites above.
    # The decoder was right in both broken versions above; the loop around it was
    # wrong twice (a range that covered nothing, then a 5-bit field compared
    # against 16-bit masks). A decoder unit test cannot see either fault, so the
    # loop needs its own check with a known-positive answer.
    found = scan(rom, {0x0806B864, 0x0806BAD0}, ((ROM_BASE, ROM_BASE + 0x0080_0000),),
              [], False)
    sites = {(at, target) for _, at, target, _ in found}
    for want_site, want_target in [(0x0806B418, 0x0806B864), (0x0806B4AC, 0x0806BAD0)]:
        ok = (want_site, want_target) in sites
        print(f"  {'ok  ' if ok else 'FAIL'} scan() finds the call site at "
              f"0x{want_site:08X} -> 0x{want_target:08X}")
        if not ok:
            bad += 1

    # load_dispatch must produce a *name*, not an empty string. A parse that
    # silently yields empty names still "works" -- it just answers every --why
    # query with `+0x0`, which reads like an answer.
    import tempfile
    sample = ("// AUTO-GENERATED by gba_recompile. DO NOT EDIT.\n"
              "extern \"C\" const DispatchEntry kDispatchTable[] = {\n"
              "    {0x0806B410u, 1u, 0u, gf_tfunc_0806B410},\n"
              "    {0x03007D18u, 1u, 0u, gf_afunc_03007D18},\n"
              "};\n")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "dispatch_table.cpp")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(sample)
        rows = load_dispatch(p)
    got_names = [n for _, n in rows]
    ok = got_names == ["gf_afunc_03007D18", "gf_tfunc_0806B410"]
    print(f"  {'ok  ' if ok else 'FAIL'} load_dispatch() names both entries and sorts them "
          f"(got {got_names})")
    if not ok:
        bad += 1
    if rows:
        owner = enclosing(rows, 0x0806B418)
        ok = owner == "gf_tfunc_0806B410+0x8"
        print(f"  {'ok  ' if ok else 'FAIL'} enclosing() names the owning function "
              f"(got {owner!r})")
        if not ok:
            bad += 1
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", help="the base ROM; required unless --self-test")
    ap.add_argument("--target", default="", help="comma-separated target addresses")
    ap.add_argument("--range", action="append", default=[], metavar="LO:HI",
                    help="extra code range to scan, e.g. 0x03000000:0x03008000 "
                         "(repeatable; the ROM is always scanned)")
    ap.add_argument("--dispatch", default=os.path.join("generated", "cart", "dispatch_table.cpp"),
                    help="dispatch table used to name call sites")
    ap.add_argument("--why", action="store_true", help="name the function containing each call site")
    ap.add_argument("--xrefs", action="store_true",
                    help="find literal-pool references to the target instead of call sites")
    ap.add_argument("--indirect", action="store_true",
                    help="also report every register-indirect BX/BLX Rm in the scanned "
                         "ranges; the target is not in the instruction, so these are "
                         "listed as (site, register), not matched against --target")
    ap.add_argument("--self-test", action="store_true", help="check the decoder and exit")
    ap.add_argument("--root", default=".",
                    help="project root used to find game.toml and generated/cart/ when "
                         "deriving which ROM ranges are ARM (default: the cwd)")
    args = ap.parse_args(argv)

    if args.self_test:
        if not args.rom:
            print("--self-test needs --rom: the check is against real ROM bytes", file=sys.stderr)
            return 2
        rom = open(args.rom, "rb").read()
        print(f"decoder self-test against {args.rom}")
        return self_test(rom)

    if not args.rom:
        print("--rom is required", file=sys.stderr)
        return 2
    if not args.target and not args.indirect:
        print("--target is required unless --indirect (comma-separated addresses)",
              file=sys.stderr)
        return 2

    rom = open(args.rom, "rb").read()
    targets = parse_targets(args.target, align=not args.xrefs)
    if not targets:
        targets = set()
    if not os.path.exists(args.dispatch):
        print(f"dispatch table not found: {args.dispatch}", file=sys.stderr)
        return 2
    dispatch = load_dispatch(args.dispatch)

    ranges = list(CODE_RANGES)
    for spec in args.range:
        lo_s, _, hi_s = spec.partition(":")
        if not hi_s:
            print(f"--range needs LO:HI, got {spec}", file=sys.stderr)
            return 2
        ranges.append((int(lo_s, 0), int(hi_s, 0)))

    span = ", ".join(f"0x{lo:08X}..0x{hi:08X}" for lo, hi in ranges)
    print(f"== rom_calls: scanning {span} for "
          + ("literal references to " if args.xrefs else "callers of ")
          + ", ".join(f"0x{t:08X}" for t in sorted(targets)))
    if args.xrefs:
        hits = xrefs(rom, targets, ROM_BASE, dispatch, args.why)
        if not hits:
            print("   no 32-bit word in the ROM holds any of them")
            return 1
        for off, word, addr, owner in hits:
            print(f"   literal 0x{word:08X} at 0x{addr:08X}   {owner}" if args.why
                  else f"   literal 0x{word:08X} at 0x{addr:08X}")
        print(f"\n   {len(hits)} literal reference(s)")
        return 0

    # parse_targets(align=True) has already masked bit 0 for this path.
    hits = scan(rom, targets, tuple(ranges), dispatch, args.why, args.indirect,
                load_arm_ranges(args.root))
    if not hits:
        print("   no B/BL in the scanned ranges targets any of them")
        return 1
    direct = [h for h in hits if not h[0].endswith("REG")]
    for kind, at, reached, owner in sorted(hits, key=lambda h: h[1]):
        if kind.endswith("REG") and reached < 16:
            label = f"0x{at:08X}  {kind} r{reached}"
        else:
            label = f"0x{at:08X}  {kind} -> 0x{reached:08X}"
        print(f"   {label}   {owner}" if args.why else f"   {label}")
    n_ind = len(hits) - len(direct)
    print(f"\n   {len(direct)} call site(s)"
          + (f", {n_ind} register-indirect BX/BLX" if n_ind else ""))
    if args.indirect and not direct:
        # Say what is left to look for, so the empty result is an instruction and
        # not just an absence.
        print("   nothing branches directly: the target is reached through a pointer "
              "that is computed at run time, or through a jump table -- use --xrefs "
              "and the --indirect list to find where that pointer is built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
