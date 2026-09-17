"""HGS Download Stick — main firmware (CircuitPython, Waveshare 25098 =
ESP32-S3-Touch-LCD-1.28: round GC9A01 LCD + CST816S touch).

Aircraft mode (on battery): READY screen, button starts the DAU download,
file stored to flash, live status on the TFT.
Office mode (USB host): PC sees the flash as a drive; screen shows stored
downloads plus the tail of the fault log.

Diagnostics built in:
  - /SYSLOG.TXT   persistent fault/event log, readable from any PC
  - watchdog      auto-resets a hung download and records it
  - battery gauge low-battery warning before starting a download
  - failed downloads kept as *.PART files for post-mortem, never deleted
"""
import os
import time

import board
import busio
import digitalio
import displayio
import microcontroller
import supervisor
import terminalio
from watchdog import WatchDogMode
from adafruit_display_text import label

import dau_protocol
from stick_log import StickLog
from touch_cst816 import Touch

# --- ESP32-S3-Touch-LCD-1.28 (Waveshare 25098) pin map ----------------------
# The only GPIOs free for our own use are the 6 on the SH1.0 expansion header:
# IO15, IO16, IO17, IO18, IO21, IO33. Everything else drives the LCD, the
# CST816S touch, the QMI8658 IMU, or battery sense.
#
# Serial pins for the MAX3232. NOT UART0 (IO43/IO44), which the ROM bootloader
# spews its 115200 log down at every power-up — that garbage would go straight
# into the DAU. Use two header pins instead.
TX_PIN = board.IO16
RX_PIN = board.IO17

# LCD (GC9A01, SPI) and touch (CST816S, I2C) — fixed by the board.
LCD_SCLK, LCD_MOSI, LCD_CS, LCD_DC, LCD_RST, LCD_BL = (
    board.IO10, board.IO11, board.IO9, board.IO8, board.IO14, board.IO2)
TP_SCL, TP_SDA, TP_RST, TP_INT = board.IO7, board.IO6, board.IO13, board.IO5
BATT_ADC = board.IO1

BAUD = 9600                 # 9600,n,8,1 per the original app
LOW_BATT_PCT = 20
WATCHDOG_S = 30             # any 30 s hang during download -> reset + log
DOWNLOAD_MIN_BYTES = 1000   # completed file smaller than this = suspect

log = StickLog()

# --- round LCD (GC9A01, 240x240) --------------------------------------------
# No board-specific CircuitPython build exists for the 1.28 round board, so we
# bring the panel up by hand on the generic ESP32-S3 build. Needs
# adafruit_gc9a01a from the lib bundle on CIRCUITPY.
import fourwire
import adafruit_gc9a01a

_bl = digitalio.DigitalInOut(LCD_BL)     # backlight on
_bl.switch_to_output(value=True)
_spi = busio.SPI(clock=LCD_SCLK, MOSI=LCD_MOSI)
_bus = fourwire.FourWire(_spi, command=LCD_DC, chip_select=LCD_CS,
                         reset=LCD_RST, baudrate=40_000_000)
display = adafruit_gc9a01a.GC9A01A(_bus, width=240, height=240)
group = displayio.Group()
display.root_group = group

# The panel is a circle: keep text and the bar inside a centred safe band so
# nothing lands in the clipped corners.
lines = []
for i in range(5):
    l = label.Label(terminalio.FONT, text="", x=24, y=48 + i * 30)
    group.append(l)
    lines.append(l)


def show(*msgs):
    for i, l in enumerate(lines):
        l.text = msgs[i] if i < len(msgs) else ""


# --- graphical progress bar (drawn with core displayio, no extra libs) -------
BAR_X, BAR_Y, BAR_W, BAR_H = 40, 100, 160, 14   # centred inside the round panel
_bar_bmp = displayio.Bitmap(BAR_W, BAR_H, 2)
_bar_pal = displayio.Palette(2)
_bar_pal[0] = 0x202830   # empty track
_bar_pal[1] = 0x00C0FF   # filled
_bar_tile = displayio.TileGrid(_bar_bmp, pixel_shader=_bar_pal, x=BAR_X, y=BAR_Y)
_bar_tile.hidden = True
group.append(_bar_tile)
_bar_last = -1


def set_bar(pct, visible=True):
    global _bar_last
    _bar_tile.hidden = not visible
    if not visible:
        return
    pct = 0 if pct < 0 else (100 if pct > 100 else pct)
    fillw = BAR_W * pct // 100
    if fillw == _bar_last:
        return                      # only redraw when the fill actually changes
    lo, hi = sorted((_bar_last if _bar_last >= 0 else 0, fillw))
    for x in range(lo, hi):         # touch only the columns that changed
        c = 1 if x < fillw else 0
        for y in range(BAR_H):
            _bar_bmp[x, y] = c
    _bar_last = fillw


# --- duration calibration (self-learning, for the % bar and ETA) -------------
# A download is hundreds of tiny records first, then the big time-history
# frames, so BYTES map non-linearly to time. Elapsed time vs. the last
# download's duration gives a smooth, honest countdown (same aircraft ~ same
# duration each time). We store seconds; bytes shown on screen are exact.
CAL_FILE = "/calibration.txt"
DEFAULT_SECONDS = 840     # ~14 min, a typical full DOWNLOAD LOGS until learned


