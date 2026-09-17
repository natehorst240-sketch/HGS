"""Parser for HGS binary download files (.HG1-.HG7 / .HG6).

Reverse-engineered from a real A109 download (22366_260707_A1.HG6). A single
file bundles several sections:

  1. PARAMETER CATALOG — exceedance / fault / AFCS parameter dictionary.
       record = 25-byte ASCII label (space-padded) + event fields + a
       16-bit big-endian sequence/record ID immediately before the next
       label. Record lengths vary per block (110 / 92 bytes) so we parse
       by scanning for labels rather than assuming a fixed stride.

       When the parameter's event OCCURRED, the record carries data
       (verified against the original app's Fault Log "ALL EVENTS
       DETECTED" display, which listed exactly the entries found here):
         label+25 .. +30 : first occurrence, BCD YY MM DD HH MM SS
         end-22  .. -17  : last occurrence, BCD (same layout)
         end-6           : occurrence count (BCD)
         end-2  .. -1    : sequence ID (big-endian uint16)
       Zero-filled fields mean the event never occurred.

  2. MARKERS         — literal "CUMULATIVE LOG" text separating blocks.

  3. TIME HISTORY    — N frames, 2817 bytes each, header "TIME HISTORY #NNN".
       Each frame holds 90 samples of 31 bytes. EVERY field is BCD
       (verified value-for-value against the original app's display):
         bytes  0-5  : timestamp  YY MM DD HH MM SS  (1 Hz)
         byte   6    : status/flag (0 in normal ops)
         bytes  7-8  : N1  eng1, 4 digits, /10  -> "88.2" %
         bytes  9-10 : N1  eng2
         bytes 11-12 : N2  eng1, integer %
         bytes 13-14 : N2  eng2
         bytes 15-16 : TRQ eng1, integer %
         bytes 17-18 : TRQ eng2
         bytes 19-20 : TOT eng1, integer degC
         bytes 21-22 : TOT eng2
         bytes 23-24 : NR, integer %
         bytes 25-27 : CLP eng1, 6 digits, /100 -> "59.89" %
         bytes 28-30 : CLP eng2
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

SAMPLE_LEN = 31
TH_HEADER_LEN = 25
FRAME_LEN = 2817
FRAME_MARKER = b"TIME HISTORY #"
TAIL_MARKER = bytes([0x00, 0x59, 0x89])

# Column order matches the original app's Time History Log Display.
TH_COLUMNS = (
    "Time",
    "N1 1 (%)", "N2 1 (%)", "TRQ 1 (%)", "TOT 1 (degC)", "CLP 1 (%)",
    "N1 2 (%)", "N2 2 (%)", "TRQ 2 (%)", "TOT 2 (degC)", "CLP 2 (%)",
    "NR (%)",
)


def _bcd(b: int) -> int:
    return (b >> 4) * 10 + (b & 0x0F)


def _bcd_int(bs: bytes) -> int:
    """Multi-byte BCD to integer: b'\\x07\\x75' -> 775."""
    v = 0
    for b in bs:
        v = v * 100 + _bcd(b)
    return v


def _ts(sample: bytes) -> str:
    yy, mm, dd, hh, mi, ss = (_bcd(sample[i]) for i in range(6))
    return f"20{yy:02d}-{mm:02d}-{dd:02d} {hh:02d}:{mi:02d}:{ss:02d}"


FAULT_COLUMNS = ("Event", "First Occurrence", "Last Occurrence", "Count")

# Power Assurance: stored fields only. The app's "TOT Calc" / "N1 Calc"
# columns are computed at display time from its PA model, not stored.
PA_COLUMNS = (
    "Time", "OAT (degC)", "Pa (feet)", "IAS (Kts)",
    "N2 1 (%)", "TRQ 1 (%)", "TOT 1 Act (degC)", "N1 1 Act (%)",
    "IDLE 1", "MAN 1",
    "N2 2 (%)", "TRQ 2 (%)", "TOT 2 Act (degC)", "N1 2 Act (%)",
    "IDLE 2", "MAN 2",
)

CUM_COLUMNS = ("Item", "Value")


@dataclass
class Hg6:
    counters: list[tuple[str, int]] = field(default_factory=list)
    faults: list[list[str]] = field(default_factory=list)
    afcs_faults: list[list[str]] = field(default_factory=list)
    cumulative: list[list[str]] = field(default_factory=list)
    power_assurance: list[list[str]] = field(default_factory=list)
    time_history: list[list[str]] = field(default_factory=list)
    frame_count: int = 0


def _is_label(data: bytes, o: int) -> bool:
    seg = data[o:o + TH_HEADER_LEN]
    if len(seg) < TH_HEADER_LEN:
        return False
    if not all(0x20 <= c <= 0x7E for c in seg):
        return False
    if not (seg[0:1] == b"#" or 48 <= seg[0] <= 57 or 65 <= seg[0] <= 90):
        return False
    return sum(65 <= c <= 90 for c in seg) >= 3


def _trailing_spaces(data: bytes, o: int) -> int:
    seg = data[o:o + TH_HEADER_LEN]
    return len(seg) - len(seg.rstrip(b" "))


def _scan_labels(data: bytes, end: int) -> list[int]:
    """Label offsets in [0, end), skipping ahead past each accepted label so
    shifted substrings of the same label aren't double-counted.

    A printable byte in the preceding record's sequence ID can make a window
    look like a label one byte early (e.g. seq byte 0x49 -> 'I2 AP TEST FAIL').
    When adjacent windows both qualify, the correctly aligned one has more
    trailing space padding — prefer it."""
    out = []
    o = 0
    while o < end:
        if _is_label(data, o):
            while (o + 1 < end and _is_label(data, o + 1)
                   and _trailing_spaces(data, o + 1) > _trailing_spaces(data, o)):
                o += 1
            out.append(o)
            o += TH_HEADER_LEN
        else:
            o += 1
    return out


def _bcd_ts_ok(ts: bytes) -> bool:
    if len(ts) < 6 or not any(ts):
        return False
    try:
        yy, mm, dd, hh, mi, ss = (_bcd(ts[i]) for i in range(6))
    except Exception:
        return False
    return 20 <= yy <= 40 and 1 <= mm <= 12 and 1 <= dd <= 31 \
        and hh <= 23 and mi <= 59 and ss <= 59


def parse_catalog(data: bytes, end: int) -> tuple[
        list[tuple[str, int]], list[list[str]], list[list[str]]]:
    """Parse the parameter catalog: (label, seq id) entries plus event rows
    for every parameter whose occurrence fields are populated."""
    labels = _scan_labels(data, end)
    counters: list[tuple[str, int]] = []
    faults: list[list[str]] = []
    afcs: list[list[str]] = []
    for i, o in enumerate(labels):
        label = data[o:o + TH_HEADER_LEN].decode("latin-1").strip()
        if label.startswith("TIME HISTORY") or label.startswith("CUMULATIVE"):
            continue
        nxt = labels[i + 1] if i + 1 < len(labels) else end
        seq = 0
        if nxt - 2 >= o + TH_HEADER_LEN:
            seq = struct.unpack(">H", data[nxt - 2:nxt])[0]
        counters.append((label, seq))

        ts1 = data[o + TH_HEADER_LEN:o + TH_HEADER_LEN + 6]
        if _bcd_ts_ok(ts1):
            ts2 = data[nxt - 22:nxt - 16]
            count = _bcd(data[nxt - 6]) if nxt - 6 > o + TH_HEADER_LEN else 0
            row = [label, _ts(ts1),
                   _ts(ts2) if _bcd_ts_ok(ts2) else "",
                   str(count)]
            # AFCS fault entries carry "FAIL CODE" in the label
            (afcs if "FAIL CODE" in label else faults).append(row)
    return counters, faults, afcs


def parse_time_history(data: bytes) -> tuple[list[list[str]], int]:
    frames = [m.start() for m in re.finditer(re.escape(FRAME_MARKER) + rb"\d{3}", data)]
    rows: list[list[str]] = []
    for fstart in frames:
        base = fstart + TH_HEADER_LEN
        # walk 31-byte samples until the frame's byte budget is used or the
        # next frame marker / a non-plausible timestamp is hit.
        limit = min(fstart + FRAME_LEN, len(data))
        off = base
        while off + SAMPLE_LEN <= limit:
            s = data[off:off + SAMPLE_LEN]
            # a valid sample has a BCD-plausible timestamp
            if not _plausible_ts(s):
                break
            rows.append([
                _ts(s),
                f"{_bcd_int(s[7:9]) / 10:.1f}",    # N1 1
                str(_bcd_int(s[11:13])),           # N2 1
                str(_bcd_int(s[15:17])),           # TRQ 1
                str(_bcd_int(s[19:21])),           # TOT 1
                f"{_bcd_int(s[25:28]) / 100:.2f}", # CLP 1
                f"{_bcd_int(s[9:11]) / 10:.1f}",   # N1 2
                str(_bcd_int(s[13:15])),           # N2 2
                str(_bcd_int(s[17:19])),           # TRQ 2
                str(_bcd_int(s[21:23])),           # TOT 2
                f"{_bcd_int(s[28:31]) / 100:.2f}", # CLP 2
                str(_bcd_int(s[23:25])),           # NR
            ])
            off += SAMPLE_LEN
    return rows, len(frames)


def _plausible_ts(s: bytes) -> bool:
    try:
        mm, dd, hh, mi, ss = (_bcd(s[i]) for i in range(1, 6))
    except Exception:
        return False
    return 1 <= mm <= 12 and 1 <= dd <= 31 and hh <= 23 and mi <= 59 and ss <= 59


def _hhmm(bs: bytes) -> str:
    """4-byte BCD running-time counter: 00 47 85 38 -> '04785:38'."""
    digits = "".join(f"{b >> 4}{b & 15}" for b in bs)
    return f"{int(digits[:-2]):05d}:{digits[-2:]}"


def _hms(bs: bytes) -> str:
    return f"{_bcd(bs[0]):02d}:{_bcd(bs[1]):02d}:{_bcd(bs[2]):02d}"


def parse_cumulative(data: bytes) -> list[list[str]]:
    """Cumulative Log block: 'CUMULATIVE LOG' label + fixed header, then four
    component blocks (main xmsn, tail xmsn, engine 1, engine 2) anchored on
    their ASCII serial numbers, then total chip-burner activations."""
    o = data.find(b"CUMULATIVE LOG")
    if o == -1:
        return []
    th = data.find(FRAME_MARKER, o)
    blk = data[o:th if th != -1 else len(data)]
    rows: list[list[str]] = []
    p = TH_HEADER_LEN
    date = f"20{_bcd(blk[p]):02d}-{_bcd(blk[p+1]):02d}-{_bcd(blk[p+2]):02d}"
    time = _hms(blk[p + 4:p + 7])            # byte p+3: unknown (channel?)
    rows.append(["Cumulative Data", f"{date} {time}"])
    rows.append(["Dau Batt. Install Date",
                 f"20{_bcd(blk[p+8]):02d}-{_bcd(blk[p+9]):02d}-{_bcd(blk[p+10]):02d}"])
    rows.append(["Aircraft S/N", blk[p + 11:p + 16].decode("latin-1")])
    rows.append(["Most Recent Flight Start", _hms(blk[p + 16:p + 19])])
    rows.append(["Most Recent Flight Stop", _hms(blk[p + 19:p + 22])])
    rows.append(["Most Recent Flight Time",
                 f"{_bcd(blk[p+22]):02d}:{_bcd(blk[p+23]):02d}"])
    rows.append(["Total Flight Time", _hhmm(blk[p + 24:p + 28])])
    rows.append(["Number of Flights", str(_bcd_int(blk[p + 28:p + 31]))])
    rows.append(["Chip Burner Activations", str(_bcd_int(blk[-4:-2]))])

    # Component blocks at fixed offsets from the label (verified against the
    # app's Cumulative Log Display; single-sample layout — revisit if another
    # download shifts). S/N field is 7 chars for transmissions, 6 for engines.
    # 23-byte transmission blocks, 59-byte engine blocks
    blocks = (("Main Transmission", 56, 7), ("Tail Transmission", 79, 7),
              ("Engine 1", 102, 6), ("Engine 2", 161, 6))
    for i, (name, ao, snlen) in enumerate(blocks):
        nxt = blocks[i + 1][1] if i + 1 < len(blocks) else len(blk) - 4
        rows.append([f"{name} S/N",
                     blk[ao:ao + snlen].decode("latin-1").strip()])
        q = ao + snlen
        rows.append([f"{name} TBO", str(_bcd_int(blk[q:q + 2]))])
        rows.append([f"{name} TSN", _hhmm(blk[q + 2:q + 6])])
        if name.startswith("Engine"):
            # Running time is a 4-byte BCD counter after the TSO field; locate
            # it as first nonzero byte minus one (leading byte may be 00).
            r = q + 10
            while r < nxt and blk[r] == 0:
                r += 1
            r -= 1
            rows.append([f"{name} Running Time", _hhmm(blk[r:r + 4])])
            # Fixed ladder from the running-time field (verified vs the app):
            # +4: 5 pad/OEI bytes, chip(1), startup(3), shutdown(3), pad(3),
            # LIM(2), training(3), EECU P/N(6), cycle counts(3x3)
            c = r + 4 + 5
            rows.append([f"{name} Chip D.A.", str(_bcd(blk[c]))])
            rows.append([f"{name} Start-up", _hms(blk[c + 1:c + 4])])
            rows.append([f"{name} Shutdown", _hms(blk[c + 4:c + 7])])
            rows.append([f"{name} LIM ON Activations",
                         str(_bcd_int(blk[c + 10:c + 12]))])
            rows.append([f"{name} Training Activations",
                         str(_bcd_int(blk[c + 12:c + 15]))])
            # 12 BCD digits with a leading pad zero: 010029042104 -> 1002904-2-104
            ecu = "".join(f"{b>>4}{b&15}" for b in blk[c + 15:c + 21])[1:]
            rows.append([f"{name} EECU P/N",
                         f"{ecu[0:7]}-{ecu[7]}-{ecu[8:11]}"])
            rows.append([f"{name} Compr.Turbine C.Counts",
                         str(_bcd_int(blk[c + 21:c + 24]))])
            rows.append([f"{name} Pwr Turbine C.Counts",
                         str(_bcd_int(blk[c + 24:c + 27]))])
            rows.append([f"{name} Imp.Turbine C.Counts",
                         str(_bcd_int(blk[c + 27:c + 30]))])
        else:
            # Transmissions: chip detector D.A. is the last nonzero BCD pair.
            chip = 0
            for k in range(nxt - 2, q + 6, -1):
                if blk[k] or blk[k + 1]:
                    chip = _bcd_int(blk[k:k + 2])
                    break
            rows.append([f"{name} Cumulative Chip D.A.", str(chip)])
    return rows


def parse_power_assurance(data: bytes) -> list[list[str]]:
    """Power Assurance records live in a tail section after the last time
    history frame: 'POWER ASSURANCE LOG' label + 34-byte records."""
    o = data.find(b"POWER ASSURANCE LOG")
    if o == -1:
        return []
    # 34-byte record: ts(6) OAT(3) Pa(3) N2x2(4) TRQx2(4) TOTx2(4)
    # N1x2(4, /10) IAS(2) IDLE1 IDLE2 MAN1 MAN2 -- all BCD.
    def onoff(b: int) -> str:
        return "ON" if b else "OFF"

    rows: list[list[str]] = []
    p = o + TH_HEADER_LEN
    while p + 34 <= len(data) and _bcd_ts_ok(data[p:p + 6]):
        s = data[p:p + 34]
        rows.append([
            _ts(s),
            str(_bcd_int(s[6:9])),                # OAT
            str(_bcd_int(s[9:12])),               # Pa
            str(_bcd_int(s[28:30])),              # IAS
            str(_bcd_int(s[12:14])),              # N2 1
            str(_bcd_int(s[16:18])),              # TRQ 1
            str(_bcd_int(s[20:22])),              # TOT 1 Act
            f"{_bcd_int(s[24:26]) / 10:.1f}",     # N1 1 Act
            onoff(s[30]), onoff(s[32]),           # IDLE 1, MAN 1
            str(_bcd_int(s[14:16])),              # N2 2
            str(_bcd_int(s[18:20])),              # TRQ 2
            str(_bcd_int(s[22:24])),              # TOT 2 Act
            f"{_bcd_int(s[26:28]) / 10:.1f}",     # N1 2 Act
            onoff(s[31]), onoff(s[33]),           # IDLE 2, MAN 2
        ])
        p += 34
    return rows


def parse(data: bytes) -> Hg6:
    th_start = data.find(FRAME_MARKER)
    catalog_end = th_start if th_start != -1 else len(data)
    counters, faults, afcs = parse_catalog(data, catalog_end)
    th_rows, nframes = parse_time_history(data) if th_start != -1 else ([], 0)
    return Hg6(counters=counters, faults=faults, afcs_faults=afcs,
               cumulative=parse_cumulative(data),
               power_assurance=parse_power_assurance(data),
               time_history=th_rows, frame_count=nframes)


def parse_file(path: str) -> Hg6:
    with open(path, "rb") as fh:
        return parse(fh.read())
