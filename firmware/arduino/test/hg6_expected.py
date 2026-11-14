#!/usr/bin/env python3
"""Reference output for hg6_test: the Python parser's view of a download, in
the same line format the C++ test prints, so `diff` is the verdict."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hgs.hg6 import parse_file  # noqa: E402

h = parse_file(sys.argv[1])
print("params", len(h.counters))
for r in h.cumulative:
    print("cum|%s|%s" % (r[0], r[1]))
for r in h.faults:
    print("fault|%s|%s|%s|%s" % tuple(r))
for r in h.afcs_faults:
    print("afcs|%s|%s|%s|%s" % tuple(r))
for r in h.power_assurance:
    print("pa|" + "|".join(r))
th = h.time_history
print("th frames=%d samples=%d first=%s last=%s" % (
    h.frame_count, len(th), th[0][0] if th else "", th[-1][0] if th else ""))