def load_cal():
    try:
        with open(CAL_FILE) as fh:
            return max(30, int(fh.read().strip()))
    except Exception:
        return DEFAULT_SECONDS


def save_cal(seconds):
    try:
        with open(CAL_FILE, "w") as fh:
            fh.write(str(int(seconds)))
    except Exception:
        pass


# --- battery gauge (ADC divider on IO1; no fuel-gauge IC on this board) ------
# The 1.28 board brings the LiPo to IO1 through a resistor divider instead of a
# MAX17048. BATT_DIVIDER is the ratio (Vbat / Vadc); Waveshare's board divides
# by ~3. VERIFY against the schematic / a multimeter and tune if the % looks
# off. An implausible voltage (< 2.5 V) reads as "unknown" (None) so a missing
# battery / USB-only power can't falsely trip low-battery.
import analogio

BATT_DIVIDER = 3.0
_adc = None


def _batt_volts():
    global _adc
    try:
        if _adc is None:
            _adc = analogio.AnalogIn(BATT_ADC)
        v = (_adc.value / 65535) * _adc.reference_voltage * BATT_DIVIDER
        return v
    except Exception:
        _adc = None
        return None


def battery_pct():
    v = _batt_volts()
    if v is None or v < 2.5:
        return None
    # Coarse LiPo curve: 4.2 V ~ 100 %, 3.3 V ~ 0 %.
    pct = int((v - 3.3) / (4.2 - 3.3) * 100)
    return 0 if pct < 0 else (100 if pct > 100 else pct)


def free_kb():
    st = os.statvfs("/")
    return st[0] * st[3] // 1024


def list_downloads():
    return sorted(f for f in os.listdir("/") if f.upper().endswith(".HG6"))


def next_filename(part=False):
    n = len([f for f in os.listdir("/") if f.upper().startswith("DOWNLOAD_")]) + 1
    return "/DOWNLOAD_%02d.HG6%s" % (n, ".PART" if part else "")


def hgs_basename(part_path):
    """Build HGS's own filename (SSSSS_YYMMDD) from the downloaded data.
    The aircraft S/N and date live in the Cumulative Log block (BCD). Returns
    None (caller falls back to DOWNLOAD_NN) if it can't be parsed."""
    try:
        with open(part_path, "rb") as fh:
            head = fh.read(65536)          # the cumulative block is near the front
        i = head.find(b"CUMULATIVE LOG")
        if i < 0:
            return None
        p = i + 25
        def bcd(b):
            return (b >> 4) * 10 + (b & 0x0F)
        yy, mm, dd = bcd(head[p]), bcd(head[p + 1]), bcd(head[p + 2])
        sn = head[p + 11:p + 16].decode("latin-1").strip()
        if not sn or not (1 <= mm <= 12 and 1 <= dd <= 31):
            return None
        return "%s_%02d%02d%02d" % (sn, yy, mm, dd)
    except Exception:
        return None


def final_name(part_path):
    """Pick the saved filename: HGS-style SSSSS_YYMMDD_An.HG6 when the S/N and
    date can be read, else the plain DOWNLOAD_NN.HG6. Avoids collisions."""
    base = hgs_basename(part_path)
    if not base:
        return part_path[:-5]              # strip ".PART" -> DOWNLOAD_NN.HG6
    n = 1
    while True:
        cand = "/%s_A%d.HG6" % (base, n)
        try:
            os.stat(cand)
            n += 1                          # exists (same aircraft, same day) -> bump
        except OSError:
            return cand


# --- office mode --------------------------------------------------------------
def office_mode():
    files = list_downloads()
    parts = [f for f in os.listdir("/") if f.upper().endswith(".PART")]
    l3 = "%d download(s)" % len(files)
    if parts:
        l3 += ", %d FAILED (.PART)" % len(parts)
    tail = log.tail(2)
    show("HGS STICK - USB drive", l3,
         files[-1] if files else "no downloads yet",
         tail[-1][:40] if tail else "", "SYSLOG.TXT has details")
    while True:
        time.sleep(60)


