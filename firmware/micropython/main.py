"""HGS Download Stick — main firmware (MicroPython, ESP32-S3-Touch-LCD-1.28).

Standalone, battery-powered: shows an HGS-styled screen on the round LCD, waits
for a screen tap, runs the DAU download over RS-232 (via MAX3232 on IO16/IO17),
and stores the .HG6 to onboard flash. Retrieve files afterward over serial:

    python -m mpremote connect COM7 fs ls          # list stored downloads
    python -m mpremote connect COM7 fs cp :SSSSS_YYMMDD_A1.HG6 .

UI mirrors the Windows HGS app: navy title bar, a sunken "Hgs Status" panel
(COM_1: STAND BY READY), and the app's own phase strings during a download.
Hold the screen ~1.5 s to ABORT.
"""
import os
import io
import time
from machine import Pin, UART, ADC, deepsleep
import esp32

import gc9a01 as g
from gc9a01 import GC9A01
from cst816 import CST816
import dau_protocol as dp

# --- board pins (25098) ------------------------------------------------------
TX_PIN = 16          # -> MAX3232 TTL in  -> DB9 pin3 (DAU RXD)
RX_PIN = 17          # <- MAX3232 TTL out <- DB9 pin2 (DAU TXD)
BATT_ADC_PIN = 1
BATT_DIVIDER = 3.0   # Vbat = Vadc * 3 (Waveshare demo)

BAUD = 9600
LOW_BATT_PCT = 20
DOWNLOAD_MIN_BYTES = 1000
LOGFILE = "/syslog.txt"

TP_INT_PIN = 5           # CST816S INT — wakes the board from deep sleep
IDLE_SLEEP_MS = 120000   # sleep after this long idle on the ready screen.
                         # Set 0 to disable (e.g. while developing over USB).

# --- HGS-look palette (RGB565) ----------------------------------------------
BG = 0xC618          # Win9x face gray
NAVY = 0x0010        # title bar
WHITE = 0xFFFF
BLACK = 0x0000
GREEN = 0x07E0
RED = 0xF800
AMBER = 0xFD20
SHADOW = 0x8410      # sunken-panel border

lcd = GC9A01()
tp = CST816()

# HGS wordmark logo (48x48 RGB565, composited over the gray face). Falls back
# to text if the asset isn't present on the board.
LOGO_W = LOGO_H = 48
try:
    with open("hgs_logo.bin", "rb") as _f:
        _LOGO = _f.read()
    if len(_LOGO) != LOGO_W * LOGO_H * 2:
        _LOGO = None
except Exception:
    _LOGO = None


# --- tiny persistent log -----------------------------------------------------
def logline(msg):
    try:
        with open(LOGFILE, "a") as fh:
            fh.write("%d %s\n" % (time.ticks_ms(), msg))
    except Exception:
        pass


