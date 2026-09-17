"""Generate the HGS Download Stick carrier schematic for KiCad 10.

The carrier is a Pico-format board that sits under the Waveshare
ESP32-S3-Touch-LCD-1.9 and gives it an RS-232 port: MAX3232 level shifter, a
DE9, and provision for the still-unresolved FUNCTION SEL discrete.

Why generated rather than hand-drawn: connectivity here is entirely by net
label, and a script can place every label exactly on its pin's connection point
using the pin geometry read from KiCad's own symbol libraries. That removes the
usual failure mode of a hand-built netlist - a label sitting one grid step off a
pin, which looks connected and is not.

The MAX3232 section follows mtguerreiro/pcbs (BSD-3-Clause), see
carrier/upstream/. Run:  python gen_schematic.py
"""
import os
import re
import uuid as _uuid

KICAD_SYM = r"C:\Program Files\KiCad\10.0\share\kicad\symbols"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT = "HGS_Carrier"

# Deterministic UUIDs: regenerating must not churn the file.
_NS = _uuid.UUID("2f1c9a7e-5b3d-4c81-9a2e-7d6f4b1c8e05")
def uid(tag):
    return str(_uuid.uuid5(_NS, tag))


# --- read pin geometry out of KiCad's installed libraries -------------------
def symbol_block(lib, name):
    src = open(os.path.join(KICAD_SYM, lib + ".kicad_sym"), encoding="utf-8").read()
    start = src.find('\n\t(symbol "%s"' % name)
    if start < 0:
        raise SystemExit("symbol not found: %s:%s" % (lib, name))
    depth, i = 0, start + 1
    while i < len(src):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[start + 1:i + 1]
        i += 1
    raise SystemExit("unterminated symbol %s" % name)


def strip_lib_only(blk):
    """Remove tokens that exist in .kicad_sym but that the schematic parser rejects.

    A schematic's lib_symbols cache is NOT the same dialect as a symbol library:
    `in_pos_files`, and `show_name` / `do_not_autoplace` inside properties, are
    library-only. Leaving any of them in makes KiCad refuse the whole file with
    nothing more helpful than "Failed to load schematic".
    """
    for tok in ("in_pos_files", "show_name", "do_not_autoplace"):
        blk = re.sub(r'\n\s*\(%s (?:yes|no)\)' % tok, '', blk)
    return blk


def split_children(blk):
    """(text before the first child, [(token, text), ...]) for direct children."""
    i = blk.index("(") + 1
    depth, start, kids = 1, None, []
    while i < len(blk):
        c = blk[i]
        if c == "(":
            if depth == 1:
                start = i
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 1 and start is not None:
                text = blk[start:i + 1]
                kids.append((text[1:].split(None, 1)[0].strip("()"), text))
                start = None
            elif depth == 0:
                break
        i += 1
    head = blk[:kids[0][1] and blk.index(kids[0][1])] if kids else blk
    return head.rstrip(), kids


def prop_name(text):
    m = re.match(r'\(property\s+"([^"]*)"', text)
    return m.group(1) if m else None


def resolve_symbol(lib, name):
    """Return a symbol block that actually carries pins.

    Many KiCad symbols are derived: MAX3232 is `(extends "MAX232")` and holds no
    pins of its own, and the same is true of the DE9 mounting-hole and solder
    jumper variants. Graft the parent's geometry onto the child's name so pin
    lookup and lib_symbols emission both see a complete symbol.
    """
    blk = strip_lib_only(symbol_block(lib, name))
    m = re.search(r'\(extends "([^"]+)"', blk)
    if not m:
        return blk
    parent = m.group(1)
    pblk = strip_lib_only(symbol_block(lib, parent))
    pblk = pblk.replace('(symbol "%s"' % parent, '(symbol "%s"' % name, 1)
    pblk = pblk.replace('(symbol "%s_' % parent, '(symbol "%s_' % name)

    # Graphics and pins come from the parent; everything the child overrides -
    # Value, Datasheet, Description, keywords, footprint filters - comes from the
    # child. Keeping the parent's properties is what makes KiCad report the
    # cached symbol as differing from the library copy.
    head, pkids = split_children(pblk)
    _, ckids = split_children(blk)
    over = {}
    for tok, text in ckids:
        if tok == "symbol":
            continue                       # child never carries units
        key = (tok, prop_name(text)) if tok == "property" else (tok, None)
        over[key] = text
    merged, used = [], set()
    for tok, text in pkids:
        key = (tok, prop_name(text)) if tok == "property" else (tok, None)
        if key in over and tok != "symbol":
            merged.append(over[key]); used.add(key)
        else:
            merged.append(text)
    for key, text in over.items():         # child-only properties
        if key not in used and key[0] == "property":
            merged.append(text)
    return head + "\n" + "\n".join(merged) + "\n)"


