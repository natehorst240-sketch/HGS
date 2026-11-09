#!/usr/bin/env python3
"""End-to-end check of the sandbox serial chain, no Wine or hardware needed.

Starts serialtap.py (virtual null-modem) and dau_sim.py, then plays the
downloader (what HGS / the stick does) on the program-side pty: send
"DOWNLOAD LOGS", read records framed by idle gaps, ack each. Passes when the
reassembled bytes equal the source file and the tap log holds every frame.

    sandbox/selftest.py [--file sample-data/22366_260707_A1.HG6]
"""
from __future__ import annotations

import argparse
import os
import re
import select
import subprocess
import sys
import tempfile
import termios
import time
import tty

HERE = os.path.dirname(os.path.abspath(__file__))


def pad25(m: bytes) -> bytes:
    return (m + b" " * 25)[:25]


def read_record(fd: int, first_timeout: float, idle: float = 0.06) -> bytes:
    buf = bytearray()
    deadline = time.monotonic() + first_timeout
    while True:
        wait = idle if buf else max(0.0, deadline - time.monotonic())
        r, _, _ = select.select([fd], [], [], wait)
        if r:
            chunk = os.read(fd, 4096)
            if chunk:
                buf += chunk
                continue
        if buf or time.monotonic() >= deadline:
            return bytes(buf)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=os.path.join(HERE, "..", "sample-data", "22366_260707_A1.HG6"))
    args = ap.parse_args()
    expected = open(args.file, "rb").read()

    tmp = tempfile.mkdtemp(prefix="hgs_selftest_")
    peer_file, log = os.path.join(tmp, "peer"), os.path.join(tmp, "tap.log")
    tap = subprocess.Popen([sys.executable, os.path.join(HERE, "serialtap.py"), "--virtual", "--no-link",
                            "--peer-file", peer_file, "--log", log, "-q"],
                           stdout=subprocess.PIPE, text=True)
    first = tap.stdout.readline()
    m = re.search(r"program side (\S+)\s+<->\s+peer side (\S+)", first)
    if not m:
        print("serialtap did not start:", first)
        tap.kill()
        return 1
    prog_path, peer_path = m.groups()
    sim = subprocess.Popen([sys.executable, os.path.join(HERE, "dau_sim.py"), peer_path, "--file", args.file, "--once"],
                           stdout=subprocess.PIPE, text=True)
    time.sleep(0.5)

    fd = os.open(prog_path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    tty.cfmakeraw(a)
    termios.tcsetattr(fd, termios.TCSANOW, a)

    ok = True
    try:
        t0 = time.monotonic()
        os.write(fd, pad25(b"DOWNLOAD LOGS"))
        got = bytearray()
        records = 0
        while True:
            rec = read_record(fd, 3.0 if records else 5.0)
            if not rec:
                break
            got += rec
            records += 1
            os.write(fd, pad25(b"TRANSMISSION OK"))
        dt = time.monotonic() - t0
        print(f"downloader: {records} records, {len(got)} bytes in {dt:.1f} s")
        if bytes(got) != expected:
            ok = False
            print(f"FAIL: reassembled {len(got)} bytes != file {len(expected)} bytes")
        else:
            print("PASS: reassembled download == source file")
    finally:
        os.close(fd)
        sim.wait(timeout=10)
        tap.terminate()
        tap.wait(timeout=5)

    tx = rx = rxbytes = 0
    for ln in open(log):
        mm = re.search(r"\] (>>|<<) ([0-9a-f ]+)$", ln.rstrip("\n"))
        if not mm:
            continue
        n = len(mm.group(2).split())
        if mm.group(1) == ">>":
            tx += 1
        else:
            rx += 1
            rxbytes += n
    print(f"tap log {log}: {tx} TX frames, {rx} RX frames, {rxbytes} RX bytes")
    if tx != records + 1 or rxbytes != len(expected):
        ok = False
        print("FAIL: tap log does not account for every frame")
    else:
        print("PASS: tap log complete")
    dec = os.path.join(HERE, "..", "reverse", "frida", "decode_capture.py")
    if os.path.exists(dec):
        print(f"analyze it with: python3 {os.path.relpath(dec)} {log}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