# --- aircraft mode -------------------------------------------------------------
def run_download(uart, touch):
    batt = battery_pct()
    log.line("download requested batt=%s%% free=%dKB"
             % (batt if batt is not None else "?", free_kb()))

    if batt is not None and batt < LOW_BATT_PCT:
        show("LOW BATTERY  %d%%" % batt, "Charge before use", "",
             "TAP = override  (wait = cancel)")
        log.line("blocked: low battery %d%%" % batt)
        if not touch.wait_touch(timeout=10):    # tap to override, or time out
            log.line("low-battery: cancelled (no override)")
            return                              # back to the ready screen
        touch.wait_release()                    # let go before continuing

    if free_kb() < 1024:
        show("FLASH FULL", "%d KB free" % free_kb(),
             "Offload & delete old", "downloads on a PC")
        log.line("blocked: flash full (%d KB free)" % free_kb())
        time.sleep(8)
        return

    name = next_filename(part=True)
    final = name[:-5]
    wd = microcontroller.watchdog
    wd.timeout = WATCHDOG_S
    wd.mode = WatchDogMode.RESET
    log.line("download start -> %s" % final)

    est_secs = load_cal()           # expected duration, for the % bar and ETA
    t0 = time.monotonic()
    phase = ["REQUEST FRAME MSG SENT"]

    def status(msg):
        wd.feed()
        phase[0] = msg              # keep the familiar phase text

    def progress(records, total_bytes):
        wd.feed()
        el = time.monotonic() - t0
        rate = total_bytes / el if el > 0 else 0.0          # bytes/sec (exact)
        pct = min(99, int(el * 100 / est_secs)) if est_secs else 0
        eta = max(0, int(est_secs - el))                    # smooth countdown
        set_bar(pct, visible=True)
        show("DOWNLOADING        %d:%02d" % (int(el) // 60, int(el) % 60),
             "%s" % phase[0],                               # familiar phase text
             "",                                            # (bar occupies here)
             "%d%%   %d KB   %.1f KB/s" % (pct, total_bytes // 1024, rate / 1024),
             "ETA ~%d:%02d  hold: abort" % (eta // 60, eta % 60))

    set_bar(0, visible=True)
    show("DOWNLOADING", "REQUEST FRAME MSG SENT", "", "", "")

    abort = touch.hold_checker(hold_s=1.5)   # press-and-hold the screen = abort

    total = None
    try:
        with open(name, "wb") as fh:
            dl = dau_protocol.DauDownloader(
                uart, lambda: time.monotonic_ns() // 1_000_000,
                on_status=status, on_progress=progress,
                abort_check=abort)              # screen held ~1.5 s = abort
            total = dl.download(fh, command=dau_protocol.CMD_DOWNLOAD_LOGS)
    except OSError as exc:
        set_bar(0, visible=False)
        log.exception(exc, "storage during download")
        show("STORAGE ERROR", str(exc)[:40], "", "", "See SYSLOG.TXT on PC")
        time.sleep(8)
        return
    except Exception as exc:
        set_bar(0, visible=False)
        log.exception(exc, "download")
        show("FIRMWARE FAULT", repr(exc)[:40], "kept: " + name.strip("/"),
             "", "See SYSLOG.TXT on PC")
        time.sleep(8)
        return
    finally:
        wd.mode = None  # disarm outside the download

    if total and total >= DOWNLOAD_MIN_BYTES:
        set_bar(100, visible=True)          # snap to full on success
        el = int(time.monotonic() - t0)
        save_cal(el)                        # learn this aircraft's duration for next time
        final = final_name(name)            # SSSSS_YYMMDD_An.HG6 from the data
        os.rename(name, final)
        log.line("download OK %d bytes in %ds -> %s" % (total, el, final))
        show("COMPLETED WITH SUCCESS",
             "%d KB in %d:%02d" % (total // 1024, el // 60, el % 60),
             final.strip("/"), "", "Tap screen for another")
    elif total:
        set_bar(0, visible=False)
        log.line("download SHORT (%d bytes) kept %s" % (total, name))
        show("SUSPECT DOWNLOAD", "only %d bytes" % total,
             "kept: " + name.strip("/"), "", "Retry; see SYSLOG.TXT")
    else:
        set_bar(0, visible=False)
        log.line("download FAILED, partial kept as %s" % name)
        show("DOWNLOAD FAILED", "Check cable / DAU power",
             "partial kept: " + name.strip("/"), "", "Tap screen to retry")


def aircraft_mode():
    # short read timeout so the protocol's idle-gap framing stays responsive.
    # TX_PIN/RX_PIN are header GPIOs (IO16/IO17), NOT UART0 — see the pin map.
    uart = busio.UART(TX_PIN, RX_PIN, baudrate=BAUD,
                      bits=8, parity=None, stop=1, timeout=0.02,
                      receiver_buffer_size=4096)
    touch = Touch(scl=TP_SCL, sda=TP_SDA, rst=TP_RST, irq=TP_INT)
    log.line("aircraft mode ready, touch id=%s" % touch.chip_id())

    while True:
        set_bar(0, visible=False)      # bar only shows during a download
        batt = battery_pct()
        show("HGS DOWNLOAD STICK",
             "batt %s%%  free %d KB" % (batt if batt is not None else "?",
                                        free_kb()),
             "Connect DB9 to aircraft", "", "Tap screen to download")
        touch.wait_touch()
        touch.wait_release()           # release before starting so the start
        run_download(uart, touch)      # tap isn't seen as an abort-hold
        touch.wait_touch()             # keep the result on screen until tapped
        touch.wait_release()


try:
    if supervisor.runtime.usb_connected:
        office_mode()
    else:
        aircraft_mode()
except Exception as exc:  # last-resort catcher: log, show, halt visibly
    log.exception(exc, "top level")
    show("FIRMWARE FAULT", repr(exc)[:40], "", "", "See SYSLOG.TXT on PC")
    while True:
        time.sleep(60)
