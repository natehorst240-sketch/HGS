#!/usr/bin/env bash
# Build a 32-bit Wine sandbox for a legacy Windows program. One prefix per program.
#
#   sandbox/setup.sh --name NAME [--exe PROG.exe | --dir "C:/Program Files/Prog"] \
#                    [--ocx X.OCX ...] [--dll Y.DLL ...] [--com1 /dev/ttyUSB0]
#
#   --name  sandbox name; prefix is ~/.NAME_sandbox (default: hgs -> ~/.hgs_sandbox)
#   --exe   copy just this exe into the prefix's C:\Program Files\NAME\
#   --dir   copy a whole install folder (settings/data beside the exe) into it
#   --ocx   copy an ActiveX control into system32 and register it (repeatable)
#   --dll   copy a native DLL into system32, e.g. MFC40.DLL from /mnt/c/Windows/SysWOW64 (repeatable)
#   --com1  what the program's COM1 is (a real adapter); omit when using run.sh --tap/--sim
#
# Env: WINEPREFIX overrides the prefix path, WINVER (default winxp).
# Re-runnable. Needs 32-bit Wine (Debian/Ubuntu: `sudo dpkg --add-architecture i386 &&
# sudo apt update && sudo apt install wine wine32`).
#
# Checklist for a new program: find its install folder on the Windows side
# (/mnt/c/Program Files (x86)/... under WSL), note every .OCX/.DLL that ships
# with it, run setup with --dir and those --ocx/--dll, then run.sh --trace to
# see what else it loads or opens and add those too.
set -euo pipefail

NAME="hgs"; EXE=""; DIR=""; OCX=(); DLL=(); COM1=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --exe)  EXE="$2"; shift 2 ;;
    --dir)  DIR="$2"; shift 2 ;;
    --ocx)  OCX+=("$2"); shift 2 ;;
    --dll)  DLL+=("$2"); shift 2 ;;
    --com1) COM1="$2"; shift 2 ;;
    -h|--help) sed -n 2,19p "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

export WINEPREFIX="${WINEPREFIX:-$HOME/.${NAME}_sandbox}"
export WINEARCH=win32
export WINEDEBUG="${WINEDEBUG:--all}"
WINVER="${WINVER:-winxp}"

command -v wine >/dev/null || { echo "wine not found - install wine (with 32-bit support) first" >&2; exit 1; }
echo "wine: $(wine --version)   sandbox: $NAME   prefix: $WINEPREFIX"

if [ -d "$WINEPREFIX" ] && [ -f "$WINEPREFIX/system.reg" ]; then
  if ! grep -q '#arch=win32' "$WINEPREFIX/system.reg"; then
    echo "ERROR: $WINEPREFIX exists but is not a win32 prefix. Pick another --name/WINEPREFIX." >&2; exit 1
  fi
  echo "reusing prefix"
else
  echo "creating win32 prefix ..."
  wineboot -u >/dev/null 2>&1
fi

# Windows version the program sees (MFC-era apps are happiest on winxp).
wine winecfg -v "$WINVER" >/dev/null 2>&1 || echo "warning: could not set Windows version to $WINVER"

# Pin COM1 so Wine's own port detection can't steal it. Wine rebuilds every
# dosdevices/comN link at start-up from /dev/ttyS*, /dev/ttyUSB*, ... (on WSL
# that maps com1 -> root-owned /dev/ttyS0 = "Permission denied"), but a value
# COM1 under HKLM\Software\Wine\Ports overrides detection for that number.
# We point it at a stable link inside the prefix that --com1 or serialtap.py
# retargets at the real device / the tap's pty each run.
STABLE="$WINEPREFIX/com1.serial"
wine reg add 'HKLM\Software\Wine\Ports' /v COM1 /t REG_SZ /d "$STABLE" /f >/dev/null 2>&1 \
  && echo "COM1 pinned to $STABLE (HKLM\\Software\\Wine\\Ports)" \
  || echo "warning: could not write HKLM\\Software\\Wine\\Ports\\COM1"

if [ -n "$COM1" ]; then
  if [ ! -e "$COM1" ]; then
    echo "warning: $COM1 does not exist right now (adapter unplugged?) - link created anyway"
  else
    grp=$(stat -c %G "$COM1")
    if ! id -nG | tr ' ' '\n' | grep -qx "$grp"; then
      echo "NOTE: $COM1 is group '$grp' and you are not in it:  sudo usermod -aG $grp $USER  (then log out/in)"
    fi
  fi
  ln -sfn "$COM1" "$STABLE"
  mkdir -p "$WINEPREFIX/dosdevices"
  ln -sfn "$STABLE" "$WINEPREFIX/dosdevices/com1"
  echo "com1 -> $STABLE -> $COM1"
fi

SYS32="$WINEPREFIX/drive_c/windows/system32"
for f in "${DLL[@]:-}"; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || { echo "no such file: $f" >&2; exit 1; }
  cp -f "$f" "$SYS32/$(basename "$f")"
  echo "dll  -> system32/$(basename "$f")"
done
for f in "${OCX[@]:-}"; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || { echo "no such file: $f" >&2; exit 1; }
  b=$(basename "$f")
  cp -f "$f" "$SYS32/$b"
  if wine regsvr32 /s "C:\\windows\\system32\\$b" 2>/dev/null; then
    echo "ocx  -> system32/$b registered"
  else
    echo "warning: regsvr32 $b failed - try WINEDEBUG=+loaddll wine regsvr32 'C:\\windows\\system32\\$b' to see the missing import (often an MFC/VB runtime: --dll it from /mnt/c/Windows/SysWOW64)" >&2
  fi
done

DEST="$WINEPREFIX/drive_c/Program Files/$NAME"
if [ -n "$DIR" ]; then
  [ -d "$DIR" ] || { echo "no such folder: $DIR" >&2; exit 1; }
  mkdir -p "$DEST"
  cp -r "$DIR/." "$DEST/"
  echo "installed folder -> $DEST"
  exe=$(find "$DEST" -maxdepth 2 -iname '*.exe' | head -1)
  [ -n "$exe" ] && echo "run it:   sandbox/run.sh --name $NAME --sim|--tap DEV|--trace \"$exe\""
elif [ -n "$EXE" ]; then
  [ -f "$EXE" ] || { echo "no such file: $EXE" >&2; exit 1; }
  mkdir -p "$DEST"
  cp -f "$EXE" "$DEST/"
  echo "installed -> $DEST/$(basename "$EXE")"
  echo "run it:   sandbox/run.sh --name $NAME --sim|--tap DEV|--trace \"$DEST/$(basename "$EXE")\""
fi

# Port mapping is read when the prefix boots, so make sure the next run starts fresh.
wineserver -k 2>/dev/null || true
echo "done. WINEPREFIX=$WINEPREFIX"
