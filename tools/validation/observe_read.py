#!/usr/bin/env python3
"""Read guest memory from a running observer-mode session (--tcp-observe).

Why this exists (see docs/KNOWN_ISSUES.md G13): under `--tcp` the framework
bypasses GBARECOMP_INPUT_REPLAY, so the routes that most need memory reads --
player-driven input routes -- had no read channel at all and had to be probed
with write watchpoints.  `--tcp-observe PORT` attaches a read-only debug server
to a *windowed* run instead, and that run keeps its input replay.  This script
is the client: it waits for the port, polls `run_status` until the guest passes
each mark, then reads a memory space and writes it to disk.

Commands used (gbarecomp-main/src/debug/tcp_debug_server.cpp):
  run_status  -> {"ok":true,"run":"windowed","parked":false,"frame":N,...}
  read_iwram  -> addr=0x03000000 len=32768      (cmd_read_region, needs addr+len)
  read_ewram  -> addr=0x02000000 len=262144
  read_vram   -> addr=0x06000000 len=98304
  read_pal    -> addr=0x05000000 len=1024
  read_oam    -> addr=0x07000000 len=1024

Usage:
  observe_read.py --port 19995 --marks 11600,12000,13000 --space iwram \
      --outdir logs/routes/obs-explore --timeout 300
"""
import argparse
import json
import socket
import sys
import time
from pathlib import Path

SPACES = {
    "iwram": ("read_iwram", 0x03000000, 32768),
    "ewram": ("read_ewram", 0x02000000, 262144),
    "vram": ("read_vram", 0x06000000, 98304),
    "pal": ("read_pal", 0x05000000, 1024),
    "oam": ("read_oam", 0x07000000, 1024),
}


class Client:
    def __init__(self, port: int, host: str = "127.0.0.1", timeout: float = 20.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.buf = b""
        self.next_id = 1

    def send(self, cmd: str, **fields):
        ident = self.next_id
        self.next_id += 1
        payload = {"id": ident, "cmd": cmd}
        payload.update(fields)
        self.sock.sendall((json.dumps(payload) + "\n").encode())
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("server closed the connection")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode())

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def connect(port: int, deadline: float) -> Client:
    last = None
    while time.time() < deadline:
        try:
            return Client(port)
        except OSError as exc:
            last = exc
            time.sleep(0.25)
    raise SystemExit(f"could not connect to 127.0.0.1:{port} within the timeout: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--marks", required=True, help="comma list of guest frames")
    ap.add_argument("--space", default="iwram", choices=sorted(SPACES))
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--timeout", type=float, default=300.0,
                    help="seconds to wait for each mark")
    ap.add_argument("--connect-timeout", type=float, default=30.0)
    args = ap.parse_args()

    marks = sorted(int(m) for m in args.marks.split(",") if m.strip())
    tag = args.tag or Path(args.outdir).name
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    cmd, base, length = SPACES[args.space]

    client = connect(args.port, time.time() + args.connect_timeout)
    index = []
    try:
        for mark in marks:
            deadline = time.time() + args.timeout
            frame = -1
            while time.time() < deadline:
                status = client.send("run_status")
                frame = int(status.get("frame", -1))
                if frame >= mark:
                    break
                if status.get("run") != "windowed":
                    print(f"note: run_status run={status.get('run')} parked={status.get('parked')}")
                time.sleep(0.05)
            if frame < mark:
                print(f"warning: gave up waiting for mark {mark} (last frame {frame})")
            reply = client.send(cmd, addr=f"0x{base:08X}", len=length)
            if not reply.get("ok"):
                print(f"error: {cmd} failed: {reply.get('error')}")
                return 2
            data = bytes.fromhex(reply["data"])
            path = outdir / f"{tag}-{args.space}-f{frame:06d}.bin"
            path.write_bytes(data)
            index.append({"mark": mark, "frame": frame, "space": args.space,
                          "bytes": len(data), "file": path.name})
            print(f"frame {frame} -> {path} ({len(data)} bytes)")
    finally:
        client.close()

    with open(outdir / f"{tag}-index.json", "w", encoding="utf-8") as fh:
        json.dump({"space": args.space, "base": f"0x{base:08X}", "length": length,
                   "captures": index}, fh, indent=2)
    print(f"wrote {outdir / (tag + '-index.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
