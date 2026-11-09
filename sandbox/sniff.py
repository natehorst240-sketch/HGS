#!/usr/bin/env python3
"""Terminal serial sniffer for the sandbox - a Wireshark-style view in curses.

Follows a serialtap.py log live (or opens a finished one) and shows a frame
list with time, delta, direction, length and a protocol decode, plus a
hex/ASCII detail pane for the selected frame. No GUI needed: works over ssh
next to the Wine window.

    sandbox/sniff.py sandbox/logs/20261109_120000.log       # follows the file as it grows
    sandbox/sniff.py reverse/frida/hgs_rx.log --no-follow   # browse an old capture

Keys: Up/Down/PgUp/PgDn/Home/End move   Enter/Tab toggle detail pane focus
      / filter (substring of the decode, e.g. "TIME HISTORY", ">>", "RETRANSMIT")
      a autoscroll on/off   d HGS decode on/off (raw hex summary instead)
      w write visible frames to pcapng (for Wireshark)   q quit
"""
from __future__ import annotations

import argparse
import curses
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcapng  # noqa: E402

LINE = re.compile(r"\[\s*(\d+)\s*ms\]\s*(>>|<<|A|B)\s+([0-9a-fA-F ]+)\s*$")
RECORD_TYPES = {110: "EXCEEDANCE PARAM", 92: "DISCRETE COUNTER", 228: "CUMULATIVE LOG",
                2817: "TIME HISTORY", 503: "POWER ASSURANCE"}
COMMANDS = {"DOWNLOAD LOGS", "DOWNLOAD CUMULATIVE", "DOWNLOAD STATUS", "TRANSMISSION OK",
            "RETRANSMIT", "STAND BY READY", "READY TO UPLOAD", "UPLOAD DATA", "COPY_FILES",
            "DELETE_FILES", "TRANSFER_FILES"}


class Frame:
    __slots__ = ("no", "ms", "tag", "data")

    def __init__(self, no, ms, tag, data):
        self.no, self.ms, self.tag, self.data = no, ms, tag, data

    @property
    def tx(self) -> bool:
        return self.tag in (">>", "A")


def printable(b: bytes) -> str:
    return "".join(chr(x) if 32 <= x < 127 else "." for x in b)


def decode(fr: Frame) -> str:
    d = fr.data
    if len(d) == 25 and all(32 <= x < 127 for x in d):
        tok = d.decode().rstrip()
        return tok if tok in COMMANDS else f"text? {tok!r}"
    kind = RECORD_TYPES.get(len(d), f"record? {len(d)} B")
    if len(d) >= 25 and all(32 <= x < 127 for x in d[:25]):
        return f"{kind}  \"{d[:25].decode().rstrip()}\""
    return kind


def hexdump(d: bytes, width: int = 16):
    for off in range(0, len(d), width):
        chunk = d[off:off + width]
        hx = " ".join("%02x" % b for b in chunk)
        yield "%06x  %-*s  |%s|" % (off, width * 3 - 1, hx, printable(chunk))


class Tail:
    def __init__(self, path: str, follow: bool):
        self.path, self.follow = path, follow
        self.fh = open(path, encoding="utf-8", errors="replace")
        self.frames: list[Frame] = []
        self.partial = ""

    def poll(self) -> bool:
        new = False
        while True:
            ln = self.fh.readline()
            if not ln:
                break
            if not ln.endswith("\n"):
                self.partial += ln
                break
            ln = self.partial + ln
            self.partial = ""
            m = LINE.search(ln)
            if m:
                data = bytes(int(b, 16) for b in m.group(3).split())
                self.frames.append(Frame(len(self.frames) + 1, int(m.group(1)), m.group(2), data))
                new = True
        return new