def pins_of(block):
    """{number: (x, y, name)} in symbol-local coords; (x,y) is the connection point."""
    out = {}
    for m in re.finditer(
            r'\(pin\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)'
            r'.*?\(name\s+"([^"]*)".*?\(number\s+"([^"]*)"', block, re.S):
        x, y, _rot, nm, num = m.groups()
        out[num] = (float(x), float(y), nm)
    return out


LIBS = {
    "Interface_UART:MAX3232": None,
    "Connector:DE9_Pins_MountingHoles": None,
    "Device:R_Small": None,
    "Device:C_Small": None,
    "power:GND": None,
    "power:+3V3": None,
    "power:PWR_FLAG": None,
}
for lid in list(LIBS):
    lib, nm = lid.split(":")
    LIBS[lid] = resolve_symbol(lib, nm)

PINS = {lid: pins_of(blk) for lid, blk in LIBS.items()}


# --- the module symbol: 40 pins, real ESP32 names ---------------------------
# Pin numbers follow the Pico convention the board implements, so they match
# Module:RaspberryPi_Pico_Common_THT pad-for-pad.
MODULE_PINS = [
    # (pin, name, type)  left column = 1..20, right column = 40..21
    (1, "IO43/U0TX", "bidirectional"), (2, "IO44/U0RX", "bidirectional"),
    (3, "GND", "power_in"), (4, "IO0/BOOT", "bidirectional"),
    (5, "IO1", "bidirectional"), (6, "IO2", "bidirectional"),
    (7, "IO3", "bidirectional"), (8, "GND", "power_in"),
    (9, "IO4/BAT_ADC", "bidirectional"), (10, "IO5", "bidirectional"),
    (11, "IO6", "bidirectional"), (12, "IO7/IMU_INT2", "bidirectional"),
    (13, "GND", "power_in"), (14, "IO15", "bidirectional"),
    (15, "IO16", "bidirectional"), (16, "IO17/TP_RESET", "bidirectional"),
    (17, "IO18", "bidirectional"), (18, "GND", "power_in"),
    (19, "IO19/USB_D-", "bidirectional"), (20, "IO20/USB_D+", "bidirectional"),
    (21, "IO21/TP_INT", "bidirectional"), (22, "IO38", "bidirectional"),
    (23, "GND", "power_in"), (24, "IO39/SD_CMD", "bidirectional"),
    (25, "IO40/SD_D0", "bidirectional"), (26, "IO41/SD_CLK", "bidirectional"),
    (27, "IO42", "bidirectional"), (28, "GND", "power_in"),
    (29, "IO45", "bidirectional"), (30, "RUN", "input"),
    (31, "IO46", "bidirectional"), (32, "IO47/SDA", "bidirectional"),
    (33, "AGND", "power_in"), (34, "IO48/SCL", "bidirectional"),
    (35, "VREF", "power_in"), (36, "3V3", "power_out"),
    (37, "3V3_EN", "input"), (38, "GND", "power_in"),
    (39, "VSYS", "power_out"), (40, "VBUS", "power_out"),
]

MOD_W, PITCH = 45.72, 2.54
MOD_H = PITCH * 21


