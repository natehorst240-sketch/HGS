"""Generate a project-local footprint for the Waveshare ESP32-S3-Touch-LCD-1.9.

Starts from KiCad's Module:RaspberryPi_Pico_Common_THT - the pad grid is
geometrically identical to this board's header (2.54 pitch, 17.78 rows, 48.26
span) - and replaces everything that is Pico-specific:

  * silkscreen / fab outline resized 51.0 x 21.0  ->  52.60 x 29.00 (real PCB)
  * the 55.00 x 31.40 display bezel drawn on User.Drawings so the ~1.2 mm/side
    overhang is visible while placing parts
  * courtyard grown to enclose the bezel, not the Pico body
  * the module's own M2 mounting holes built in

That last point is the reason this exists. With the holes inside the footprint
there is no second footprint to trip courtyards_overlap or npth_inside_courtyard,
and the holes cannot drift out of position relative to pin 1.

Geometry from Waveshare's dimension drawing (SKU 30939):
    PCB            52.60 x 29.00      bezel 55.00 x 31.40 (1.20 overhang/side)
    header         2.54 pitch, 17.78 rows, pin1->pin20 span 48.26
    M2 holes       40.75 apart, 5.06 from PIN 2; 25.00 across (pin-referenced)

Run:  python gen_footprint.py
"""
import os
import re
import uuid as _uuid

KICAD_FP = r"C:\Program Files\KiCad\10.0\share\kicad\footprints"
OUT_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "HGS_Carrier.pretty")
NAME = "ESP32-S3-Touch-LCD-1.9"

_NS = _uuid.UUID("6b21f0d4-9c7a-4e35-8f10-3ab5c9d27e41")
uid = lambda t: str(_uuid.uuid5(_NS, t))

# --- dimensions, all in mm --------------------------------------------------
PITCH, ROWS, SPAN = 2.54, 17.78, 48.26
PCB_L, PCB_W = 52.60, 29.00
BEZEL_L, BEZEL_W = 55.00, 31.40
# The drawing dimensions 5.06 from PIN 2 to the first hole - the holes are
# referenced to the header, not to the module board edge. Anchor to the pins:
# the carrier outline is arbitrary, only the pin/hole relationship must match.
HOLE_PITCH, HOLE_FROM_PIN2, HOLE_ACROSS = 40.75, 5.06, 25.00
HOLE_DRILL = 2.2                      # M2 clearance

# Pad 1 sits at local (0,0); pads run +Y, the second row is at +X = ROWS.
PIN_INSET = (PCB_L - SPAN) / 2.0      # 2.17 from the short edge to pin 1
ROW_INSET = (PCB_W - ROWS) / 2.0      # 5.61 from the long edge to a pin row
EDGE_X0, EDGE_X1 = -ROW_INSET, ROWS + ROW_INSET
EDGE_Y0, EDGE_Y1 = -PIN_INSET, -PIN_INSET + PCB_L
OVER = (BEZEL_L - PCB_L) / 2.0        # 1.20 overhang per side
BEZ_X0, BEZ_X1 = EDGE_X0 - OVER, EDGE_X1 + OVER
BEZ_Y0, BEZ_Y1 = EDGE_Y0 - OVER, EDGE_Y1 + OVER
CY = 0.25                             # courtyard clearance beyond the bezel

HOLE_X = (-(HOLE_ACROSS - ROWS) / 2.0, ROWS + (HOLE_ACROSS - ROWS) / 2.0)
HOLE_Y = (PITCH + HOLE_FROM_PIN2,                 # +7.60 from pad 1
          PITCH + HOLE_FROM_PIN2 + HOLE_PITCH)    # +48.35 from pad 1


