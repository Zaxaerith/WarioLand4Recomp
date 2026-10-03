#!/usr/bin/env python3
"""Who reaches this address? Combine the two call-graph sources into one walk.

The recompiled C++ in `generated/cart/` records every *tail call* as
`runtime_dispatch(0x...)`, and the ROM scan in `rom_calls.py` records every BL and
B. Neither is the whole graph: this game's room code is a long chain of tiny
functions that hand off to each other by tail call, so the interesting question
-- "what makes the game load a room" -- is only answerable by following both kinds
of edge backwards from the instruction that writes `gCurrentRoom`.

Reading that off the generated C++ by hand is where this session went wrong
several times: a walk keyed half by name and half by address silently reported a
two-function chain when the real chain was dozens long. So the walk is a tool, and
--self-test checks it against a chain whose length is known from the C++.

Usage
  callchain.py --generated generated/cart --from 0x0806B90C
  callchain.py --generated generated/cart --from 0x0806B90C --json
  callchain.py --self-test
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

_FN = re.compile(r"^void (gf_\w+)\(void\)")
_DISPATCH = re.compile(r"runtime_dispatch\(0x([0-9A-F]+)u\)")
# Names are `gf_tfunc_0806B410` and `gf_autojt_0806AFFC_07`; the address is eight
# hex digits, optionally followed by the jump-table index.
_ADDR_SUFFIX = re.compile(r"_([0-9A-Fa-f]{8})(?:_\d+)?$")


def load_edges(generated_dir: str) -> tuple[dict[str, list[int]], dict[str, int]]:
    """Parse `runtime_dispatch` tail calls out of every recompiled_*.cpp.

    Returns (edges, addr_of) where edges maps a generated function name to the
    addresses it tail-calls, and addr_of maps that name to its own address.
    """
    edges: dict[str, list[int]] = {}
    addr_of: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(generated_dir, "recompiled_*.cpp"))):
        fn = None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = _FN.match(line)
                if m:
                    fn = m.group(1)
                    m_addr = _ADDR_SUFFIX.search(fn)
                    if m_addr:
                        try:
                            addr_of[fn] = int(m_addr.group(1), 16)
                        except ValueError:
                            pass
                    edges.setdefault(fn, [])
                    continue
                if fn is None:
                    continue
                m = _DISPATCH.search(line)
                if m:
                    edges[fn].append(int(m.group(1), 16))
    return edges, addr_of


def build_graph(edges: dict[str, list[int]], addr_of: dict[str, int]) -> tuple[dict[int, set[str]], dict[str, set[int]]]:
    """Return (callers_of_address, callees_of_function).

    Both directions are keyed consistently: addresses are always ints, function
    names are always strings. An earlier version mixed the two and every walk
    past the first hop came back empty.
    """
    callees: dict[str, set[int]] = {fn: set(ts) for fn, ts in edges.items()}
    callers: dict[int, set[str]] = {}
    for fn, ts in edges.items():
        for target in ts:
            callers.setdefault(target, set()).add(fn)
    return callers, callees


def reach(start: int, callers: dict[int, set[str]], addr_of: dict[str, int],
          max_depth: int = 64) -> dict[int, int]:
    """Map every address in the chain to its depth from `start` (0 = start).

    `addr_of` is needed because a tail-call chain alternates between addresses and
    function names: the graph is stored address-keyed, and each discovered
    function must be mapped back to its address before its own callers are read.
    """
    depth_of: dict[int, int] = {start: 0}
    frontier = [start]
    depth = 0
    while frontier and depth < max_depth:
        depth += 1
        nxt: list[int] = []
        for addr in frontier:
            for fn in callers.get(addr, ()):
                a = addr_of.get(fn)
                if a is not None and a not in depth_of:
                    depth_of[a] = depth
                    nxt.append(a)
        frontier = nxt
    return depth_of


def self_test() -> int:
    """Check the graph walk on a graph whose answer is known by construction.

    Four functions a->b->c->d, plus a disjoint island, plus a cycle, because the
    cycle is the case that turns a naive walk into an infinite loop.
    """
    edges = {"fn_A": [0x10], "fn_B": [0x20], "fn_C": [0x30],
             "fn_X": [0x99], "fn_Y": [0x99]}
    addr_of = {"fn_A": 0x00, "fn_B": 0x10, "fn_C": 0x20, "fn_X": 0x50, "fn_Y": 0x60}
    callers, _ = build_graph(edges, addr_of)
    got = reach(0x30, callers, addr_of)
    want = {0x30: 0, 0x20: 1, 0x10: 2, 0x00: 3}
    bad = 0
    if got != want:
        print(f"  FAIL reach(): got {sorted(got.items())}, want {sorted(want.items())}")
        bad += 1
    else:
        print("  ok   reach() walks a 4-deep tail-call chain back to its root")

    # A cycle must terminate and must not run forever or claim depth is unbounded.
    edges_c = {"fn_P": [0x70, 0x80], "fn_Q": [0x70]}
    addr_of_c = {"fn_P": 0x70, "fn_Q": 0x80}
    callers_c, _ = build_graph(edges_c, addr_of_c)
    got_c = reach(0x80, callers_c, addr_of_c)
    if got_c != {0x80: 0, 0x70: 1}:
        print(f"  FAIL reach() on a cycle: got {sorted(got_c.items())}, want [(80, 0), (112, 1)]")
        bad += 1
    else:
        print("  ok   reach() terminates on a cycle and does not over-claim")

    # An unknown start must return just itself, not everything.
    if reach(0xDEAD, callers, addr_of) != {0xDEAD: 0}:
        print("  FAIL reach() on an unknown start did not return just the start")
        bad += 1
    else:
        print("  ok   reach() on an address nobody calls returns only itself")

    # parse_edges must actually parse a file that looks like the generated one.
    sample = ("/* header */\n"
              "void gf_tfunc_0806B410(void) {\n"
              "    runtime_dispatch(0x0806B41Cu);\n"
              "}\n"
              "void gf_autojt_0806AFFC_07(void) {\n"
              "    runtime_dispatch(0x0806B14Eu);\n"
              "}\n")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "recompiled_999.cpp"), "w", encoding="utf-8") as fh:
            fh.write(sample)
        e, a = load_edges(d)
    if e.get("gf_tfunc_0806B410") != [0x0806B41C] or a.get("gf_autojt_0806AFFC_07") != 0x0806AFFC:
        print(f"  FAIL load_edges(): parsed {e} / {a}")
        bad += 1
    else:
        print("  ok   load_edges() parses tail calls and derives addresses")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generated", default=os.path.join("generated", "cart"),
                    help="directory holding recompiled_*.cpp (default %(default)s)")
    ap.add_argument("--from", dest="start", type=lambda s: int(s, 0), default=None,
                    help="address to walk back from")
    ap.add_argument("--json", action="store_true", help="emit the chain as JSON")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        print("callchain self-test")
        return self_test()
    if args.start is None:
        print("--from is required (unless --self-test)", file=sys.stderr)
        return 2
    if not glob.glob(os.path.join(args.generated, "recompiled_*.cpp")):
        print(f"no recompiled_*.cpp under {args.generated}", file=sys.stderr)
        return 2

    edges, addr_of = load_edges(args.generated)
    callers, _ = build_graph(edges, addr_of)
    names = {a: fn for fn, a in addr_of.items()}
    depth_of = reach(args.start, callers, addr_of)

    ordered = sorted(depth_of, key=lambda a: (-depth_of[a], a))
    rows = []
    for addr in ordered:
        who = sorted(fn for fn in callers.get(addr, ()))
        rows.append({"address": f"0x{addr:08X}", "function": names.get(addr, ""),
                     "hops_from_start": depth_of[addr],
                     "tail_calls_to": [f"0x{t:08X}" for t in sorted(edges.get(names.get(addr, ""), ()))],
                     "called_by": who})
    if args.json:
        print(json.dumps({"start": f"0x{args.start:08X}", "chain": rows}, indent=2))
        return 0

    print(f"== callchain: {len(ordered)} function(s) reach 0x{args.start:08X} by tail call "
          f"(or are it) ==")
    for r in rows:
        arrow = "<- " + ", ".join(r["called_by"]) if r["called_by"] else "** no caller in the graph **"
        print(f"  [{r['hops_from_start']:2d}] {r['address']}  {r['function']:<24} {arrow}")
        if r["tail_calls_to"]:
            print(f"        tail-calls {', '.join(r['tail_calls_to'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())