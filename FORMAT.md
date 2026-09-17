# HGS `.HG6` file format (reverse-engineered)

Derived from a real A109 download: `22366_260707_A1.HG6` (590,117 bytes).
Filename pattern: `<serial>_<YYMMDD>_<id>.HG<n>` where `.HGn` selects the log type.

A single file concatenates several sections in this order:

## 1. Parameter catalog  (offset 0x0000 .. first "TIME HISTORY")
Exceedance / fault / AFCS parameter dictionary. Each record:

| field | size | notes |
|-------|------|-------|
| label | 25 bytes | ASCII, space-padded (e.g. `#1 HOT START - A`, `XMSN OIL HOT`) |
| pad   | varies | 0x00 fill |
| seq id | 2 bytes | **big-endian** uint16, immediately before the next label |

Record stride varies by parameter block (110 bytes for exceedance params,
92 for discrete events), so parse by scanning for labels — not a fixed stride.
206 parameters in the sample.

**The trailing uint16 is a sequence/record ID, not an event count.** Verified
against the original Windows app: it reports "NO EXCEEDINGS ARE AVAILABLE" for
this same file even though these values are populated (and they increment
sequentially: HOT START A/B/C = 1243/1244/1245, TOT A/B/C = 1017/1018/1019).

### Event occurrence fields (faults / AFCS faults)
When a parameter's event OCCURRED, its catalog record carries data (decoded
list verified to match the app's Fault Log "ALL EVENTS DETECTED" display
exactly — 16/16 events):

| position (rel. to record) | field | encoding |
|---------------------------|-------|----------|
| label+25 .. +30 | first occurrence | BCD `YY MM DD HH MM SS` |
| end-22 .. -17   | last occurrence  | BCD (zero if single/ongoing) |
| end-6           | occurrence count | BCD |
| end-2 .. -1     | sequence ID      | big-endian uint16 |

Zero-filled fields = event never occurred. AFCS fault entries are the records
whose labels contain `FAIL CODE nnn`; they use the same layout. A one-byte-
early label misdetection is possible when the preceding sequence ID's low
byte is printable ASCII — resolve by preferring the alignment with more
trailing space padding.

### Exceedance *event* records (confirmed vs DAU CMM 109090076 Rev E)
When a parameter exceedance occurred, its 110-byte record carries **four event
slots + summary** (per the CMM "Exceedance Log" table). Each event slot (~19
bytes, seen at rel offsets 25 / 44 / 63 / 82 = first / second / third / most-
recent) contains:
- Event **Date/Time** — BCD YY MM DD HH MM SS
- **Duration** of the exceedance (2 bytes)  [scaling: verify]
- **Peak value** — highest value during the exceedance (2 bytes)  [scaling: verify]
- **Start-of-flight Date/Time** — BCD YY MM DD HH MM SS
- **LIMITER ON status**
Then a summary: **number of occurrences**, **total duration**, **max peak value**
(all "since last download"), and the seq id at 108-109.

Verified against a real AIRSPEED exceedance (2026-07-10): event time 02:50:19,
start-of-flight 02:44:06, occurrences=1 (first == most-recent, as expected for
a single event). Exact Duration/Peak scaling still needs the HGS *tabular*
exceedance display (the summary preview only lists which events fired).

The 85 exceedance types are defined in the CMM (TOT areas A–D, N1/N2/overtorque
areas A–C, XMSN overtorque C/F, NR high/low, AIRSPEED).

### IDS Status Log (format per CMM; bytes not yet captured)
Date/Time/Zone-stamped **snapshots of fault + exceedance status**, kept ~1 hour,
uniquely **not cleared after download**. Matches the HGS display. Status records
stream at the *start* of a download, so a mid-stream capture misses them — need
a capture that begins before the download starts to get the byte layout.

### Confirmed from the CMM
- **CLP = Collective Pitch** (a real control-input trace, unlike governed NR).
- **No attitude/bank angle is recorded** — "ATTD" appears only as the discrete
  "ATTD OFF" AP status flag, never as an angle. Time history is engine/rotor
  only; the DAU does not log attitude.

## 2. Cumulative Log  (label `CUMULATIVE LOG`, 228 bytes, all fields verified 43/43 vs the app)
25-byte label, then (offsets relative to label start):