def run(stdscr, tail: Tail, use_decode: bool):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)    # TX
    curses.init_pair(2, curses.COLOR_GREEN, -1)   # RX
    curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_WHITE)  # selection
    curses.init_pair(4, curses.COLOR_YELLOW, -1)  # status
    stdscr.nodelay(True)
    stdscr.timeout(100)

    sel, top, autoscroll, filt, status, detail_off = 0, 0, True, "", "", 0
    while True:
        if tail.poll() and autoscroll:
            sel = None  # jump to last visible after filtering
        rows = [f for f in tail.frames if not filt or filt.lower() in (decode(f) + " " + f.tag).lower()]
        if sel is None or sel >= len(rows):
            sel = max(0, len(rows) - 1)

        h, w = stdscr.getmaxyx()
        list_h = max(3, (h - 2) * 3 // 5)
        det_h = h - 2 - list_h
        if sel < top:
            top = sel
        if sel >= top + list_h - 1:
            top = sel - (list_h - 1) + 1

        stdscr.erase()
        hdr = f" {'No.':>5} {'Time':>9} {'Delta':>8} Dir {'Len':>5}  Decode"
        stdscr.addnstr(0, 0, hdr.ljust(w), w - 1, curses.A_REVERSE)
        for i in range(list_h - 1):
            idx = top + i
            if idx >= len(rows):
                break
            fr = rows[idx]
            prev = tail.frames[fr.no - 2] if fr.no >= 2 else fr
            delta = fr.ms - prev.ms
            d = decode(fr) if use_decode else " ".join("%02x" % b for b in fr.data[:24]) + (" ..." if len(fr.data) > 24 else "")
            arrow = "->" if fr.tx else "<-"
            line = f" {fr.no:>5} {fr.ms / 1000:>9.3f} {delta / 1000:>+8.3f} {arrow:^3} {len(fr.data):>5}  {d}"
            attr = curses.color_pair(3) if idx == sel else curses.color_pair(1 if fr.tx else 2)
            stdscr.addnstr(1 + i, 0, line.ljust(w), w - 1, attr)

        y0 = list_h
        if rows:
            fr = rows[sel]
            title = f"── frame {fr.no}  {'HGS->DAU' if fr.tx else 'DAU->HGS'}  {len(fr.data)} bytes  t={fr.ms} ms  {decode(fr)} "
            stdscr.addnstr(y0, 0, title.ljust(w, "─"), w - 1, curses.A_BOLD)
            dump = list(hexdump(fr.data))
            detail_off = max(0, min(detail_off, len(dump) - 1))
            for i, ln in enumerate(dump[detail_off:detail_off + det_h - 1]):
                stdscr.addnstr(y0 + 1 + i, 0, ln, w - 1)
        tx = sum(1 for f in tail.frames if f.tx)
        foot = (f" {len(tail.frames)} frames ({tx} tx / {len(tail.frames) - tx} rx)  showing {len(rows)}"
                f"  filter:[{filt}]  autoscroll:{'on' if autoscroll else 'off'}  "
                f"{'following' if tail.follow else 'static'} {os.path.basename(tail.path)}  {status}  q:quit /:filter w:pcapng")
        stdscr.addnstr(h - 1, 0, foot.ljust(w), w - 1, curses.color_pair(4) | curses.A_REVERSE)
        stdscr.refresh()

        try:
            k = stdscr.getch()
        except curses.error:
            k = -1
        if k == -1:
            continue
        status = ""
        if k in (ord("q"), 27):
            return
        elif k == curses.KEY_UP:
            sel, autoscroll = max(0, sel - 1), False
        elif k == curses.KEY_DOWN:
            sel = min(len(rows) - 1, sel + 1); autoscroll = sel == len(rows) - 1
        elif k == curses.KEY_PPAGE:
            sel, autoscroll = max(0, sel - (list_h - 2)), False
        elif k == curses.KEY_NPAGE:
            sel = min(len(rows) - 1, sel + (list_h - 2)); autoscroll = sel == len(rows) - 1
        elif k == curses.KEY_HOME:
            sel, autoscroll = 0, False
        elif k == curses.KEY_END:
            sel, autoscroll = max(0, len(rows) - 1), True
        elif k in (ord("j"),):
            detail_off += 1
        elif k in (ord("k"),):
            detail_off -= 1
        elif k == ord("a"):
            autoscroll = not autoscroll
        elif k == ord("d"):
            use_decode = not use_decode
        elif k == ord("/"):
            curses.echo(); curses.curs_set(1)
            stdscr.addnstr(h - 1, 0, " filter: ".ljust(w), w - 1)
            try:
                filt = stdscr.getstr(h - 1, 9, 60).decode(errors="replace").strip()
            except Exception:
                filt = ""
            curses.noecho(); curses.curs_set(0)
            sel = None
        elif k == ord("w"):
            out = os.path.splitext(tail.path)[0] + ".pcapng"
            with open(out, "wb") as fh:
                wr = pcapng.Writer(fh)
                base = int(time.time() * 1_000_000)
                for f in rows:
                    wr.frame(pcapng.IF_PROGRAM if f.tx else pcapng.IF_DEVICE, f.data, base + f.ms * 1000)
            status = f"wrote {len(rows)} frames -> {out}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", help="serialtap.py / hgs_sniff.js style log")
    ap.add_argument("--no-follow", action="store_true", help="don't wait for new lines")
    ap.add_argument("--raw", action="store_true", help="start with hex summaries instead of HGS decode")
    args = ap.parse_args()
    tail = Tail(args.log, not args.no_follow)
    tail.poll()
    curses.wrapper(run, tail, not args.raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
