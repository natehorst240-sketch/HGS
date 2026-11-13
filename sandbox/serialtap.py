#!/usr/bin/env python3
"""Serial tap for the Wine sandbox: the Linux stand-in for the Frida hook and com0com.

Creates a pseudo-terminal, points the sandbox's COMn at it, and bridges it to
either a real serial adapter or a second pty (a virtual null-modem for
dau_sim.py / dau_emulator.py). Every byte in both directions is logged with
timestamps in the format reverse/frida/decode_capture.py reads:
    [   ms] >> hex...     program -> device
    [   ms] << hex...     device  -> program

    serialtap.py --real /dev/ttyUSB0 [--baud 9600] [--com 1] [--log tap.log]
    serialtap.py --virtual [--peer-file sandbox/logs/peer] ...   (prints the peer pty path)
    ... --pcap capture.pcapng        also write pcapng for Wireshark (sandbox/wireshark/)
    ... --pcap /path/to/fifo         live: mkfifo it first, then `wireshark -k -i /path/to/fifo`

Stdlib only (no pyserial). In --real mode the adapter is set to 8N1 at --baud;
if the program changes the baud rate on its side, the change is mirrored to
the adapter. Frames are split on --idle ms of silence per direction (the HGS
protocol frames by pause, so this matches the wire's own framing).
"""
from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import threading
import time
import tty

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcapng  # noqa: E402

BAUDS = {
    1200: termios.B1200, 2400: termios.B2400, 4800: termios.B4800,
    9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
    57600: termios.B57600, 115200: termios.B115200,
}
SPEED_TO_BAUD = {v: k for k, v in BAUDS.items()}


def printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def open_real(path: str, baud: int) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    set_raw_8n1(fd, baud)
    return fd