# Pin labels. The module covers the pads once plugged in, so labels go OUTSIDE
# the board outline where they stay readable. LABEL_MODE: "number", "signal",
# or "both".
LABEL_MODE = "number"
LABEL_SIZE = 0.8
SIGNALS = {
 1:"IO43",2:"IO44",3:"GND",4:"IO0",5:"IO1",6:"IO2",7:"IO3",8:"GND",9:"IO4",
 10:"IO5",11:"IO6",12:"IO7",13:"GND",14:"IO15",15:"IO16",16:"IO17",17:"IO18",
 18:"GND",19:"D-",20:"D+",21:"IO21",22:"IO38",23:"GND",24:"IO39",25:"IO40",
 26:"IO41",27:"IO42",28:"GND",29:"IO45",30:"RUN",31:"IO46",32:"IO47",33:"AGND",
 34:"IO48",35:"VREF",36:"3V3",37:"3V3_EN",38:"GND",39:"VSYS",40:"VBUS"}


def pin_label(n):
    if LABEL_MODE == "signal": return SIGNALS[n]
    if LABEL_MODE == "both":   return "%d %s" % (n, SIGNALS[n])
    return str(n)


def blocks(src, tok):
    for m in re.finditer(r"\(%s[\s\"]" % tok, src):
        i = m.start(); d = 0; j = i
        while j < len(src):
            if src[j] == "(":
                d += 1
            elif src[j] == ")":
                d -= 1
                if d == 0:
                    break
            j += 1
        yield src[i:j + 1]


src = open(os.path.join(KICAD_FP, "Module.pretty",
                        "RaspberryPi_Pico_Common_THT.kicad_mod"),
           encoding="utf-8").read()

pads = [p for p in blocks(src, "pad")]
assert len(pads) == 40, "expected 40 header pads, got %d" % len(pads)

# Sanity-check the inherited grid against the Waveshare drawing before trusting it.
xy = {}
for p in pads:
    n = re.match(r'\(pad\s+"(\d+)"', p).group(1)
    a = re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", p)
    xy[int(n)] = (float(a.group(1)), float(a.group(2)))
assert abs((xy[2][1] - xy[1][1]) - PITCH) < 1e-6, "pitch mismatch"
assert abs((xy[40][0] - xy[1][0]) - ROWS) < 1e-6, "row spacing mismatch"
assert abs((xy[20][1] - xy[1][1]) - SPAN) < 1e-6, "pin span mismatch"

# The stock M2 hole pad, reused verbatim rather than hand-written.
mh = open(os.path.join(KICAD_FP, "MountingHole.pretty",
                       "MountingHole_2.2mm_M2.kicad_mod"), encoding="utf-8").read()
hole_pad = next(blocks(mh, "pad"))


def line(x0, y0, x1, y1, layer, width, tag):
    return ('  (fp_line (start %.4f %.4f) (end %.4f %.4f)\n'
            '    (stroke (width %s) (type solid)) (layer "%s") (uuid "%s"))'
            % (x0, y0, x1, y1, width, layer, uid(tag)))


def rect(x0, y0, x1, y1, layer, width, tag):
    return "\n".join([
        line(x0, y0, x1, y0, layer, width, tag + ":t"),
        line(x1, y0, x1, y1, layer, width, tag + ":r"),
        line(x1, y1, x0, y1, layer, width, tag + ":b"),
        line(x0, y1, x0, y0, layer, width, tag + ":l"),
    ])


out = []
out.append('(footprint "%s"' % NAME)
out.append('  (version 20241229) (generator "hgs_gen") (generator_version "10.0")')
out.append('  (layer "F.Cu")')
out.append('  (descr "Waveshare ESP32-S3-Touch-LCD-1.9 (SKU 30939). Pico-format '
           'header: 2.54 pitch, 17.78 rows, 20 pins/row. PCB 52.60x29.00, bezel '
           '55.00x31.40, M2 holes 40.75x25.00. Pad grid from '
           'Module:RaspberryPi_Pico_Common_THT.")')
out.append('  (tags "waveshare esp32-s3 touch lcd module pico-format")')
out.append('  (attr through_hole)')
out.append('  (property "Reference" "J" (at %.2f -5 0) (layer "F.SilkS") (uuid "%s")\n'
           '    (effects (font (size 1 1) (thickness 0.15))))'
           % (ROWS / 2.0, uid("ref")))
