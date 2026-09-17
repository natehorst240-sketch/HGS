# HGS Download Stick — enclosure build plan (Fusion 360)

> ⚠️ **SUPERSEDED — needs redesign for the new board (2026-07-31).** This plan
> is written for the old **rectangular ESP32-S2 Feather + RS-232 breakout**
> stack. The build now uses the **Waveshare 25098 = ESP32-S3-Touch-LCD-1.28**,
> a **round** board (~Ø40 mm) with a round display and an MX1.25 battery
> connector, paired with a small **MAX3232 DB9 module** instead of the Feather-
> format RS-232 breakout. That changes the enclosure fundamentally:
> - Body is a **round puck**, not a Feather-width rectangle; display window is a
>   circle. No 50.8×22.86 Feather PCB, no Feather mounting-hole pattern.
> - Mounting is **M2-class**, not M2.5; there is no Feather↔breakout standoff
>   stack — the MAX3232 module mounts separately and wires to the SH1.0 header
>   (IO16/IO17/3V3/GND).
> - **No BOOT-button nub** — the start/abort control is the touchscreen, so the
>   lid just needs the round display window, not a button feature.
> - Still valid, carry forward: hang-from-DB9 short-cantilever intent; the DB9
>   flange dimensions (~30.8 W × 12.55 H, jackscrews 24.99 apart); USB-C tail
>   opening; screwed lid for service.
>
> **TODO before printing:** measure the 25098 PCB diameter, hole pattern, LCD
> window Ø/offset, USB-C port position, and the MAX3232 module footprint, then
> rewrite the dimensions below. The old rectangular numbers do not apply.

Design intent: the stick **hangs from the DB9** plugged into the aircraft, so
keep it **short** (small cantilever = less torque on the connector), display
facing out. Screwed lid (M2.5) for service. Stack, bottom → top:

    RS-232 + DB9 board  →  LiPo (in the gap)  →  Feather (display up)  →  lid window

Two M2.5 standoffs at the DB9 end tie the Feather to the RS-232 board; the
battery fills the gap between them. USB-C and the power switch face the tail
(opposite the DB9).

---

## 0. Do this first — import the real geometry
Adafruit publishes **STEP + DXF** files for the ESP32-S2 TFT Feather and most
breakouts. Import them into Fusion and model the case *around* them. That gives
exact board outlines, mounting-hole positions, and connector locations — don't
hand-key hole coordinates. Everything below is the envelope, clearances, and
cutout sizing to design around those imported bodies.

## 1. Component dimensions
Confident numbers are given; **[MEASURE]** = confirm on your actual parts /
STEP file before committing.

| Part | Size (mm) | Notes |
|------|-----------|-------|
| ESP32-S2 TFT Feather PCB | 50.8 L × 22.86 W × ~1.6 | standard Feather; 4× Ø2.5 mounting holes |
| TFT active window | ~25 × 14 | 1.14" ST7789; window the glass +0.5 all round |
| USB-C on Feather | opening ~9.5 × 4.5 | on one short edge |
| LiPo 350 mAh (Adafruit 2750) | ~37 × 20 × 6.4 **[MEASURE]** | wires add length; leave slack room |
| RS-232 full-pinout breakout | ~40 × 25 **[MEASURE]** | DB9 on one end |
| DB9 connector flange | ~30.8 W × 12.55 H | jackscrew holes 24.99 apart; **wider than the Feather** |
| Power switch | **[MEASURE]** | slot to match your SPST slide switch |

Key consequence: the **DB9 (30.8 wide) is wider than the Feather (22.86)** — the
case internal width is set by the DB9, ~31 mm, external ~35–36 mm.

## 2. Overall envelope (target)
- **Length ≈ 58–62 mm** (Feather 50.8 + tail wall + DB9-end wall). Minimize.
- **Width ≈ 35–36 mm** (driven by the DB9 flange + walls).
- **Height ≈ 20 mm** (see stack below). Thin on purpose.

## 3. Stack heights (interior)
| Layer | Height (mm) |
|-------|-------------|
| floor clearance under RS-232 board | 1.5 |
| RS-232 board | 1.6 |
| **gap (standoff) — holds the LiPo** | **~10** (≥ battery 6.4 + breakout top parts) |
| Feather PCB | 1.6 |
| TFT + clearance to lid | ~3 |
| lid | 2 |
| **interior total** | **~19.7** |

Set the standoff gap after measuring the battery + the tallest part on top of
the RS-232 breakout (the MAX3232 + caps).

## 4. Standoffs & board mounting
- **Feather ↔ RS-232 board:** 2× M2.5 at the **DB9 end** holes (the "last 2
  standoffs"). M2.5 screw through Feather → threaded standoff (or printed boss
  + heat-set insert) → RS-232 board. Length = the ~10 mm gap.
- The Feather's other 2 holes (tail end) land on **printed bosses** from the
  tray floor so the free end can't flex.
- LiPo sits in the gap on a thin shelf or double-sided tape pad; add a low rib
  so it can't slide into the DB9 solder side.

