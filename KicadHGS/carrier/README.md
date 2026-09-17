# HGS Download Stick — RS-232 carrier

Pico-format carrier that sits under the **Waveshare ESP32-S3-Touch-LCD-1.9
(SKU 30939)** and gives it a DE9 RS-232 port for the A109 DAU maintenance
connector.

> **This revision is a deliberately minimal 3-wire MAX3232 straight-through.**
> An earlier design had jumpers (JP1–JP3), a 2N7002 for FUNCTION SEL, D1/D2 TVS,
> 47 Ω series resistors, and a CTS sense line. Those were **removed** — the real
> captured download is plain 3-wire stop-and-wait (see `../../reverse/PROTOCOL.md`),
> so none of them are needed. If you're reading an older description mentioning
> jumpers/MOSFET/TVS, it's stale; the netlist below is the truth.

| File | What it is |
|---|---|
| `HGS_Carrier.kicad_sch` | the schematic — open this |
| `HGS_Carrier.kicad_sym` | project symbol for the module (40 pins, real ESP32 names) |
| `gen_schematic.py` | generator that produced the schematic — edit this, not the .kicad_sch |
| `bom.csv`, `net.net`, `erc.rpt` | exports, regenerate any time with `kicad-cli` |
| `upstream/` | mtguerreiro's MAX3232 sheet + licence (see Attribution) |

## The circuit (as actually netlisted)

Verified from `net.net`, not the prose:

```
ESP32-S3-Touch-LCD-1.9 (J1)     MAX3232 (U1) on 3V3        DE9 (J2, male DTE)
  IO16  (J1 pin 15) ----------- T1IN(11) -> T1OUT(14) ---- pin 3  TXD  -> DAU RXD
  IO18  (J1 pin 17) <----------- R1OUT(12) <- R1IN(13) ---- pin 2  RXD  <- DAU TXD
  GND (all 8 module GND) ------- GND(15) ----------------- pin 5  GND + shell
  3V3   (J1 pin 36) ----------- VCC(16)
```

- **U1 MAX3232**, VCC on **+3V3 only** (never 5 V — the S3 is not 5 V tolerant),
  charge-pump caps **C1–C5 100 nF** (C1±, C2±, V+, V−).
- **9600 baud, 8N1** (`Serial1.begin(9600, SERIAL_8N1, RX=IO18, TX=IO16)` in
  firmware) — matches the original app's `9600,n,8,1`.
- The firmware uses **Serial1 on IO16/IO18**, a second UART. Do **not** move it to
  IO43/IO44 (UART0, header pins 1/2): the ROM bootloader prints its 115200 banner
  there at power-up, straight into the DAU.
- MAX3232 **second channel (T2/R2) is unused and unconnected** — no FUNCTION SEL
  driver, no CTS sense on this revision (see below).

## Cable pinout — standard DTE serial

The maintenance cable presents a **standard DTE serial port** (the same pinout a
generic USB-to-serial adapter uses, which is how the HGS laptop connected). The
board is straight-through, male DE9:

| DE9 pin | Signal | Our side |
|---|---|---|
| 2 | RXD | receive ← MAX3232 R1IN |
| 3 | TXD | transmit → MAX3232 T1OUT |
| 5 | GND | signal return |
| 1/4/6/7/8/9 | — | **not connected** |

## FUNCTION SEL — open item (resolve by test, not by adding parts)

The A109 maintenance connector (J101-E) carries a **FUNCTION SEL** discrete that
*may* need to be asserted before the DAU will stream. **This board does not drive
it** (DE9 pin 4 and IO15 are unconnected) — a deliberate simplification.

Resolve it empirically:
1. Build the board and run a real download. If the DAU streams, FUNCTION SEL was
   not needed — done.
2. If the DAU stays silent, buzz out the working HGS laptop/USB-serial cable to
   see whether it drives DTR (pin 4) or RTS (pin 7). Only then add a driver:
   route `IO15 → MAX3232 T2IN → T2OUT → DE9 pin 4` (one edit in
   `gen_schematic.py`) and set `USE_FUNCTION_SEL = true` in firmware.

`USE_FUNCTION_SEL` stays `false` until confirmed.

## Verified

Regenerate before ordering (numbers change with the design — don't trust a stale
copy):

```bash
cd KicadHGS/carrier && python gen_schematic.py       # regenerates schematic + exports
kicad-cli sch erc HGS_Carrier.kicad_sch              # run ERC
```

Real nets in the current design: `+3V3, GND, /DAU_TX_TTL, /DAU_RX_TTL, /DE9_P2,
/DE9_P3, /V_PLUS, /V_MINUS, /C1P, /C1N, /C2P, /C2N` — everything else is an
explicit no-connect.

## BOM (current, minimal)

| Ref | Value | Footprint |
|---|---|---|
| U1 | MAX3232 | SOIC-16 |
| C1–C5 | 100 nF | 0603 |
| J1 | ESP32-S3-Touch-LCD-1.9 header | RaspberryPi_Pico_Common_THT |
| J2 | DE9 male | DSUB-9 horizontal |

(The older `HGS_Carrier.csv` still lists JP1–JP3/Q1/D1/D2/R1–R4 from the previous
design — ignore it; `fab/HGS_Carrier_BOM.csv` is the current one.)

## Reuse rather than authored

- **Header footprint:** `Module:RaspberryPi_Pico_Common_THT` (ships with KiCad).
  Verified against Waveshare's dimension drawing: 2.54 mm pitch, 17.78 mm row
  spacing, 48.26 mm pin 1→20 span — exact match.
- **MAX3232 section:** topology follows `mtguerreiro/pcbs` (BSD-3-Clause). See
  Attribution. (The 47 Ω series resistors from that reference were dropped here.)
- **Everything else** is stock KiCad symbols.

## Layout notes

- **Do not use header pins 1/2** (IO43/IO44 = UART0) for the serial port.
- Module PCB is **52.60 × 29.00 mm**; the bezel is **55.00 × 31.40 mm** and
  overhangs ~1.2 mm per side. M2 mounting holes on a **40.75 × 25.00 mm**
  rectangle. The Pico footprint's silk outline is a 51.0 × 21.0 Pico — redraw it.
- The DE9 flange (~30.8 mm) is wider than the board. Bolt its jackscrews to the
  enclosure so the connector carries the hanging load, not the PCB.
- Optional: TVS on RX/TX for flight-line transients (footprints not on this
  revision; add if the environment warrants).
- **Print the layout 1:1 and test-fit the real module before ordering. Order one
  board first.**

## Regenerating

```bash
cd KicadHGS/carrier && python gen_schematic.py
```

Connectivity is by net label, placed programmatically on each pin's exact
connection point using geometry from KiCad's own libraries — this rules out the
hand-drawn failure of a label one grid step off a pin. Edit `gen_schematic.py`
and re-run rather than hand-editing the `.kicad_sch`. (This README is hand-written
and safe to edit directly.)

## Attribution

The MAX3232 section derives from **[mtguerreiro/pcbs](https://github.com/mtguerreiro/pcbs)**,
`pi-pico-itm39xxc-if/ttl_rs232_max3232.kicad_sch`, **BSD-3-Clause**. The original
sheet and licence text are preserved verbatim in `upstream/`.
