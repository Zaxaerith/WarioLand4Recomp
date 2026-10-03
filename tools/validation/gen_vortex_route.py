#!/usr/bin/env python3
"""Generate an input replay that runs room 0's stage-clear vortex down.

Room 0 of level 0 (`0x083F2F88`) has exactly three live sprites
(`func_801E0EC` decodes the header list; that observation lived in the
`obs-f39` trace, which the release cleanup removed — re-measure with
`tools/validation/room_probe.py` or the sprite mode of `wario_watch.py`):

  gid 7  PSPRITE_SWITCH   at (1696, 1024)  -- the switch's stage, already on
  gid 41 PSPRITE_VORTEX   at (2016, 1024)  -- the exit vortex, pose 24 SPOSE_IDLE
  gid 41 (dormant)        at ( 480, 1280)  -- a second vortex on Wario's own row

Wario spawns at (2016, 1279).  A standing jump apexes at y = 1047 (232 px),
and the vortex's overlap slab is y in [991, 1055] (`VortexSetCommonProperties`
gives it hitbox Up = 4, Down = 0), 13 px above that apex; the run+jump of
`tests/input/f49-runjump.keyinput.txt` instead lands him on a ledge at
(2337, 1087).  This route reproduces that climb and then jumps back LEFT off
the ledge, which should carry him through the vortex slab.

The 18-row menu navigation is copied verbatim from
`tests/input/new-game.keyinput.txt` (see docs/KNOWN_ISSUES.md, "The menu
navigation is not optional"); only the gameplay tail differs.

Active-low masks are computed from the button bit table, never by hand:
    A 0x0001  B 0x0002  SELECT 0x0004  START 0x0008
    RIGHT 0x0010  LEFT 0x0020  UP 0x0040  DOWN 0x0080
    R 0x0100  L 0x0200
"""

import argparse
from pathlib import Path

BUTTONS = {
    "A": 0x0001,
    "B": 0x0002,
    "SELECT": 0x0004,
    "START": 0x0008,
    "RIGHT": 0x0010,
    "LEFT": 0x0020,
    "UP": 0x0040,
    "DOWN": 0x0080,
    "R": 0x0100,
    "L": 0x0200,
}
IDLE = 0x03FF


def mask(*names: str) -> int:
    value = IDLE
    for name in names:
        value &= ~BUTTONS[name]
    return value & 0x03FF


NAV = [
    # (frame, mask) -- verbatim from tests/input/new-game.keyinput.txt
    (5300, mask("START")),
    (5308, IDLE),
    (5800, mask("A")),
    (5808, IDLE),
    (6600, mask("A")),
    (6608, IDLE),
    (7400, mask("A")),
    (7408, IDLE),
    (8200, mask("RIGHT")),
    (8208, IDLE),
    (8600, mask("RIGHT")),
    (8608, IDLE),
    (9000, mask("A")),
    (9008, IDLE),
    (10000, mask("A")),
    (10008, IDLE),
    (11000, mask("A")),
    (11008, IDLE),
]


def build(jump: int, hold: int, fall: int) -> list[tuple[int, int]]:
    rows = list(NAV)
    # Phase 1: run right and jump onto the ledge at (2337, 1087) -- the
    # f49-runjump climb, re-measured at 10-frame cadence in logs/routes/obs-f49.
    rows += [
        (12000, mask("A", "RIGHT")),
        (12040, mask("RIGHT")),
    ]
    # Phase 2: from the ledge, jump back left through the vortex slab.
    rows += [
        (jump, mask("A", "LEFT")),
        (jump + hold, mask("LEFT")),
        (jump + hold + fall, IDLE),
    ]
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jump", type=int, default=12120,
                        help="frame to start the leftward jump (default 12120)")
    parser.add_argument("--hold", type=int, default=45,
                        help="frames to hold A during the jump (default 45)")
    parser.add_argument("--fall", type=int, default=15,
                        help="frames to keep LEFT after releasing A (default 15)")
    parser.add_argument("--out", default="tests/input/f51-vortex.keyinput.txt")
    args = parser.parse_args()

    rows = build(args.jump, args.hold, args.fall)
    lines = [
        "# gbarecomp-keyinput-v1",
        "# frame,keyinput_active_low",
        f"# f51: room 0 stage-clear vortex -- jump={args.jump} holdA={args.hold} fall={args.fall}",
    ]
    for frame, value in rows:
        lines.append(f"{frame},0x{value:04X}")
    text = "\n".join(lines) + "\n"
    Path(args.out).write_text(text, encoding="ascii")
    print(f"wrote {args.out}: {len(rows)} rows, last frame "
          f"{rows[-1][0]} (0x{rows[-1][1]:04X})")
    for frame, value in rows[18:]:
        names = [n for n, bit in BUTTONS.items() if not value & bit]
        print(f"  {frame:6d}  0x{value:04X}  {'+'.join(names) if names else 'IDLE'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
