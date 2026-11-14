#!/usr/bin/env python3
"""Play a .HG6 download as if you were the aircraft's DAU.

Implements the DAU side of reverse/PROTOCOL.md: wait for a 25-byte
"DOWNLOAD LOGS" request, send one record, wait for "TRANSMISSION OK", send the
next, until the file is exhausted. Lets the real HGS .exe (under Wine, via
serialtap.py --virtual) or the stick firmware do a complete download with no
aircraft, so the sandbox and any Linux-native rewrite can be validated against
the original program's own acceptance of the data.

    dau_sim.py /dev/pts/N [--file sample-data/22366_260707_A1.HG6] [--baud 9600]

Record boundaries: a full download is 33x110 + 243x92 + 228 + 200x2817 + 503
bytes (the sizes/counts seen on the wire), which is exactly the 590,117-byte
sample file. A file of another size is split the same way from the front; the
leftover is sent as one final record (that is how a partial capture like
firmware/wire_test.HG6, which lacks the first 8 records, still replays).
Stdlib only. Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import time
import tty

MSG_LEN = 25
REQUESTS = (b"DOWNLOAD LOGS", b"DOWNLOAD CUMULATIVE", b"DOWNLOAD STATUS")
ACK = b"TRANSMISSION OK"
NAK = b"RETRANSMIT"
SCHEDULE = ((33, 110), (243, 92), (1, 228), (200, 2817), (1, 503))
FULL_SIZE = sum(n * s for n, s in SCHEDULE)


def split_records(data: bytes) -> list[bytes]:
    recs, pos = [], 0
    if len(data) != FULL_SIZE:
        # partial file: assume it is the tail of a full download and try to
        # realign on a record boundary that reproduces the known schedule
        missing = FULL_SIZE - len(data)
        sizes = [s for n, s in SCHEDULE for _ in range(n)]
        acc, skip = 0, 0
        while skip < len(sizes) and acc < missing:
            acc += sizes[skip]
            skip += 1
        if acc == missing:
            sizes = sizes[skip:]
        else:
            sizes = [s for n, s in SCHEDULE for _ in range(n)]
    else:
        sizes = [s for n, s in SCHEDULE for _ in range(n)]
    for s in sizes:
        if pos >= len(data):
            break
        recs.append(data[pos:pos + s])
        pos += s
    if pos < len(data):
        recs.append(data[pos:])
    return recs


def open_port(path: str, baud: int) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    tty.cfmakeraw(attrs)
    attrs[2] &= ~(termios.PARENB | termios.CSTOPB | termios.CSIZE | termios.CRTSCTS)
    attrs[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
    speed = getattr(termios, f"B{baud}")
    attrs[4] = attrs[5] = speed
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def write_all(fd: int, data: bytes, byte_delay: float = 0.0) -> None:
    """Write everything; with byte_delay>0, pace to emulate 9600 baud on a pty."""
    if byte_delay <= 0:
        view = memoryview(data)
        while view:
            _, w, _ = select.select([], [fd], [], 1.0)
            if w:
                n = os.write(fd, view[:1024])
                view = view[n:]
        return
    for i in range(0, len(data), 32):
        _, w, _ = select.select([], [fd], [], 1.0)
        os.write(fd, data[i:i + 32])
        time.sleep(byte_delay * 32)


def wait_message(fd: int, buf: bytearray, timeout: float | None) -> bytes | None:
    """Collect bytes until a 25-byte message is complete; return it stripped."""
    deadline = None if timeout is None else time.monotonic() + timeout
    while len(buf) < MSG_LEN:
        wait = None if deadline is None else max(0.0, deadline - time.monotonic())
        r, _, _ = select.select([fd], [], [], wait)
        if not r:
            return None
        try:
            chunk = os.read(fd, 256)
        except OSError:
            chunk = b""
        if not chunk:
            time.sleep(0.01)
            continue
        buf += chunk
    msg, rest = bytes(buf[:MSG_LEN]), buf[MSG_LEN:]
    buf[:] = rest
    return msg.rstrip(b" ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", help="tty to answer on (serialtap --virtual peer, or a real adapter)")
    ap.add_argument("--file", default=os.path.join(os.path.dirname(__file__), "..", "sample-data", "22366_260707_A1.HG6"))
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--pace", action="store_true", help="pace output at --baud even on a pty (realistic timing, ~10 min for a full file)")
    ap.add_argument("--delay", type=float, default=0.0, help="ms to wait after a request/ack before sending the next record (DAU turnaround)")
    ap.add_argument("--once", action="store_true", help="exit after one complete download")
    args = ap.parse_args()

    data = open(args.file, "rb").read()
    records = split_records(data)
    print(f"{args.file}: {len(data)} bytes -> {len(records)} records"
          + ("" if len(data) == FULL_SIZE else f"  (not a full {FULL_SIZE}-byte download; boundaries are best-effort)"), flush=True)
    fd = open_port(args.port, args.baud)
    byte_delay = 10.0 / args.baud if args.pace else 0.0
    buf = bytearray()
    try:
        while True:
            print(f"waiting for request on {args.port} ...", flush=True)
            while True:
                msg = wait_message(fd, buf, None)
                if msg in REQUESTS:
                    break
                print(f"  ignoring {msg!r}", flush=True)
            print(f"<- {msg.decode()}  : streaming {len(records)} records", flush=True)
            t0 = time.monotonic()
            sent = 0
            i = 0
            while i < len(records):
                rec = records[i]
                if args.delay > 0:
                    time.sleep(args.delay / 1000.0)
                write_all(fd, rec, byte_delay)
                sent += len(rec)
                reply = wait_message(fd, buf, 30.0)
                if reply == ACK:
                    i += 1
                    if i % 50 == 0 or i == len(records):
                        print(f"  {i}/{len(records)} records acked, {sent} bytes", flush=True)
                elif reply == NAK:
                    print(f"  RETRANSMIT requested for record {i} ({len(rec)} bytes)", flush=True)
                elif reply in REQUESTS:
                    print(f"  downloader re-sent {reply.decode()} at record {i}; restarting", flush=True)
                    i, sent = 0, 0
                elif reply is None:
                    print(f"  no ack for record {i} within 30 s; giving up this transfer", flush=True)
                    break
                else:
                    print(f"  unexpected {reply!r} after record {i}", flush=True)
            else:
                print(f"download complete: {sent} bytes in {time.monotonic() - t0:.1f} s", flush=True)
                if args.once:
                    return 0
    except KeyboardInterrupt:
        pass
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
