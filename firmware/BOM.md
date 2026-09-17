# HGS Download Stick — Bill of Materials

Per-unit build (one stick), plus one-time tools/consumables at the bottom.
Prices are rough USD in small quantity; verify current pricing when you order.

**Board (2026-07-31):** Waveshare **25098 = ESP32-S3-Touch-LCD-1.28** (round
1.28" GC9A01 240×240, CST816S capacitive touch, ESP32-S3R2, 16 MB flash /
2 MB PSRAM, USB-C, onboard MX1.25 LiPo charger + battery ADC). Touch replaces
the physical start/abort button. (Supersedes the earlier ESP32-S2 TFT Feather.)

## Core electronics (per unit)
| # | Item | Spec / example | Qty | ~$ | Notes |
|---|------|----------------|-----|----|-------|
| 1 | Waveshare ESP32-S3-Touch-LCD-1.28 | SKU **25098** (round touch LCD, USB-C, LiPo charger) | 1 | 18–24 | the brain + display + touch + charger |
| 2 | MAX3232 RS-232 ↔ TTL module, DB9 | e.g. ANMBEST / generic MAX3232 DB9 board | 1 | 5–8 | ±12 V ↔ 3.3 V; DB9 on board. **Power VCC from 3V3 only** |
| 3 | LiPo battery, 350–500 mAh | JST **MX1.25** 2-pin (match the board's connector, not JST-PH) | 1 | 6 | **verify connector + polarity before plugging in** |
| 4 | Power switch, SPST (optional) | small slide | 0–1 | 1 | inline on battery + or wired to a control pin |
| 5 | TVS diodes (optional) | e.g. SM712 bidirectional on RX,TX | 0–2 | 1 | flight-line transient protection; nice-to-have |

No physical start button in the BOM — the capacitive **touchscreen** is the
start/abort control (tap = start, press-and-hold ≈1.5 s = abort).

## Interconnect (per unit)
| # | Item | Spec | Qty | ~$ |
|---|------|------|-----|----|
| 6 | Silicone hookup wire | 28–30 AWG, few colors | ~30 cm | 0.5 |
| 7 | SH1.0 pigtail (optional) | mates the board's 6-pin expansion header | 0–1 | 1 | clean way to tap IO16/IO17/3V3/GND |
| 8 | Heat-shrink tubing | 2–3 mm | a little | 0.2 |
| 9 | Solder | rosin-core 0.6–0.8 mm | — | — |

The four MAX3232 connections (IO16, IO17, 3V3, GND) can solder to the SH1.0
header pads or a pigtail — see HARDWARE.md.

## Mechanical / enclosure (per unit)
| # | Item | Spec | Qty | ~$ | Notes |
|---|------|------|-----|----|-------|
| 10 | Enclosure (tray + lid) | 3D printed, **round** to suit the 1.28" board | 1 set | 1 (PLA proto) / 15–40 (MJF nylon final) | round display window; PLA to prove fit, MJF PA12 for the real one |
| 11 | M2 heat-set brass inserts | press-fit | 2–4 | 0.5 | board + lid (1.28 board uses M2-class holes — verify) |
| 12 | M2 screws | ~5–6 mm | 2–6 | 0.5 | from an M2 kit |
| 13 | Round lens (optional) | clear polycarbonate disc over the LCD | 0–1 | 0.5 | protects the display |
| 14 | Lanyard / cord | small loop | 1 | 0.5 | it dangles off the DB9 |

## DB9 / aircraft interface — VERIFY FIRST
| # | Item | Notes |
|---|------|-------|
| 15 | DB9 gender/pinout match | The module's DB9 must mate with the maintenance cable. **Buzz out the cable** first (J101 letter → DB9 pin). If gender is wrong, add a gender changer. If null-modem, swap pins 2↔3. Resolve **FUNCTION SEL** (J101-E) — see HARDWARE.md. |

## Per-unit total
- Electronics + interconnect + hardware: **~$35–45**
- Enclosure: **+$1 (PLA proto)** or **+$15–40 (MJF nylon, small batch)**
- **≈ $50–85 per finished unit** in small quantity.

## One-time tools / consumables (not per unit)
| Item | Why |
|------|-----|
| Soldering iron + heat-set insert tip | the 4 signal wires + pressing inserts |
| Multimeter | **buzz out the DB9 cable** (critical) + verify battery polarity |
| USB-C cable | flashing, charging, offloading |
| 3D printer + PLA (you have this) | prototype enclosures |
| M2 screw/standoff/insert assortment kit | covers items 11–12 for many units |
| Wire strippers, flush cutters, heat gun | assembly |

## Software (free)
| Item | Notes |
|------|-------|
| CircuitPython — **generic ESP32-S3 build** | No board-specific build exists for the 1.28. Use the generic Espressif ESP32-S3 (N16R8) build from circuitpython.org; the display/touch are set up manually in code.py |
| Firmware: boot.py, code.py, dau_protocol.py, stick_log.py, **touch_cst816.py** | this repo (firmware/) |
| Libraries: **adafruit_display_text**, **adafruit_gc9a01a** | from the Adafruit CircuitPython bundle. (No adafruit_max1704x — battery is read via ADC on IO1.) |