| rel | field | encoding |
|-----|-------|----------|
| 25-27 | date | BCD YY MM DD |
| 28 | unknown (0x01 — DAU channel?) | |
| 29-31 | time | BCD HH MM SS |
| 33-35 | DAU battery install date | BCD YY MM DD |
| 36-40 | aircraft S/N | 5 ASCII |
| 41-43 / 44-46 | most recent flight start / stop | BCD HH MM SS |
| 47-48 | most recent flight time | BCD HH MM |
| 49-52 | total flight time | 4-byte BCD, last 2 digits = minutes (`00 34 97 29` → 03497:29) |
| 53-55 | number of flights | BCD |
| file: last 4 bytes of block | chip burner activations (2 BCD) + seq uint16 | |

Then four component blocks — Main XMSN @56, Tail XMSN @79 (23 bytes each,
S/N 7 ASCII), Engine 1 @102, Engine 2 @161 (59 bytes each, S/N 6 ASCII):

- Transmissions: S/N, TBO (2 BCD), TSN (4 BCD hours:min), TSO (4), pad,
  cumulative chip D.A. (2 BCD) at block end.
- Engines: S/N, TBO, TSN, TSO, then running time (4 BCD; leading byte may be
  00 — locate first nonzero minus one), +9: chip D.A. (1), start-up (3 BCD
  HH MM SS), shutdown (3), pad (3), LIM ON activations (2), training
  activations (3), EECU P/N (6 BCD, 12 digits, drop leading 0 →
  `1002904-2-104`), Compr/Pwr/Imp turbine cycle counts (3 BCD each).

## 3. Time History  (bulk of the file)
`N` frames, **2817 bytes each** (200 frames in the sample). Each frame:

- Header: `TIME HISTORY #NNN` padded to **25 bytes**.
- Then 90 **samples of 31 bytes** each. **Every field is BCD** — verified
  value-for-value against the original app's Time History Log Display:

| bytes | field | encoding | example |
|-------|-------|----------|---------|
| 0-5   | timestamp | BCD `YY MM DD HH MM SS`, 1 Hz | `26 07 05 14 05 39` → 2026-07-05 14:05:39 |
| 6     | flag | binary, 0 in normal ops | |
| 7-8   | N1 Eng1 | 4 BCD digits ÷10, % | `08 82` → 88.2 |
| 9-10  | N1 Eng2 | " | `08 84` → 88.4 |
| 11-12 | N2 Eng1 | 4 BCD digits, % | `01 00` → 100 |
| 13-14 | N2 Eng2 | " | |
| 15-16 | TRQ Eng1 | 4 BCD digits, % | `00 53` → 53 |
| 17-18 | TRQ Eng2 | " | |
| 19-20 | TOT Eng1 | 4 BCD digits, °C | `07 75` → 775 |
| 21-22 | TOT Eng2 | " | |
| 23-24 | NR | 4 BCD digits, % | `00 99` → 99 |
| 25-27 | CLP Eng1 | 6 BCD digits ÷100, % | `00 59 89` → 59.89 |
| 28-30 | CLP Eng2 | " | |

(The `00 59 89` bytes previously mistaken for a frame marker are the CLP
columns, constant at 59.89 % throughout this particular download.)

## 4. Power Assurance Log  (tail section, after the last time-history frame)
Label `POWER ASSURANCE LOG` (25 bytes) + N consecutive 34-byte records
(record 1 verified field-for-field vs the app), zero padding, then a final
uint16 at file end. All BCD:

| bytes | field |
|-------|-------|
| 0-5   | timestamp YY MM DD HH MM SS |
| 6-8   | OAT °C |
| 9-11  | Pa feet |
| 12-13 / 14-15 | N2 eng1 / eng2, % |
| 16-17 / 18-19 | TRQ eng1 / eng2, % |
| 20-21 / 22-23 | TOT Act eng1 / eng2, °C |
| 24-25 / 26-27 | N1 Act eng1 / eng2, 4 digits ÷10 % |
| 28-29 | IAS kts |
| 30/31 | IDLE status eng1/eng2 (01=ON) |
| 32/33 | MAN status eng1/eng2 |

The app's "TOT Calc"/"N1 Calc" columns are NOT stored — the app computes them
from its power-assurance model at display time (shows `#No Value!#` when the
engine wasn't in a valid check state). Negative-OAT encoding unobserved.

## Encoding summary
- Numeric fields: **BCD**, big-endian digit order.
- Labels: ASCII, 25-byte fixed field, space-padded.
- Parameter-catalog sequence IDs: plain big-endian uint16 (the one non-BCD
  numeric field observed).