## 5. Cutouts
- **DB9 aperture** (DB9 end wall): D-shaped opening for the connector to mate
  with the cable. Size to the flange + 0.3 clearance; add 2 holes for the
  jackscrews at 24.99 mm if you want to bolt the DB9 to the wall (recommended —
  it makes the wall carry the hanging load, not the PCB solder joints).
- **TFT window** (lid): 26 × 15 opening over the display; optional 1 mm inset
  ledge for a clear polycarbonate lens.
- **USB-C** (tail wall): 10.5 × 5.5 opening, aligned to the Feather's port.
- **Power switch** (tail or side wall): slot per the switch **[MEASURE]**.
- **Button:** use the Feather's on-board BOOT button via a **flex nub / hole**
  in the lid, or add an external momentary button (GPIO0→GND) with a cap.

## 6. Lid & fasteners
- 4× **M2.5** screws, corners, into brass **heat-set inserts** (Ø3.4 hole,
  press-fit) in tray posts — far more durable than self-tapping into plastic
  for a tool that gets opened.
- Lip/tongue joint (1 mm) between tray and lid for a dust seal and alignment.
- **Lanyard loop** boss on the tail end (hang it on the toolbox / your wrist
  while it dangles from the aircraft).

## 7. Walls, tolerances, print
- Walls: **2.5 mm** for the PLA prototype; **2.0 mm** works for the PETG final.
- Fillet external edges R1.5–2 (comfort + strength); internal R0.5.
- Clearances: **0.25 mm** around connector cutouts, **0.15 mm** on board-edge
  slots. Print a 15-min "cutout coupon" (DB9 + USB-C apertures only) to dial
  these in before printing the whole box.
- Print orientation: tray open-side up, lid flat — no supports needed if the
  DB9 aperture is on a vertical wall (bridge ≤ 13 mm is fine).

## 8. Manufacturing — prototype at home, send the FINAL out

**Prototype yourself (PLA):** print 1–2 iterations to validate fit, cutout
alignment, and standoff heights. Cheap and fast, and you *must* prove the fit
before paying a service.

**Final: outsource to an on-demand manufacturing service.** Upload the CAD, pick
a material, they make it and ship it back. Good fits for a small run of a
durable flightline tool:

| Process | Material | Why / notes |
|---------|----------|-------------|
| **MJF (HP Multi Jet Fusion)** | **PA12 nylon** | **Recommended default.** Tough, slightly flexible, survives drops; no support marks; thin walls OK (down to ~1 mm). Cheap in low volume. |
| SLS | PA11/PA12 nylon | Very similar to MJF; PA11 is even more impact-tough. |
| CNC | Delrin (POM) / PC | Most rugged, but pockets/cutouts cost more to machine; pricier. |
| Injection molding | ABS/PC | Only worth it at hundreds+ units (tooling cost). Not for a handful. |

Nylon via MJF/SLS is exactly what makes the "thinner **and** more durable" goal
possible — you can run 1.2–1.5 mm walls (vs ~2.5 mm at home) and it's tougher
than home-printed PETG.

### What to send them
- **STEP file** (`.step`/`.stp`) — the universal format every service and
  machinist accepts. Export it from Fusion (File → Export → STEP).
- **STL** as a backup (print services often want it; mesh at fine resolution).
- The **spec below** pasted into the order notes.

### Order spec (paste into the quote)
- Process/material: **MJF, PA12 nylon** (or SLS PA12). 1 part (or your qty).
- Wall thickness: 1.2–1.5 mm (already in the model).
- Tolerance: standard (±0.3 mm is fine); note the **DB9 and USB-C cutouts are
  fit-critical** — hold ±0.15 mm there.
- Finish: as-printed (bead-blast/dyed black optional for looks).
- Threads: **none in the plastic** — I'm using M2.5 heat-set inserts (call out
  the Ø3.4 mm insert holes so they don't "clean them up").
- No sealed cavities (box is open) → no powder-escape holes needed.

### Where
Instant-quote services that take a STEP/STL and ship the part: **Xometry,
Protolabs / Protolabs Network (Hubs), PCBWay, JLCPCB 3D printing, Craftcloud**
(aggregator that price-compares several). Upload, choose MJF PA12, checkout.

### Design-for-service tweaks (already reflected above)
- Keep the M2.5 **heat-set inserts** (you press them in after the part arrives)
  rather than modeled threads — cleaner and more durable than printed threads.
- Fillet internal corners R0.5+ (nylon likes it; avoids stress risers).
- Emboss a small **part name + rev** on the inside floor so reorders match.

## 9. Fusion modeling sequence
1. Import Feather + RS-232 STEP files; orient the stack per §0.
2. Sketch the tray footprint (§2), extrude walls (§7).
3. Project the board holes; add standoff/boss features (§4).
4. Cut the apertures (§5) referencing the imported connector bodies.
5. Split off the lid; add the lip, TFT window, screw posts/inserts (§6).
6. Print the cutout coupon (§7), adjust clearances, then print the full case.