def module_symbol():
    """A 40-pin rectangle: pins 1-20 down the left, 21-40 up the right."""
    half_w, half_h = MOD_W / 2.0, MOD_H / 2.0
    s = []
    s.append('  (symbol "ESP32-S3-Touch-LCD-1.9"')
    s.append('    (pin_names (offset 1.016))')
    s.append('    (exclude_from_sim no) (in_bom yes) (on_board yes)')
    s.append('    (property "Reference" "J" (at 0 %.2f 0)' % (half_h + 2.54))
    s.append('      (effects (font (size 1.27 1.27))))')
    s.append('    (property "Value" "ESP32-S3-Touch-LCD-1.9" (at 0 %.2f 0)' % (-half_h - 2.54))
    s.append('      (effects (font (size 1.27 1.27))))')
    s.append('    (property "Footprint" "Module:RaspberryPi_Pico_Common_THT" (at 0 0 0)')
    s.append('      (effects (font (size 1.27 1.27)) hide))')
    s.append('    (property "Datasheet" "https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-1.9" (at 0 0 0)')
    s.append('      (effects (font (size 1.27 1.27)) hide))')
    s.append('    (property "Description" "Waveshare SKU 30939, Pico-format header" (at 0 0 0)')
    s.append('      (effects (font (size 1.27 1.27)) hide))')
    s.append('    (symbol "ESP32-S3-Touch-LCD-1.9_0_1"')
    s.append('      (rectangle (start %.2f %.2f) (end %.2f %.2f)' % (-half_w, half_h, half_w, -half_h))
    s.append('        (stroke (width 0.254) (type default)) (fill (type background))))')
    s.append('    (symbol "ESP32-S3-Touch-LCD-1.9_1_1"')
    for num, name, ptype in MODULE_PINS:
        if num <= 20:                      # left column, top to bottom
            x, y, rot = -half_w - 5.08, half_h - PITCH * num, 0
        else:                              # right column, bottom to top
            x, y, rot = half_w + 5.08, half_h - PITCH * (41 - num), 180
        s.append('      (pin %s line (at %.2f %.2f %d) (length 5.08)' % (ptype, x, y, rot))
        s.append('        (name "%s" (effects (font (size 1.27 1.27))))' % name)
        s.append('        (number "%d" (effects (font (size 1.27 1.27)))))' % num)
    s.append('    ))')
    return "\n".join(s), {
        num: ((-MOD_W / 2 - 5.08, MOD_H / 2 - PITCH * num) if num <= 20
              else (MOD_W / 2 + 5.08, MOD_H / 2 - PITCH * (41 - num)))
        for num, _, _ in MODULE_PINS
    }


MOD_SYM_TEXT, MOD_PIN_XY = module_symbol()

with open(os.path.join(OUT_DIR, PROJECT + ".kicad_sym"), "w", encoding="utf-8") as f:
    f.write('(kicad_symbol_lib (version 20241209) (generator "hgs_gen")\n')
    f.write('  (generator_version "10.0")\n')
    f.write(MOD_SYM_TEXT + "\n)\n")

PINS["%s:ESP32-S3-Touch-LCD-1.9" % PROJECT] = {
    str(n): (MOD_PIN_XY[n][0], MOD_PIN_XY[n][1], nm) for n, nm, _ in MODULE_PINS
}
LIBS["%s:ESP32-S3-Touch-LCD-1.9" % PROJECT] = MOD_SYM_TEXT


# --- placement ---------------------------------------------------------------
# (ref, lib_id, value, x, y, footprint)
PLACE = [
    ("J1", "%s:ESP32-S3-Touch-LCD-1.9" % PROJECT, "ESP32-S3-Touch-LCD-1.9",
     70, 100, "Module:RaspberryPi_Pico_Common_THT"),
    ("U1", "Interface_UART:MAX3232", "MAX3232",
     170, 95, "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"),
    ("J2", "Connector:DE9_Pins_MountingHoles", "DE9_Pins",
     250, 100, "Connector_Dsub:DSUB-9_Pins_Horizontal_P2.77x2.84mm_EdgePinOffset4.94mm_Housed_MountingHolesOffset4.94mm"),
    ("C1", "Device:C_Small", "100nF", 205, 55, "Capacitor_SMD:C_0603_1608Metric"),
    ("C2", "Device:C_Small", "100nF", 217, 55, "Capacitor_SMD:C_0603_1608Metric"),
    ("C3", "Device:C_Small", "100nF", 229, 55, "Capacitor_SMD:C_0603_1608Metric"),
    ("C4", "Device:C_Small", "100nF", 241, 55, "Capacitor_SMD:C_0603_1608Metric"),
    ("C5", "Device:C_Small", "100nF", 253, 55, "Capacitor_SMD:C_0603_1608Metric"),
]