out.append('  (property "Value" "%s" (at %.2f %.2f 0) (layer "F.Fab") (uuid "%s")\n'
           '    (effects (font (size 1 1) (thickness 0.15))))'
           % (NAME, ROWS / 2.0, EDGE_Y1 + 3, uid("val")))

# --- graphics ---------------------------------------------------------------
out.append("  " + rect(EDGE_X0, EDGE_Y0, EDGE_X1, EDGE_Y1, "F.SilkS", 0.12, "silk").strip())
out.append("  " + rect(EDGE_X0, EDGE_Y0, EDGE_X1, EDGE_Y1, "F.Fab", 0.1, "fab").strip())
out.append("  " + rect(BEZ_X0, BEZ_Y0, BEZ_X1, BEZ_Y1, "Dwgs.User", 0.1, "bezel").strip())
out.append("  " + rect(BEZ_X0 - CY, BEZ_Y0 - CY, BEZ_X1 + CY, BEZ_Y1 + CY,
                       "F.CrtYd", 0.05, "crtyd").strip())
# Pin 1 marker on silk, outboard of the pad so it survives assembly.
out.append(line(EDGE_X0, EDGE_Y0, EDGE_X0 + 2.0, EDGE_Y0, "F.SilkS", 0.3, "p1a"))
out.append(line(EDGE_X0, EDGE_Y0, EDGE_X0, EDGE_Y0 + 2.0, "F.SilkS", 0.3, "p1b"))
out.append('  (fp_text user "USB-C" (at %.2f %.2f 0) (layer "F.SilkS") (uuid "%s")\n'
           '    (effects (font (size 0.8 0.8) (thickness 0.12))))'
           % (ROWS / 2.0, EDGE_Y0 - 1.6, uid("usb")))

# --- pads: the 40 header pins, untouched ------------------------------------
for p in pads:
    out.append("  " + p.strip())

# --- the module's own M2 mounting holes -------------------------------------
for i, hx in enumerate(HOLE_X):
    for k, hy in enumerate(HOLE_Y):
        pad = re.sub(r"\(at [-\d.]+ [-\d.]+\)", "(at %.4f %.4f)" % (hx, hy), hole_pad, count=1)
        pad = re.sub(r'\(uuid "[^"]*"\)', '(uuid "%s")' % uid("hole:%d:%d" % (i, k)), pad)
        if "(uuid" not in pad:
            pad = pad[:-1] + ' (uuid "%s"))' % uid("hole:%d:%d" % (i, k))
        out.append("  " + pad.strip())

# --- pin number labels on F.SilkS, outboard of the module outline -----------
for num, (px, py) in sorted(xy.items()):
    left = px < ROWS / 2.0
    tx = (EDGE_X0 - 0.7) if left else (EDGE_X1 + 0.7)
    just = "right" if left else "left"
    out.append('  (fp_text user "%s" (at %.3f %.3f 0) (layer "F.SilkS") '
               '(uuid "%s") (effects (font (size %.2f %.2f) (thickness 0.12)) '
               '(justify %s)))'
               % (pin_label(num), tx, py, uid("lbl:%d" % num),
                  LABEL_SIZE, LABEL_SIZE, just))

out.append(")")

os.makedirs(OUT_LIB, exist_ok=True)
path = os.path.join(OUT_LIB, NAME + ".kicad_mod")
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")

print("wrote", path)
print("  pads: 40 header + %d M2 holes" % (len(HOLE_X) * len(HOLE_Y)))
print("  pad 1 local (0,0);  holes at X %s  Y %s"
      % (["%.2f" % v for v in HOLE_X], ["%.2f" % v for v in HOLE_Y]))
print("  PCB outline  X %.2f..%.2f  Y %.2f..%.2f" % (EDGE_X0, EDGE_X1, EDGE_Y0, EDGE_Y1))
print("  bezel        X %.2f..%.2f  Y %.2f..%.2f" % (BEZ_X0, BEZ_X1, BEZ_Y0, BEZ_Y1))
