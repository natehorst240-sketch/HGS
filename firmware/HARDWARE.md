# HGS Download Stick — hardware design

Target hardware (selected 2026-07-31):
- **Waveshare 25098 = ESP32-S3-Touch-LCD-1.28** — ESP32-S3R2, 16 MB flash /
  2 MB PSRAM, round 1.28" **GC9A01** 240×240 IPS LCD, **CST816S** capacitive
  touch, QMI8658 IMU (unused), native USB-C, onboard MX1.25 LiPo charger +
  battery-voltage ADC.
- **MAX3232 RS-232 ↔ TTL module with DB9** (e.g. ANMBEST) — does the
  ±12 V ↔ 3.3 V level shift and carries the DB9.

Goal: a pocket-size, battery-powered dongle with a DB9 RS-232 port on one end
and USB-C on the other. Maintenance plugs it into the aircraft's IDS/DAU
serial connector, **taps the screen**, it performs the download entirely
on-board and stores the `.HG6` file. Plugged into any PC afterward, it
enumerates as an ordinary USB flash drive — no drivers, no software, nothing
to get past IT.

## Concept of operations

1. Field: connect DB9 to the aircraft (same connector the HGS laptop cable
   used), **tap the touchscreen**. The round LCD shows live status —
   "DOWNLOADING", phase text, a progress bar + ETA, then "COMPLETED WITH
   SUCCESS 22366_260707_A1.HG6" — mirroring the original app's status strings.
   **Press and hold the screen (~1.5 s) to abort.** Power comes from the LiPo.
2. Office: plug USB-C into any computer. It mounts as a flash drive containing
   `SSSSS_YYMMDD_A1.HG6`-style files (same naming as the original app). View
   with hgs-linux or copy the files anywhere.

Download-only by design: the stick never writes to the aircraft beyond the
protocol's own request/ACK bytes.

## Why this pairing works

- ESP32-S3 has **native USB** — CircuitPython exposes the flash as USB mass
  storage (the CIRCUITPY drive) with zero extra hardware. The same board *is*
  the thumb drive. 16 MB flash vs a ~0.6 MB download → many downloads fit.
- The **round touch LCD replaces both the laptop screen and the button** — the
  status strings the original app shows go on the display; a tap starts the
  download, a hold aborts it. No mechanical switch to fail in an enclosure.
- The MAX3232 module does the ±12 V ↔ 3.3 V conversion (never wire the DB9
  straight to the S3 — RS-232 line levels destroy 3.3 V GPIO).
- Onboard LiPo charger + battery ADC (IO1, ÷3 divider) → runs on battery in
  the field, recharges + offloads over the same USB-C port.

## Board pin map (verified against the official demo `DEV_Config.h`)

Fixed by the board — do not reuse these for the serial port:

| Function | GPIO |
|----------|------|
| LCD (GC9A01): DC / CS / CLK / MOSI / MISO / RST / BL | 8 / 9 / 10 / 11 / 12 / 14 / 2 |
| Touch (CST816S): SDA / SCL / INT / RST | 6 / 7 / 5 / 13  (I²C addr **0x15**) |
| IMU (QMI8658): INT1 / INT2 | 4 / 3 |
| Battery voltage ADC | 1  (Vbat = ADC × 3.3/4096 × 3) |
| BOOT strap | 0 |

**Free for our use — SH1.0 expansion header:** IO15, IO16, IO17, IO18, IO21,
IO33. The MAX3232 lands on two of these.

Do **not** use IO43/IO44 (`board.TX`/`board.RX` = UART0): the ROM bootloader
prints its 115200 log there on every power-up, which would inject garbage into
the DAU. The firmware uses a second UART on the header pins instead.

## DAU maintenance connector (from the A109S wiring diagram, J101 / AIC163)

The aircraft maintenance cable splits J101 into two DB9s:
CH1 = DAU channel A, CH2 = DAU channel B. Both channels behave identically —
a download works the same from either DB9 (confirmed by maintenance), so the
stick needs no channel selection; plug into whichever port is convenient.