# (ref, pin) -> net label
NETS = {
    # --- module: only what the level shifter needs ------------------------
    ("J1", "15"): "DAU_TX_TTL",      # IO16 (header pin 15) -> T1IN
    ("J1", "17"): "DAU_RX_TTL",      # IO18 (header pin 17) <- R1OUT
    ("J1", "36"): "+3V3",
    # every ground pin on the header, for a short return path
    ("J1", "3"): "GND", ("J1", "8"): "GND", ("J1", "13"): "GND",
    ("J1", "18"): "GND", ("J1", "23"): "GND", ("J1", "28"): "GND",
    ("J1", "33"): "GND", ("J1", "38"): "GND",
    # --- MAX3232: datasheet typical operating circuit ---------------------
    ("U1", "1"): "C1P",   ("U1", "2"): "V_PLUS", ("U1", "3"): "C1N",
    ("U1", "4"): "C2P",   ("U1", "5"): "C2N",    ("U1", "6"): "V_MINUS",
    ("U1", "11"): "DAU_TX_TTL",      # T1IN  <- IO16, direct, no series R
    ("U1", "12"): "DAU_RX_TTL",      # R1OUT -> IO18, direct
    ("U1", "13"): "DE9_P2",          # R1IN  <- DE9 pin 2 (RXD)
    ("U1", "14"): "DE9_P3",          # T1OUT -> DE9 pin 3 (TXD)
    ("U1", "15"): "GND",  ("U1", "16"): "+3V3",
    # pins 7-10 (channel 2) deliberately unconnected - the captured download
    # was plain 3-wire and T2IN must not be left driven by nothing.
    ("C1", "1"): "C1P",     ("C1", "2"): "C1N",
    ("C2", "1"): "C2P",     ("C2", "2"): "C2N",
    ("C3", "1"): "V_PLUS",  ("C3", "2"): "GND",
    ("C4", "1"): "V_MINUS", ("C4", "2"): "GND",
    ("C5", "1"): "+3V3",    ("C5", "2"): "GND",
    # --- DE9, straight-through DTE (cable pinout confirmed) ---------------
    ("J2", "2"): "DE9_P2", ("J2", "3"): "DE9_P3", ("J2", "5"): "GND",
    ("J2", "SH"): "GND",
    # pins 1,4,6,7,8,9 unconnected. If FUNCTION SEL (J101-E) turns out to be
    # needed, tack a wire from U1 pin 7 to the DE9 pin-4 leg - both are
    # accessible on a built board, so this is rework, not a respin.
}

NOTES = [
    (20, 30, "HGS Download Stick - RS-232 carrier for Waveshare ESP32-S3-Touch-LCD-1.9 (SKU 30939)"),
    (20, 35, "Pico-format: Module:RaspberryPi_Pico_Common_THT, 2.54mm pitch, 17.78mm rows, 20 pins/row."),
    (20, 40, "Module PCB 52.60 x 29.00mm; bezel 55.00 x 31.40mm overhangs ~1.2mm/side. M2 holes 40.75 x 25.00mm."),
    (20, 45, "MAX3232 section after mtguerreiro/pcbs (BSD-3-Clause) - see carrier/upstream/."),
    (20, 160, "DO NOT use header pins 1/2 (IO43/IO44 = UART0): the ROM bootloader prints its"),
    (20, 165, "115200 banner there at power-up and it would be injected straight into the DAU."),
    (20, 172, "Cable is a standard DTE port: TXD=DE9 pin3, RXD=DE9 pin2, GND=DE9 pin5. Wired straight through."),
    (20, 179, "MAX3232 VCC from 3V3 ONLY - the ESP32-S3 is not 5V tolerant."),
    (20, 186, "Channel 2 (pins 7-10) unused. FUNCTION SEL (J101-E) unresolved; if needed, rework"),
    (20, 191, "a wire from U1 pin 7 to the DE9 pin 4 leg rather than respinning."),
]


def sym_instance(ref, lib_id, value, x, y, footprint):
    u = uid("sym:" + ref)
    p = PINS[lib_id]
    out = ['  (symbol (lib_id "%s") (at %.2f %.2f 0) (unit 1)' % (lib_id, x, y),
           '    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
           '    (uuid "%s")' % u,
           '    (property "Reference" "%s" (at %.2f %.2f 0)' % (ref, x, y - 12),
           '      (effects (font (size 1.27 1.27))))',
           '    (property "Value" "%s" (at %.2f %.2f 0)' % (value, x, y + 12),
           '      (effects (font (size 1.27 1.27))))',
           '    (property "Footprint" "%s" (at %.2f %.2f 0)' % (footprint, x, y),
           '      (effects (font (size 1.27 1.27)) hide))']
    for num in sorted(p, key=lambda k: (len(k), k)):
        out.append('    (pin "%s" (uuid "%s"))' % (num, uid("pin:%s:%s" % (ref, num))))
    out.append('    (instances (project "%s" (path "/%s"' % (PROJECT, uid("root")))
    out.append('      (reference "%s") (unit 1))))' % ref)
    out.append('  )')
    return "\n".join(out)