def set_raw_8n1(fd: int, baud: int) -> None:
    attrs = termios.tcgetattr(fd)
    tty.cfmakeraw(attrs)
    attrs[2] &= ~(termios.PARENB | termios.CSTOPB | termios.CSIZE | termios.CRTSCTS)
    attrs[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
    speed = BAUDS[baud]
    attrs[4] = speed
    attrs[5] = speed
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def new_pty() -> tuple[int, int, str]:
    master, slave = os.openpty()
    attrs = termios.tcgetattr(slave)
    tty.cfmakeraw(attrs)
    termios.tcsetattr(slave, termios.TCSANOW, attrs)
    return master, slave, os.ttyname(slave)


def slave_baud(slave_fd: int) -> int | None:
    try:
        return SPEED_TO_BAUD.get(termios.tcgetattr(slave_fd)[5])
    except termios.error:
        return None


def _is_fifo(path: str) -> bool:
    import stat
    try:
        return stat.S_ISFIFO(os.stat(path).st_mode)
    except OSError:
        return False


class Logger:
    def __init__(self, path: str | None, idle_s: float, quiet: bool, pcap: str | None = None):
        self.fh = open(path, "a") if path else None
        self.idle = idle_s
        self.quiet = quiet
        self.t0 = time.monotonic()
        self.wall0 = time.time()
        self.buf = {">>": bytearray(), "<<": bytearray()}
        self.last = {">>": 0.0, "<<": 0.0}
        self.pcap = None
        self.pcap_pending: list[tuple[int, bytes, int]] = []
        if pcap:
            if _is_fifo(pcap):
                # opening a FIFO for writing blocks until a reader (Wireshark)
                # connects; do that in a thread so the bridge starts right away
                # and buffer frames until then
                threading.Thread(target=self._open_pcap, args=(pcap,), daemon=True).start()
            else:
                self.pcap = pcapng.Writer(open(pcap, "wb"))

    def _open_pcap(self, path: str) -> None:
        try:
            w = pcapng.Writer(open(path, "wb"))
        except OSError as e:
            print(f"-- pcap {path}: {e}; continuing without pcapng", flush=True)
            return
        for ifid, data, ts in self.pcap_pending:
            w.frame(ifid, data, ts)
        self.pcap_pending = []
        self.pcap = w
        print("-- pcap reader connected", flush=True)

    def add(self, tag: str, data: bytes) -> None:
        now = time.monotonic()
        other = "<<" if tag == ">>" else ">>"
        # a turn-around also closes the other direction's frame
        if self.buf[other]:
            self.flush(other)
        self.buf[tag] += data
        self.last[tag] = now

    def tick(self) -> None:
        now = time.monotonic()
        for tag in (">>", "<<"):
            if self.buf[tag] and now - self.last[tag] >= self.idle:
                self.flush(tag)

    def flush(self, tag: str) -> None:
        data = bytes(self.buf[tag])
        self.buf[tag].clear()
        ms = int((self.last[tag] - self.t0) * 1000)
        line = "[%8d ms] %s %s" % (ms, tag, " ".join("%02x" % b for b in data))
        ifid = pcapng.IF_PROGRAM if tag == ">>" else pcapng.IF_DEVICE
        ts = int((self.wall0 + self.last[tag] - self.t0) * 1_000_000)
        if self.pcap:
            try:
                self.pcap.frame(ifid, data, ts)
            except BrokenPipeError:
                self.pcap = None  # Wireshark closed the fifo; keep bridging
        elif self.pcap_pending is not None and len(self.pcap_pending) < 10000:
            self.pcap_pending.append((ifid, data, ts))
        if self.fh:
            self.fh.write(line + "\n")
            self.fh.flush()
        if not self.quiet:
            shown = data if len(data) <= 40 else data[:40]
            tail = "" if len(data) <= 40 else " ...(%d bytes)" % len(data)
            print("[%8d ms] %s %-3d |%s|%s" % (ms, tag, len(data), printable(shown), tail), flush=True)

    def close(self) -> None:
        for tag in (">>", "<<"):
            if self.buf[tag]:
                self.flush(tag)
        if self.fh:
            self.fh.close()
        if self.pcap:
            try:
                self.pcap.close()
            except OSError:
                pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--real", metavar="DEV", help="bridge to this serial adapter")
    mode.add_argument("--virtual", action="store_true", help="bridge to a second pty (null-modem)")
    ap.add_argument("--baud", type=int, default=9600, choices=sorted(BAUDS))
    ap.add_argument("--com", type=int, default=1, help="COM number inside the sandbox (default 1)")
    ap.add_argument("--prefix", default=os.environ.get("WINEPREFIX", os.path.expanduser("~/.hgs_sandbox")))
    ap.add_argument("--no-link", action="store_true", help="don't touch the Wine prefix; just print the pty path")
    ap.add_argument("--peer-file", help="(--virtual) also write the peer pty path to this file")
    ap.add_argument("--log", help="write decode_capture.py-compatible log here")
    ap.add_argument("--pcap", help="write pcapng here (regular file, or a FIFO for live Wireshark)")
    ap.add_argument("--idle", type=float, default=50.0, help="frame split gap in ms (default 50)")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    prog_master, prog_slave, prog_path = new_pty()
    # a fresh pty reports 38400; start it at the requested rate so the baud
    # mirror only reacts to changes the program actually makes
    set_raw_8n1(prog_slave, args.baud)
    if args.virtual:
        far_fd, peer_slave, peer_path = new_pty()
        print(f"virtual null-modem: program side {prog_path}  <->  peer side {peer_path}", flush=True)
        if args.peer_file:
            os.makedirs(os.path.dirname(os.path.abspath(args.peer_file)), exist_ok=True)
            with open(args.peer_file, "w") as fh:
                fh.write(peer_path + "\n")
    else:
        far_fd = open_real(args.real, args.baud)
        peer_slave = None
        print(f"program side {prog_path}  <->  {args.real} @ {args.baud} 8N1", flush=True)

    link = None
    if not args.no_link:
        dosdev = os.path.join(args.prefix, "dosdevices")
        os.makedirs(dosdev, exist_ok=True)
        link = os.path.join(dosdev, f"com{args.com}")
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(prog_path, link)
        print(f"COM{args.com} in {args.prefix} -> {prog_path}", flush=True)

    if args.pcap and not args.quiet:
        print(f"pcapng -> {args.pcap}" + ("  (waiting for a reader)" if _is_fifo(args.pcap) else ""), flush=True)
    log = Logger(args.log, args.idle / 1000.0, args.quiet, args.pcap)
    cur_baud = args.baud
    last_baud_check = 0.0
    try:
        while True:
            r, _, _ = select.select([prog_master, far_fd], [], [], 0.01)
            for fd in r:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    data = b""
                if not data:
                    continue
                if fd == prog_master:
                    os.write(far_fd, data)
                    log.add(">>", data)
                else:
                    os.write(prog_master, data)
                    log.add("<<", data)
            log.tick()
            now = time.monotonic()
            if args.real and now - last_baud_check > 0.5:
                last_baud_check = now
                b = slave_baud(prog_slave)
                if b and b != cur_baud:
                    set_raw_8n1(far_fd, b)
                    cur_baud = b
                    print(f"-- program set {b} baud; adapter follows", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        log.close()
        if link and os.path.islink(link):
            os.remove(link)
        for fd in (prog_master, prog_slave, far_fd, peer_slave):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
