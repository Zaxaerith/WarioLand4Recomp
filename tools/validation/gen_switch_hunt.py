#!/usr/bin/env python3
"""Generate tests/input/switch-hunt.keyinput.txt.

Goal (priority G): press the room-0 switch, i.e. make the game write
gSwitchPressed (0x03000C0D).  The switch sprite sits at (1696,1024) and Wario's
walkable band in that room is x 1758..2337, so the route walks into the switch
and then hammers every plausible "press" action at both ends of the band.

Active-low keyinput: A 0x03FE  B 0x03FD  START 0x03F7  RIGHT 0x03EF
LEFT 0x03DF  UP 0x03BF  DOWN 0x037F  none 0x03FF.
"""
import sys

NONE, A, B, START, RIGHT, LEFT, UP, DOWN = 0x03FF, 0x03FE, 0x03FD, 0x03F7, 0x03EF, 0x03DF, 0x03BF, 0x037F
LEFT_A, LEFT_DOWN, RIGHT_A, RIGHT_DOWN = LEFT & A, LEFT & DOWN, RIGHT & A, RIGHT & DOWN

presses = []          # (frame, keyinput)


def put(frame, value, hold=6):
    presses.append((frame, value))
    presses.append((frame + hold, NONE))


# --- known-good menu prefix (verified by every earlier route) -----------------
put(5300, START, 8)                     # press START
for f in (5800, 6600, 7400):            # three A presses through the file select
    put(f, A, 8)
put(8200, RIGHT, 8)                     # move cursor right
put(8600, RIGHT, 8)
for f in (9000, 10000, 11000):          # confirm
    put(f, A, 8)

# --- walk to the switch and hammer every press action -------------------------
put(12000, LEFT, 600)                   # walk left until blocked (x ~ 1758)

t = 12650
for cycle in range(14):
    # 1. plain jump, then DOWN in mid-air (body slam)
    put(t, A, 3)
    put(t + 8, DOWN, 34)
    # 2. jump and slam immediately
    put(t + 50, A, 3)
    put(t + 54, DOWN, 30)
    # 3. crouch on the spot
    put(t + 95, DOWN, 30)
    # 4. walk a step into the object and jump-slam
    put(t + 135, LEFT, 12)
    put(t + 150, LEFT_A, 3)
    put(t + 156, LEFT_DOWN, 30)
    # 5. walk a step the other way and slam
    put(t + 200, RIGHT, 12)
    put(t + 214, RIGHT_A, 3)
    put(t + 220, RIGHT_DOWN, 30)
    # 6. UP / B probes (door and attack)
    put(t + 265, UP, 24)
    put(t + 300, B, 20)
    t += 340

# A held from 18000 to the end: "run into it" while jumping repeatedly.
put(18000, RIGHT, 40)
for f in range(18100, 20000, 45):
    put(f, RIGHT_A, 4)
presses.append((20000, NONE))

seen = {}
for f, v in presses:
    seen[f] = v                    # last write at a frame wins
with open(sys.argv[1] if len(sys.argv) > 1 else "tests/input/switch-hunt.keyinput.txt", "w", newline="\n") as fh:
    fh.write("# gbarecomp-keyinput-v1\n# frame,keyinput_active_low\n")
    for f in sorted(seen):
        fh.write(f"{f},0x{seen[f]:04X}\n")
print(f"wrote {len(seen)} entries, last frame {max(seen)}")