# --- UI ----------------------------------------------------------------------
def _center_x(s, scale):
    return max(0, (g.WIDTH - len(s) * 8 * scale) // 2)


def title_bar():
    if _LOGO:
        lcd.blit565((g.WIDTH - LOGO_W) // 2, 14, LOGO_W, LOGO_H, _LOGO)
    else:
        lcd.fill_rect(0, 28, g.WIDTH, 26, NAVY)
        lcd.text("A109S  HGS", _center_x("A109S  HGS", 2), 32, WHITE, NAVY, 2)


def panel(lines, y=92, box_h=96, fg=BLACK):
    """Draw the sunken 'Hgs Status' panel with up to 4 short lines."""
    lcd.fill_rect(18, y - 18, 204, 16, BG)
    lcd.text("Hgs Status:", 22, y - 18, BLACK, BG, 1)
    lcd.fill_rect(16, y, 208, box_h, WHITE)             # white sunken field
    lcd.fill_rect(16, y, 208, 2, SHADOW)                # top/left shadow
    lcd.fill_rect(16, y, 2, box_h, SHADOW)
    for i, ln in enumerate(lines[:4]):
        lcd.text(ln, 24, y + 8 + i * 20, fg, WHITE, 1)


def screen(status_lines, hint=None, hint_col=BLACK, fg=BLACK):
    lcd.fill(BG)
    title_bar()
    panel(status_lines, fg=fg)
    if hint:
        lcd.text(hint, _center_x(hint, 1), 200, hint_col, BG, 1)


# --- progress bar ------------------------------------------------------------
BAR_X, BAR_Y, BAR_W, BAR_H = 30, 176, 180, 14
_bar_last = -1


def bar(pct, show=True):
    global _bar_last
    if not show:
        _bar_last = -1
        return
    pct = 0 if pct < 0 else (100 if pct > 100 else pct)
    fillw = BAR_W * pct // 100
    if fillw == _bar_last:
        return
    lcd.fill_rect(BAR_X, BAR_Y, BAR_W, BAR_H, 0x2104)          # track
    if fillw:
        lcd.fill_rect(BAR_X, BAR_Y, fillw, BAR_H, g.CYAN)      # fill
    _bar_last = fillw


# --- battery / storage -------------------------------------------------------
_adc = None


def battery_pct():
    global _adc
    try:
        if _adc is None:
            _adc = ADC(Pin(BATT_ADC_PIN))
            _adc.atten(ADC.ATTN_11DB)
        v = _adc.read_uv() / 1_000_000 * BATT_DIVIDER
        if v < 2.5:
            return None
        pct = int((v - 3.3) / (4.2 - 3.3) * 100)
        return 0 if pct < 0 else (100 if pct > 100 else pct)
    except Exception:
        return None


def free_kb():
    st = os.statvfs("/")
    return st[0] * st[3] // 1024


def list_downloads():
    return sorted(f for f in os.listdir("/") if f.upper().endswith(".HG6"))


def next_part():
    n = len([f for f in os.listdir("/") if f.startswith("DOWNLOAD_")]) + 1
    return "/DOWNLOAD_%02d.HG6.PART" % n


def hgs_basename(part_path):
    """SSSSS_YYMMDD from the Cumulative Log block (BCD), else None."""
    try:
        with open(part_path, "rb") as fh:
            head = fh.read(65536)
        i = head.find(b"CUMULATIVE LOG")
        if i < 0:
            return None
        p = i + 25
        def bcd(b):
            return (b >> 4) * 10 + (b & 0x0F)
        yy, mm, dd = bcd(head[p]), bcd(head[p + 1]), bcd(head[p + 2])
        sn = head[p + 11:p + 16].decode().strip()
        if not sn or not (1 <= mm <= 12 and 1 <= dd <= 31):
            return None
        return "%s_%02d%02d%02d" % (sn, yy, mm, dd)
    except Exception:
        return None


def final_name(part_path):
    base = hgs_basename(part_path)
    if not base:
        return part_path[:-5]            # strip ".PART"
    n = 1
    while True:
        cand = "/%s_A%d.HG6" % (base, n)
        try:
            os.stat(cand)
            n += 1
        except OSError:
            return cand


# --- data sanity: reject line noise from a floating/disconnected RX ----------
# Real HGS records begin with 25-byte ASCII labels and the stream contains
# known log keywords; random UART noise is ~37% printable and has no markers.
_HGS_MARKERS = (b"CUMULATIVE", b"FAULT", b"PARAMETER", b"POWER", b"TIME",
                b"AFCS", b"ASSURANCE", b"LOG")


def valid_first_record(rec):
    if len(rec) < 20:
        return False
    if any(m in rec for m in _HGS_MARKERS):
        return True
    head = rec[:48]
    printable = sum(1 for b in head if 0x20 <= b <= 0x7E)
    return printable >= len(head) // 2        # >=50% printable ASCII


# --- download flow -----------------------------------------------------------
def run_download(uart):
    batt = battery_pct()
    logline("download requested batt=%s free=%dKB"
            % (batt if batt is not None else "?", free_kb()))

    if batt is not None and batt < LOW_BATT_PCT:
        screen(["LOW BATTERY  %d%%" % batt, "Charge before use", "",
                "TAP=override wait=cancel"], fg=RED)
        if not tp.wait_touch(timeout_ms=10000):
            return
        tp.wait_release()

    if free_kb() < 1024:
        screen(["FLASH FULL", "%d KB free" % free_kb(),
                "Offload on a PC first"], fg=RED)
        time.sleep_ms(6000)
        return

    part = next_part()
    logline("download start -> %s" % part)
    t0 = time.ticks_ms()
    phase = ["REQUEST FRAME MSG SENT"]
    abort = tp.hold_checker(hold_ms=1500)

    def status(msg):
        phase[0] = msg

    def progress(records, total):
        el = time.ticks_diff(time.ticks_ms(), t0) // 1000
        pct = min(99, total * 100 // 600000)       # ~0.6 MB typical full download
        panel(["COM_1: DOWNLOADING",           # redraw panel only (no flicker)
               phase[0][:20],
               "%d KB   frame %d" % (total // 1024, records),
               "%d:%02d elapsed" % (el // 60, el % 60)])
        bar(pct)

    screen(["COM_1: DOWNLOADING", "REQUEST FRAME MSG SENT"],
           hint="hold screen = ABORT", hint_col=RED)

    total = None
    try:
        with open(part, "wb") as fh:
            dl = dp.DauDownloader(uart, on_status=status, on_progress=progress,
                                  abort_check=abort,
                                  first_record_ok=valid_first_record)
            total = dl.download(fh, command=dp.CMD_DOWNLOAD_LOGS)
    except Exception as exc:
        logline("download FAULT %r" % exc)
        screen(["DOWNLOAD FAULT", repr(exc)[:20], "kept: " + part.split("/")[-1][:18],
                "see syslog.txt"], fg=RED)
        time.sleep_ms(6000)
        return

    if total and total >= DOWNLOAD_MIN_BYTES:
        bar(100)
        el = time.ticks_diff(time.ticks_ms(), t0) // 1000
        final = final_name(part)
        os.rename(part, final)
        name = final.split("/")[-1]
        logline("download OK %d bytes in %ds -> %s" % (total, el, final))
        screen(["COMPLETED WITH SUCCESS",
                "%d KB in %d:%02d" % (total // 1024, el // 60, el % 60),
                name[:20], "Tap for another"], fg=GREEN)
    elif total:
        logline("download SHORT %d bytes kept %s" % (total, part))
        screen(["SUSPECT DOWNLOAD", "only %d bytes" % total,
                "kept: " + part.split("/")[-1][:16], "Retry"], fg=AMBER)
    else:
        # total == 0 (no valid data / no response): the .PART is empty, so
        # remove it rather than littering flash with 0-byte files.
        empty = False
        try:
            empty = os.stat(part)[6] == 0
        except OSError:
            empty = True
        if empty:
            try:
                os.remove(part)
            except OSError:
                pass
        noise = "noise" in phase[0]
        logline("download FAILED (%s), %s"
                % (phase[0], "removed empty part" if empty else "kept " + part))
        screen(["NO DATA RECEIVED" if noise else "DOWNLOAD FAILED",
                "Line noise - reseat" if noise else "Check cable / DAU pwr",
                "connector & retry" if noise else "",
                "Tap to retry"], fg=RED)


# --- deep sleep (wake on touch) ----------------------------------------------
def enter_sleep():
    """Blank the panel and deep-sleep until the screen is touched. Wake is a
    cold boot, so main() re-runs and comes back to the ready screen."""
    logline("idle -> deep sleep")
    try:
        lcd._cmd(0x28)              # display off
        lcd._cmd(0x10)              # sleep in (panel low power)
        lcd.bl.value(0)            # backlight off — the big battery saver
    except Exception:
        pass
    # Wake when the CST816S INT line goes low (a touch). ext1 is the ESP32-S3
    # deep-sleep pin-wake source (ext0 doesn't exist on the S3).
    esp32.wake_on_ext1(pins=(Pin(TP_INT_PIN),), level=esp32.WAKEUP_ALL_LOW)
    deepsleep()                    # never returns; wakes via reset


def wait_touch_or_sleep():
    """Wait for a tap; if idle past IDLE_SLEEP_MS, deep-sleep until touched."""
    if IDLE_SLEEP_MS:
        if not tp.wait_touch(timeout_ms=IDLE_SLEEP_MS):
            enter_sleep()          # timed out -> sleep; does not return
        # else: touched within the window -> fall through
    else:
        tp.wait_touch()            # sleep disabled: wait indefinitely
    tp.wait_release()


# --- main --------------------------------------------------------------------
def main():
    # Idle pull-up on RX: a disconnected/unpowered line then reads as clean
    # UART idle (high) instead of floating noise. Best-effort — the MAX3232
    # drives RX when present, and valid_first_record() is the real backstop.
    try:
        Pin(RX_PIN, Pin.IN, Pin.PULL_UP)
    except Exception:
        pass
    uart = UART(1, baudrate=BAUD, bits=8, parity=None, stop=1,
                tx=TX_PIN, rx=RX_PIN, timeout=20, rxbuf=4096)
    cid = tp.chip_id()
    logline("ready, touch id=%s free=%dKB n_dl=%d"
            % (hex(cid) if cid is not None else None, free_kb(),
               len(list_downloads())))

    while True:
        bar(0, show=False)
        batt = battery_pct()
        screen(["COM_1: STAND BY READY",
                "COM_2: - NOT AVAILABLE -",
                "batt %s%%  free %dKB" % (batt if batt is not None else "?",
                                          free_kb()),
                "%d download(s) stored" % len(list_downloads())],
               hint="Tap screen to download")
        wait_touch_or_sleep()          # idle here long enough -> deep sleep
        run_download(uart)
        wait_touch_or_sleep()          # hold the result until acknowledged



try:
    main()
except Exception as exc:
    logline("TOP-LEVEL FAULT %r" % exc)
    try:
        screen(["FIRMWARE FAULT", repr(exc)[:20], "see syslog.txt on PC"], fg=RED)
    except Exception:
        pass
    raise
