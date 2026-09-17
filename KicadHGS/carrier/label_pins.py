"""Generate silkscreen pin labels for a footprint, straight from its pads.

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" label_pins.py <board.kicad_pcb> [REF]

Reads every pad of the named footprint and drops a silkscreen text beside it,
placed outboard of the pad columns so the labels stay readable once the module
is plugged in and covering the pads.

The point of doing it this way: the position AND the number both come from the
board, so a label can never end up on the wrong pad. Hand-placing 40 of them is
exactly how a mirrored set happens.

Idempotent - it deletes labels from a previous run before adding new ones, so
re-run it after flipping or moving the footprint and everything follows.
"""
import re
import sys
import pcbnew

REF = sys.argv[2] if len(sys.argv) > 2 else "J1"
BOARD = sys.argv[1]

LABEL_MODE = "both"          # "number" | "signal" | "both"
LABEL_LAYER = "front"        # "front" | "back" | "auto" (follow the footprint)
TEXT_MM = 0.8
GAP_MM = 1.0                 # clear of the footprint BODY, not just the pads
MARK = "\u200b"              # zero-width space: marks our labels for re-runs

SIGNALS = {
    1: "TX", 2: "RX", 3: "GND", 4: "IO0", 5: "IO1", 6: "IO2", 7: "IO3",
    8: "GND", 9: "IO4", 10: "IO5", 11: "IO6", 12: "IO7", 13: "GND",
    14: "IO15", 15: "IO16", 16: "IO17", 17: "IO18", 18: "GND", 19: "D-",
    20: "D+", 21: "IO21", 22: "IO38", 23: "GND", 24: "IO39", 25: "IO40",
    26: "IO41", 27: "IO42", 28: "GND", 29: "IO45", 30: "RUN", 31: "IO46",
    32: "IO47", 33: "AGND", 34: "IO48", 35: "VREF", 36: "3V3", 37: "3V3_EN",
    38: "GND", 39: "VSYS", 40: "VBUS",
}


def clean(fn, num):
    """pcbnew hands back the schematic pin name, e.g. 'IO43/U0TX_1'. Strip the
    trailing _<pin> that KiCad appends and keep the first alias."""
    fn = re.sub(r"_%d$" % num, "", fn or "")
    return fn.split("/")[0] if fn else ""


def label_for(num, pinfn):
    name = clean(pinfn, num) or SIGNALS.get(num, "")
    if LABEL_MODE == "signal":
        return name or str(num)
    if LABEL_MODE == "both":
        return ("%d %s" % (num, name)).strip()
    return str(num)


board = pcbnew.LoadBoard(BOARD)
fp = board.FindFootprintByReference(REF)
if fp is None:
    sys.exit("footprint %s not found" % REF)

pads = [(p.GetNumber(), p.GetPosition(), p.GetPinFunction())
        for p in fp.Pads() if p.GetNumber().isdigit()]
if not pads:
    sys.exit("no numbered pads on %s" % REF)
xs = [pos.x for _, pos, _ in pads]
xmin, xmax = min(xs), max(xs)
# Outboard of the whole footprint body: 0.7mm off a pad column still sits among
# the header holes. Use the footprint extents (pads + graphics, no text).
try:
    bb = fp.GetBoundingBox(False, False)
except TypeError:
    bb = fp.GetBoundingBox()
left_edge, right_edge = min(bb.GetLeft(), xmin), max(bb.GetRight(), xmax)
gap = pcbnew.FromMM(GAP_MM)

# --- clear anything a previous run added, plus any hand-placed pin labels
# sitting on top of this footprint, so we do not end up with two sets.
known = set(SIGNALS.values())
bbox = fp.GetBoundingBox()
bbox.Inflate(pcbnew.FromMM(6))
doomed = []
for d in board.GetDrawings():
    if not isinstance(d, pcbnew.PCB_TEXT):
        continue
    if d.GetLayer() != pcbnew.F_SilkS and d.GetLayer() != pcbnew.B_SilkS:
        continue
    txt = d.GetText()
    mine = MARK in txt
    strays = (re.fullmatch(r"\d{1,2}", txt) or txt in known) and bbox.Contains(d.GetPosition())
    if mine or strays:
        doomed.append(d)
for d in doomed:
    board.Remove(d)

# --- place one label per pad, outboard of its own column
if LABEL_LAYER == "front":   layer, mirror = pcbnew.F_SilkS, False
elif LABEL_LAYER == "back":  layer, mirror = pcbnew.B_SilkS, True
else:                        layer = pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS
if LABEL_LAYER == "auto":    mirror = fp.IsFlipped()
added = 0
for num, pos, pinfn in pads:
    left = abs(pos.x - xmin) < abs(pos.x - xmax)
    t = pcbnew.PCB_TEXT(board)
    t.SetText(label_for(int(num), pinfn) + MARK)
    t.SetLayer(layer)
    t.SetPosition(pcbnew.VECTOR2I(left_edge - gap if left else right_edge + gap, pos.y))
    t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(TEXT_MM), pcbnew.FromMM(TEXT_MM)))
    t.SetTextThickness(pcbnew.FromMM(0.12))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_RIGHT if left
                      else pcbnew.GR_TEXT_H_ALIGN_LEFT)
    t.SetMirrored(mirror)
    board.Add(t)
    added += 1

pcbnew.SaveBoard(BOARD, board)
print("%s: removed %d old label(s), added %d on %s"
      % (REF, len(doomed), added, "B.SilkS" if fp.IsFlipped() else "F.SilkS"))
