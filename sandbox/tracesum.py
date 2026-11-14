#!/usr/bin/env python3
"""Summarise a Wine trace (run.sh --trace) into what the program actually uses.

Reads a file produced with WINEDEBUG=+file,+reg,+loaddll,+comm and prints
unique: DLLs/OCXs loaded (native vs Wine builtin), files opened or created
(with the program's own files separated from Windows system paths), registry
keys read/written, and serial-port activity. That list is the inventory a
Linux rewrite has to cover: config files, data files, settings keys, hardware.

    tracesum.py sandbox/logs/20261114_101500.trace [--all]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, OrderedDict

LSTR = re.compile(r'L"((?:[^"\\]|\\.)*)"')
LOADED = re.compile(r"trace:loaddll:\S+ Loaded (L\"(?:[^\"\\]|\\.)*\") at \S+: (\w+)")
CREATEFILE = re.compile(r"trace:file:(?:CreateFileW|NtCreateFile|open_file)\S* .*?(L\"(?:[^\"\\]|\\.)*\")")
REG = re.compile(r"trace:reg:(Reg\w+|Nt\w+Key\w*|Nt\w+Value\w*)\b.*?(L\"(?:[^\"\\]|\\.)*\")")
COMM = re.compile(r"trace:comm:(\w+)")
SKIP_FILE = re.compile(r"^(C:\\windows|\\\\\?\?\\C:\\windows|Z:\\usr|Z:\\lib|Z:\\etc|\\\\\?\?\\Z:)", re.I)
NOISE_KEYS = re.compile(r"(Software\\Wine|CurrentControlSet\\Control\\(Nls|Session Manager|Class)|Microsoft\\Windows NT\\CurrentVersion\\FontSubstitutes|Classes\\CLSID\\{)", re.I)


def unq(s: str) -> str:
    return s[2:-1].replace('\\\\', '\\')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--all", action="store_true", help="include Windows-system paths and Wine-internal keys")
    args = ap.parse_args()

    dlls: "OrderedDict[str, str]" = OrderedDict()
    files: Counter = Counter()
    keys: Counter = Counter()
    comm: Counter = Counter()
    with open(args.trace, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            m = LOADED.search(ln)
            if m:
                dlls.setdefault(unq(m.group(1)), m.group(2))
                continue
            m = CREATEFILE.search(ln)
            if m:
                files[unq(m.group(1))] += 1
                continue
            m = REG.search(ln)
            if m:
                keys[unq(m.group(2))] += 1
                continue
            m = COMM.search(ln)
            if m:
                comm[m.group(1)] += 1

    def show(title, items):
        print(f"\n## {title} ({len(items)})")
        for k, v in items:
            print(f"  {v:>5}  {k}" if isinstance(v, int) else f"  {v:<8} {k}")

    native = [(p, k) for p, k in dlls.items() if k == "native"]
    builtin = [(p, k) for p, k in dlls.items() if k != "native"]
    show("Native DLL/OCX loaded (must ship with the program)", native)
    if args.all:
        show("Wine builtin DLLs used", builtin)
    else:
        print(f"\n## Wine builtin DLLs used: {len(builtin)} (--all to list)")

    prog = [(p, n) for p, n in files.most_common() if args.all or not SKIP_FILE.match(p)]
    show("Files opened (program's own, by open count)", prog)
    if not args.all:
        print(f"   ({sum(1 for p in files if SKIP_FILE.match(p))} Windows/system paths hidden; --all to list)")

    ks = [(k, n) for k, n in keys.most_common() if args.all or not NOISE_KEYS.search(k)]
    show("Registry keys touched (by access count)", ks)
    if not args.all:
        print(f"   ({sum(1 for k in keys if NOISE_KEYS.search(k))} Wine-internal/system keys hidden; --all to list)")

    show("Serial port calls", comm.most_common())
    if not comm:
        print("  none - the program did not use a COM port in this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
