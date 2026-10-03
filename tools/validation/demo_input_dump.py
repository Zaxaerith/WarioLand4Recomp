#!/usr/bin/env python3
"""Dump the guest's attract-demo input stream out of a TCP IWRAM snapshot.

The decomp declares two IWRAM arrays (linker.ld):
    gDemoInputs        = 0x03002cc8  (256 x u16, active-HIGH held-button bits)
    gDemoInputLengths  = 0x03002ec8  (256 x u16, frames per entry)
    gDemoSequenceIndex = 0x030030c8  (u16, current position during playback)
    gDemoButtonPressTimer = 0x030030ca
Reading them straight out of a snapshot answers two questions the source text
cannot: which button sequence the game itself uses to traverse the level, and
how many frames each press lasts.  That stream is directly convertible into a
`gbarecomp-keyinput-v1` replay file (GBA KEYINPUT is active LOW, so the file
value is 0x03FF ^ held).

Usage: demo_input_dump.py <snapshot.bin> [--csv OUT] [--limit N]
"""
import argparse
import csv
import struct
import sys
from pathlib import Path

IWRAM_BASE = 0x03000000
G_DEMO_INPUTS = 0x03002CC8
G_DEMO_INPUT_LENGTHS = 0x03002EC8
G_DEMO_SEQUENCE_INDEX = 0x030030C8
G_DEMO_BUTTON_PRESS_TIMER = 0x030030CA
DEMO_INPUT_SIZE = 256

BUTTONS = [(0x0001, "A"), (0x0002, "B"), (0x0010, "RIGHT"), (0x0020, "LEFT"),
           (0x0040, "UP"), (0x0080, "DOWN"), (0x0008, "START"), (0x0004, "SELECT"),
           (0x0100, "R"), (0x0200, "L")]


def names(held: int) -> str:
    got = [n for bit, n in BUTTONS if held & bit]
    return "+".join(got) if got else "none"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--csv")
    ap.add_argument("--limit", type=int, default=DEMO_INPUT_SIZE)
    args = ap.parse_args()

    blob = Path(args.snapshot).read_bytes()
    if len(blob) < 32768:
        print(f"error: {args.snapshot} is {len(blob)} bytes, expected >= 32768", file=sys.stderr)
        return 2

    def off(addr: int) -> int:
        return addr - IWRAM_BASE

    def u16(addr: int) -> int:
        return struct.unpack_from("<H", blob, off(addr))[0]

    index = u16(G_DEMO_SEQUENCE_INDEX)
    timer = u16(G_DEMO_BUTTON_PRESS_TIMER)
    print(f"snapshot        : {Path(args.snapshot).name}")
    print(f"sequence index  : {index}")
    print(f"press timer     : {timer}")

    rows = []
    frame = 0
    total = 0
    for i in range(min(args.limit, DEMO_INPUT_SIZE)):
        held = u16(G_DEMO_INPUTS + 2 * i)
        length = u16(G_DEMO_INPUT_LENGTHS + 2 * i)
        if held == 0 and length == 0:
            break
        rows.append((i, held, length, frame, frame + length))
        frame += length
        total += length

    print(f"entries         : {len(rows)}  (total {total} frames = {total / 59.7275:.1f} s)")
    for i, held, length, start, end in rows:
        mark = " <- current" if i == index else ""
        print(f"  [{i:3d}] 0x{held:04X} {names(held):<12} {length:5d} frames  "
              f"({start:6d}..{end:6d}){mark}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["index", "held_active_high", "held_hex", "buttons", "length",
                        "start_frame", "end_frame"])
            for i, held, length, start, end in rows:
                w.writerow([i, held, f"0x{held:04X}", names(held), length, start, end])
        print(f"wrote {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
