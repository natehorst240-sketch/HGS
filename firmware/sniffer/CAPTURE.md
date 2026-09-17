# Passive protocol capture with the ESP32 board

Goal: record the HGS <-> DAU serial conversation using the same hardware you're
buying for the download stick, as a **listen-only tap**. Nothing is installed
on either laptop, nothing is transferred to the locked work laptop, and the
board can't talk on the bus. Later the same board is reflashed as the stick.

## Why this route
- The personal desktop (this Lenovo) can run Wireshark but can't go to the
  aircraft. The work laptop reaches the aircraft but is locked down.
- A hardware tap sidesteps both: it sits on the cable, the work laptop does a
  normal download, and the capture ends up on the board's flash — which you
  read on the desktop like a thumb drive.

## What you need
- Adafruit ESP32-S2 TFT Feather (already planned)
- Adafruit RS-232 Full Pinout Level-Shifter Breakout (already planned)
- A way to reach both data lines of the maintenance cable while HGS runs. Best
  is a **DB9 male-female passthrough / breakout** (a "DB9 T" or a breakout with
  screw terminals) so you can tap TXD, RXD, and GND without cutting anything.

## How a passive tap works
RS-232 has two data wires: one the PC drives (PC-TXD) and one the DAU drives
(DAU-TXD), plus signal ground. We feed **both** into the level-shifter's two
receiver inputs and read the two logic outputs with the ESP32's two UARTs.
We connect **only receivers**, never the drivers, so the board physically
cannot transmit.

```
maintenance cable (with a DB9 passthrough so HGS still works):

  PC-TXD  (DAU pin B / RXD-into-DAU) --> breakout R2IN --> R2OUT --> ESP32 D5
  DAU-TXD (DAU pin A / TXD-from-DAU) --> breakout R1IN --> R1OUT --> ESP32 RX
  SIGNAL GND (DAU pin G)             --> breakout GND  and ESP32 GND
  breakout VCC --> ESP32 3V

  (breakout T1/T2 driver pins: leave unconnected — listen only)
```

Exact DB9 pin numbers depend on the cable's internal wiring; from the A109
diagram the DAU side is TXD=J101-A, RXD=J101-B, GND=J101-G. Buzz the cable to
map those to DB9 pins (there's a table in ../HARDWARE.md). If you tap the two
data lines and get them swapped, it doesn't matter — the analyzer figures out
direction from content.

## Procedure
1. Flash CircuitPython to the Feather, copy this folder's `boot.py` and
   `code.py` to the CIRCUITPY drive (plus the `adafruit_display_text` library).
2. Unplug USB, power the board from its LiPo. The TFT shows
   "RS-232 SNIFFER ACTIVE" and starts a fresh `CAPTURE_nn.LOG`.
3. Put the DB9 passthrough inline on the maintenance cable and connect the
   three taps (DAU-TXD, PC-TXD, GND) as above.
4. On the work laptop, do a **normal, complete download** in HGS. The board's
   screen shows byte counts climbing on A and B.
5. When the download finishes, power the board off.
6. Bring the board to the desktop, plug in USB — it mounts as a drive with
   `CAPTURE_01.LOG`. Copy it off.

## Then
Run the analyzer (already on the desktop):
```
python hgs-linux/reverse/frida/decode_capture.py CAPTURE_01.LOG
```
It reports the framing and detects the checksum. Send me that report + the
raw `.LOG` and I'll finish `firmware/dau_protocol.py` so the same board can be
reflashed as the download stick.

## Safety / non-interference
- Only the receiver inputs are wired, so the board cannot drive the bus.
- The tap is high-impedance listening in parallel; HGS and the DAU behave
  exactly as in a normal download.
- If you're at all unsure about touching the aircraft harness, use a DB9
  passthrough adapter (no cutting/soldering into the aircraft cable) and tap
  at the adapter.
