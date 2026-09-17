"""Passive RS-232 protocol sniffer (CircuitPython, ESP32-S2 TFT Feather).

Records the HGS <-> DAU serial conversation to flash by listening to BOTH
data lines at once, without transmitting anything. The work laptop does a
normal download; this board just watches and logs. Nothing is installed on
either computer and no files need to move to the locked laptop.

Wiring (through the RS-232 level-shifter breakout, listen-only):
  DAU/aircraft TXD line  -> breakout R1IN -> R1OUT -> ESP32 RX pin A (board.RX)
  PC/laptop    TXD line  -> breakout R2IN -> R2OUT -> ESP32 RX pin B (board.D5)
  signal ground shared to breakout GND and ESP32 GND
We only use the breakout's two RECEIVERS (RS-232 -> logic); the drivers are
left unconnected so the board can never talk on the bus.

Output: /CAPTURE_nn.LOG on the CIRCUITPY flash, in the exact format
decode_capture.py expects:
    [   123 ms] A  02 00 0c 03
    [   140 ms] B  26 07 05 14 05 39 ...
Line "A" = board.RX line, "B" = board.D5 line. Which physical wire is the PC
vs the DAU doesn't matter for decoding — the analyzer (and the byte content:
short request frames vs long data frames) sorts direction out.

To read the capture: plug the board into any PC by USB; it appears as a drive
with the .LOG file on it. (boot.py keeps the flash writable only off-USB, so
plugging in never corrupts an in-progress capture.)
"""
import time

import board
import busio
import digitalio

BAUD = 9600                 # 9600,n,8,1 per the HGS config
IDLE_FLUSH_S = 0.05         # group bytes that arrive within 50 ms
STATUS = None

# Optional TFT status (present on this Feather); degrade gracefully if not.
try:
    import displayio
    import terminalio
    from adafruit_display_text import label
    _d = board.DISPLAY
    _g = displayio.Group()
    _d.root_group = _g
    _rows = []
    for i in range(4):
        lb = label.Label(terminalio.FONT, text="", x=4, y=12 + i * 22)
        _g.append(lb)
        _rows.append(lb)

    def STATUS(*msgs):
        for i, lb in enumerate(_rows):
            lb.text = msgs[i] if i < len(msgs) else ""
except Exception:
    def STATUS(*msgs):
        pass


def next_logname():
    import os
    n = len([f for f in os.listdir("/") if f.upper().startswith("CAPTURE_")]) + 1
    return "/CAPTURE_%02d.LOG" % n


def main():
    # Two receive-only UARTs. tx=None keeps the pins from ever driving the bus.
    a = busio.UART(None, board.RX, baudrate=BAUD, timeout=0.001, receiver_buffer_size=2048)
    b = busio.UART(None, board.D5, baudrate=BAUD, timeout=0.001, receiver_buffer_size=2048)

    try:
        path = next_logname()
        fh = open(path, "w")
    except OSError:
        # USB attached => read-only filesystem. Show existing captures instead.
        import os
        caps = [f for f in os.listdir("/") if f.upper().startswith("CAPTURE_")]
        STATUS("SNIFFER (USB mode)", "%d capture(s) on drive" % len(caps),
               caps[-1] if caps else "none yet", "Copy .LOG off to analyze")
        while True:
            time.sleep(60)

    t0 = time.monotonic()
    total_a = total_b = 0
    STATUS("RS-232 SNIFFER ACTIVE", path.strip("/"), "listening 9600 8N1",
           "do a normal download")

    pend = {"A": bytearray(), "B": bytearray()}
    last = {"A": 0.0, "B": 0.0}

    def stamp(line, buf):
        ms = int((time.monotonic() - t0) * 1000)
        fh.write("[%8d ms] %s  %s\n"
                 % (ms, line, " ".join("%02x" % x for x in buf)))

    def pump(uart, line):
        nonlocal total_a, total_b
        data = uart.read(256)
        now = time.monotonic()
        if data:
            pend[line] += data
            last[line] = now
            if line == "A":
                total_a += len(data)
            else:
                total_b += len(data)
        # flush a line's buffer once it's been idle briefly (frame boundary)
        elif pend[line] and (now - last[line]) > IDLE_FLUSH_S:
            stamp(line, pend[line])
            pend[line] = bytearray()

    ticks = 0
    while True:
        pump(a, "A")
        pump(b, "B")
        ticks += 1
        if ticks % 200 == 0:
            fh.flush()
            STATUS("SNIFFER ACTIVE", path.strip("/"),
                   "A:%d B:%d bytes" % (total_a, total_b),
                   "leave running til done")


main()