| J101 | wire | signal (DAU perspective) |
|------|------|--------------------------|
| A/H  | 177/184 | TXD — data out of DAU -> our RX |
| B/J  | 178/185 | RXD — data into DAU  <- our TX |
| C/K  | 179/186 | CTS |
| D/L  | 180/187 | RTS |
| E/M  | 181/188 | **FUNCTION SEL** |
| F/N  | 182/189 | spare |
| G/P  | 183/190 | SIGNAL RETURN (ground, shared A/B) |

Implications:
- CTS/RTS are wired, so the DAU may use hardware flow control. The captured
  download was plain 3-wire stop-and-wait, so firmware ignores them; wire them
  through only if a future capture shows they're needed.
- **FUNCTION SEL must be resolved before the stick will talk.** Likely the
  "maintenance device attached / select mode" discrete. Buzz out the laptop
  cable's DB9: if it ties FUNCTION SEL to signal return (or leaves it), the
  stick needs nothing; if it lands on DTR/RTS at the DB9, drive it from a spare
  header GPIO (e.g. IO18) through the module.

## Wiring (board -> MAX3232 module -> CH1/DB9)

```
ESP32-S3-Touch-LCD-1.28     MAX3232 module          DAU (via cable DB9, ch A)
  IO16 (UART TX) ----------- TTL TX-in  --- DB9 --- RXD  (J101-B)
  IO17 (UART RX) ----------- TTL RX-out --- DB9 --- TXD  (J101-A)
  3V3  -------------------- VCC   (3V3 ONLY — S3 is not 5 V tolerant)
  GND  -------------------- GND   --- DB9 --- SIGNAL RETURN (J101-G)
  (IO18, if needed) ------- DTR   --- DB9 --- FUNCTION SEL (J101-E)
```

9600 baud, 8N1 ("9600,n,8,1" from the original app). Cross TX/RX and verify the
module's TTL labels (some silkscreen the pins from the PC's perspective). Exact
DB9 pin numbers for TXD/RXD/FUNCTION SEL depend on the maintenance cable's
internal wiring — buzz out the cable (J101 letter to DB9 pin) and record it:

| DB9 pin | J101 | signal |
|---------|------|--------|
| ?       | A    | TXD    |
| ?       | B    | RXD    |
| ?       | E    | FUNCTION SEL |
| ?       | G    | SIGNAL RETURN |

Battery: 350–500 mAh LiPo on the board's **MX1.25** connector (verify polarity
before plugging in — MX1.25 is not the same as Adafruit's JST-PH). A full
download at 9600 baud is ~10–14 min; that battery runs the board with the LCD
on for hours and recharges over USB-C. Optional TVS diodes on RX/TX for
line-transient protection on the flight line.

## Firmware architecture (CircuitPython)

No board-specific CircuitPython build exists for the 1.28, so flash the
**generic ESP32-S3 (N16R8)** build and set the display/touch up in code.

- `boot.py` — USB host present at power-up → office mode (flash exposed to the
  PC). No USB host → aircraft mode (code can write downloads to flash). Board-
  agnostic; unchanged.
- `code.py` — brings up the **GC9A01** panel by hand (`fourwire` +
  `adafruit_gc9a01a`, backlight on IO2), reads the battery via ADC on IO1,
  and runs the touch-driven UI: tap to start, hold to abort, live status +
  progress bar laid out inside the round panel's safe zone.
- `touch_cst816.py` — self-contained **CST816S** driver (I²C 0x15): `read()`
  returns (x, y) or None, plus `wait_touch` / `wait_release` / `hold_checker`.
  The hold_checker is rate-limited so it's safe as dau_protocol's abort_check.
- `dau_protocol.py` — DAU framing/ACK logic, fully reverse-engineered and
  validated against a real capture. Reused unchanged from the earlier board.

The stored file is byte-identical in format to what the Windows app writes, so
hgs-linux (or the original app) reads it unchanged.
