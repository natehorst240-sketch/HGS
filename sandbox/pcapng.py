#!/usr/bin/env python3
"""Minimal pcapng writer/reader for serial captures, so Wireshark can open them.

Each direction is its own pcapng interface (Wireshark shows it in the
"Interface" column; the HGS dissector in sandbox/wireshark/hgs.lua uses it to
label HGS->DAU vs DAU->HGS). Link type is LINKTYPE_USER0 (147): raw payload,
no framing header.

As a CLI it converts the text logs this repo already has (Frida hgs_sniff.js,
serialtap.py, the hardware sniffer's A/B lines) to pcapng:

    pcapng.py reverse/frida/hgs_rx.log out.pcapng
    pcapng.py sandbox/logs/20261109_120000.log -      # to stdout (pipe into wireshark -k -i -)
"""
from __future__ import annotations

import re
import struct
import sys
import time

LINKTYPE_USER0 = 147
IF_PROGRAM = 0   # program (HGS/Wine side) -> device
IF_DEVICE = 1    # device (DAU) -> program
IF_NAMES = {IF_PROGRAM: "program->device (HGS TX)", IF_DEVICE: "device->program (DAU TX)"}

LINE = re.compile(r"\[\s*(\d+)\s*ms\]\s*(>>|<<|A|B)\s+([0-9a-fA-F ]+)\s*$")
TAG_IF = {">>": IF_PROGRAM, "A": IF_PROGRAM, "<<": IF_DEVICE, "B": IF_DEVICE}


def _opt(code: int, data: bytes) -> bytes:
    pad = (-len(data)) % 4
    return struct.pack("<HH", code, len(data)) + data + b"\0" * pad


def _block(btype: int, body: bytes) -> bytes:
    total = 12 + len(body)
    return struct.pack("<II", btype, total) + body + struct.pack("<I", total)


class Writer:
    """Writes a pcapng stream with two interfaces. Timestamps in microseconds."""

    def __init__(self, fh, comment: str = "HGS sandbox serial capture"):
        self.fh = fh
        shb = struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)
        shb += _opt(1, comment.encode()) + _opt(4, b"HGS sandbox serialtap") + _opt(0, b"")
        fh.write(_block(0x0A0D0D0A, shb))
        for ifid in (IF_PROGRAM, IF_DEVICE):
            idb = struct.pack("<HHI", LINKTYPE_USER0, 0, 65535)
            idb += _opt(2, IF_NAMES[ifid].encode()) + _opt(9, bytes([6])) + _opt(0, b"")  # if_tsresol 10^-6
            fh.write(_block(0x00000001, idb))
        fh.flush()

    def frame(self, ifid: int, data: bytes, ts_us: int | None = None) -> None:
        if ts_us is None:
            ts_us = int(time.time() * 1_000_000)
        pad = (-len(data)) % 4
        body = struct.pack("<IIIII", ifid, ts_us >> 32, ts_us & 0xFFFFFFFF, len(data), len(data))
        body += data + b"\0" * pad
        self.fh.write(_block(0x00000006, body))
        self.fh.flush()

    def close(self) -> None:
        self.fh.close()


def read(path: str):
    """Yield (ifid, ts_us, data) from a pcapng written by Writer (or any pcapng
    with EPBs; other block types are skipped)."""
    with open(path, "rb") as fh:
        blob = fh.read()
    pos = 0
    while pos + 12 <= len(blob):
        btype, total = struct.unpack_from("<II", blob, pos)
        if total < 12 or pos + total > len(blob):
            break
        if btype == 0x00000006:
            ifid, hi, lo, caplen, _ = struct.unpack_from("<IIIII", blob, pos + 8)
            data = blob[pos + 28:pos + 28 + caplen]
            yield ifid, (hi << 32) | lo, data
        pos += total


def convert_log(src: str, dst) -> int:
    w = Writer(dst)
    n = 0
    base = int(time.time() * 1_000_000)
    with open(src, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            m = LINE.search(ln)
            if not m:
                continue
            ms, tag, hexs = int(m.group(1)), m.group(2), m.group(3)
            data = bytes(int(b, 16) for b in hexs.split())
            w.frame(TAG_IF[tag], data, base + ms * 1000)
            n += 1
    return n


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    out = sys.stdout.buffer if dst == "-" else open(dst, "wb")
    n = convert_log(src, out)
    if dst != "-":
        out.close()
        print(f"{n} frames -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