def label_at(x, y, name, rot=0):
    return ('  (label "%s" (at %.2f %.2f %d)\n'
            '    (effects (font (size 1.27 1.27)) (justify left bottom))\n'
            '    (uuid "%s"))' % (name, x, y, rot, uid("lbl:%s:%.2f:%.2f" % (name, x, y))))


parts = ['(kicad_sch (version 20250610) (generator "hgs_gen") (generator_version "10.0")',
         '  (uuid "%s")' % uid("root"),
         '  (paper "A3")',
         '  (lib_symbols']
for lid, blk in LIBS.items():
    if lid.startswith(PROJECT + ":"):
        body = blk.replace('(symbol "ESP32-S3-Touch-LCD-1.9"',
                           '(symbol "%s:ESP32-S3-Touch-LCD-1.9"' % PROJECT, 1)
        parts.append(body)
    else:
        lib, nm = lid.split(":")
        # Only the outer symbol takes the lib: prefix - the _0_1 / _1_1 unit
        # sub-symbols keep the bare name, as KiCad itself writes them.
        parts.append(blk.replace('(symbol "%s"' % nm, '(symbol "%s"' % lid, 1))
parts.append('  )')

placed = {}
for ref, lid, val, x, y, fp in PLACE:
    parts.append(sym_instance(ref, lid, val, x, y, fp))
    placed[ref] = (lid, x, y)

# One real power symbol per rail so ERC sees the net as driven; every other
# connection to the rail is by name, and KiCad merges nets by name.
for ref, lid, val, x, y, fp in [("#PWR01", "power:GND", "GND", 100, 150, ""),
                                ("#PWR02", "power:+3V3", "+3V3", 100, 60, ""),
                                # GND is all power_in pins, so it needs an
                                # explicit flag or ERC calls it undriven.
                                ("#FLG01", "power:PWR_FLAG", "PWR_FLAG", 115, 150, "")]:
    parts.append(sym_instance(ref, lid, val, x, y, fp))
    placed[ref] = (lid, x, y)
    NETS[(ref, "1")] = "GND" if val in ("GND", "PWR_FLAG") else "+3V3"

# Labels dropped exactly on each pin's connection point.
missing = []
for (ref, pin), net in sorted(NETS.items()):
    if ref not in placed:
        missing.append((ref, pin)); continue
    lid, sx, sy = placed[ref]
    if pin not in PINS[lid]:
        missing.append((ref, pin)); continue
    px, py, _ = PINS[lid][pin]
    parts.append(label_at(sx + px, sy - py, net))   # schematic Y is inverted
if missing:
    raise SystemExit("pins not found: %s" % missing)

# Every pin this carrier genuinely does not use gets an explicit no-connect.
# Without them KiCad reports each as an ERC *error*, which buries any real one.
for ref, (lid, sx, sy) in sorted(placed.items()):
    if ref.startswith("#PWR"):
        continue
    for pin, (px, py, _nm) in PINS[lid].items():
        if (ref, pin) in NETS:
            continue
        parts.append('  (no_connect (at %.2f %.2f) (uuid "%s"))'
                     % (sx + px, sy - py, uid("nc:%s:%s" % (ref, pin))))

for x, y, txt in NOTES:
    parts.append('  (text "%s" (at %.2f %.2f 0)\n'
                 '    (effects (font (size 1.27 1.27)) (justify left))\n'
                 '    (uuid "%s"))' % (txt.replace('"', "'"), x, y, uid("txt:%.1f:%.1f" % (x, y))))

parts.append('  (sheet_instances (path "/" (page "1")))')
parts.append(')')

path = os.path.join(OUT_DIR, PROJECT + ".kicad_sch")
open(path, "w", encoding="utf-8").write("\n".join(parts) + "\n")
print("wrote", path)
print("symbols:", len(PLACE) + 2, " labelled pins:", len(NETS),
      " nets:", len(set(NETS.values())))
