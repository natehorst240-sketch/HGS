"""Persistent diagnostic log for the HGS Download Stick.

Appends one-line entries to /SYSLOG.TXT on the flash, so the log is visible
from any PC alongside the downloads. Timestamps are seconds-since-boot
(the stick has no clock until it reads the DAU's); each boot writes a
header line so sessions are easy to tell apart.

Writes are best-effort: in office mode (USB attached) the filesystem is
read-only to code, so logging silently no-ops rather than crashing the tool.
"""
import time

import microcontroller

LOG_PATH = "/SYSLOG.TXT"
MAX_BYTES = 200_000  # rotate to SYSLOG.OLD.TXT beyond this


def _boot_count_bump() -> int:
    """Persistent boot counter in NVM byte 0/1 (survives power loss)."""
    nvm = microcontroller.nvm
    n = (nvm[0] << 8) | nvm[1]
    n = (n + 1) & 0xFFFF
    nvm[0], nvm[1] = n >> 8, n & 0xFF
    return n


def _rotate():
    import os
    try:
        if os.stat(LOG_PATH)[6] > MAX_BYTES:
            try:
                os.remove("/SYSLOG.OLD.TXT")
            except OSError:
                pass
            os.rename(LOG_PATH, "/SYSLOG.OLD.TXT")
    except OSError:
        pass


class StickLog:
    def __init__(self):
        self.writable = True
        self.boot_no = 0
        try:
            self.boot_no = _boot_count_bump()
        except Exception:
            pass
        try:
            _rotate()
            reason = str(microcontroller.cpu.reset_reason).split(".")[-1]
            self.line("BOOT #%d reset_reason=%s" % (self.boot_no, reason))
            if reason == "WATCHDOG":
                self.line("WARNING: previous session hung and was "
                          "auto-reset by the watchdog")
        except OSError:
            self.writable = False  # office mode: read-only filesystem

    def line(self, msg: str):
        if not self.writable:
            return
        try:
            with open(LOG_PATH, "a") as fh:
                fh.write("[%9.1fs] %s\n" % (time.monotonic(), msg))
        except OSError:
            self.writable = False

    def exception(self, exc, context):
        # The one-line summary is the important part; the traceback dump is a
        # bonus and its API varies across CircuitPython, so never let it throw.
        self.line("FAULT in %s: %r" % (context, exc))
        try:
            import traceback
            with open(LOG_PATH, "a") as fh:
                traceback.print_exception(exc, file=fh)
        except Exception:
            pass

    def tail(self, n: int = 6) -> list:
        """Last n log lines, for showing on the TFT in office mode."""
        try:
            with open(LOG_PATH) as fh:
                return [l.rstrip() for l in fh][-n:]
        except OSError:
            return []
