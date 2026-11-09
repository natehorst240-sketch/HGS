# HGS-Linux

A Linux/cross-platform re-implementation of the **Agusta A109S / A109N HGS**
ground-station software (`Hgs_cpp.exe`, MFC-era Windows app) that reads IDS/DAU
downloads from the aircraft.

## Status

The `.HG*` download file format has been **reverse-engineered and verified
value-for-value against the original application** (see [FORMAT.md](FORMAT.md)):

| Section | Status |
|---------|--------|
| Parameter catalog (exceedance/fault dictionary) | decoded |
| Fault Log (first/last occurrence, count) | decoded, 16/16 events verified |
| AFCS Fault Log | decoded |
| Cumulative Log (flights, TSN/TBO, cycle counts, chip D.A., ...) | decoded, 43/43 fields verified |
| Power Assurance Log | decoded, record verified (stored fields; app-side "Calc" columns are computed, not stored) |
| Time History (1 Hz N1/N2/TRQ/TOT/CLP/NR) | decoded, verified |
| Exceedance *event* records (Max Peak/Duration) | layout unknown — need a download containing a real exceedance |
| IDS Status Log | not present in sample |
| **Live serial download protocol (9600,n,8,1)** | **fully reverse-engineered from a live capture — see reverse/PROTOCOL.md** |

## Serial protocol — DONE

Captured live from a real A109 download and validated: 25-byte space-padded
ASCII messages, stop-and-wait (downloader sends `DOWNLOAD LOGS`, DAU streams
each `.HG` record, downloader acks each with `TRANSMISSION OK`). Concatenated
records == the `.HG` file. The stick firmware (`firmware/dau_protocol.py`) is a
complete, real implementation — replayed against the captured frames it
reassembles the download byte-for-byte (589,237 bytes, exact match). Spec in
`reverse/PROTOCOL.md`; capture tools in `reverse/frida/`.

Key encoding facts: everything numeric is **BCD**; labels are 25-byte
space-padded ASCII; sequence IDs are the only plain big-endian uint16s.

## Layout

- `hgs/hg6.py` — the download-file parser (the important part)
- `hgs/ui.py` — PySide6 viewer with the original app's seven Data View tabs
- `hgs/protocol.py` — serial download state-machine skeleton (`TODO(protocol)`)
- `hgs/config.py` — INI config replacing the original's registry keys
- `FORMAT.md` — byte-level file-format specification
- `sandbox/` — Wine sandbox for the original `.exe` on Linux: `setup.sh`, `run.sh --tap /dev/ttyUSB0` or `--sim` (serial tap + DAU simulator, `--wireshark` live), `sniff.py` terminal sniffer, `wireshark/hgs.lua` dissector, `selftest.py`
- `sample-data/` — a real download (S/N 22366) + decoded CSV exports

## Run (Linux)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m hgs        # File -> Open -> sample-data/22366_260707_A1.HG6
```

Parsing works headless too:

```python
from hgs import hg6
p = hg6.parse_file("sample-data/22366_260707_A1.HG6")
print(p.cumulative, p.faults, len(p.time_history))
```
