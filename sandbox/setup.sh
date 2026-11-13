#!/usr/bin/env bash
# Build a 32-bit Wine sandbox for a legacy Windows serial program (HGS by default).
#
#   sandbox/setup.sh [--exe reverse/Hgs_cpp.exe] [--ocx /path/MSCOMM32.OCX] [--com1 /dev/ttyUSB0]
#
# Env: WINEPREFIX (default ~/.hgs_sandbox), WINVER (default winxp).
# Re-runnable. Needs 32-bit Wine installed (Debian/Ubuntu: `sudo dpkg --add-architecture i386 &&
# sudo apt update && sudo apt install wine32 wine`; Fedora: `sudo dnf install wine`).
set -euo pipefail

EXE=""; OCX=""; COM1=""
while [ $# -gt 0 ]; do
  case "$1" in
    --exe)  EXE="$2"; shift 2 ;;
    --ocx)  OCX="$2"; shift 2 ;;
    --com1) COM1="$2"; shift 2 ;;
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

export WINEPREFIX="${WINEPREFIX:-$HOME/.hgs_sandbox}"
export WINEARCH=win32
export WINEDEBUG="${WINEDEBUG:--all}"
WINVER="${WINVER:-winxp}"

command -v wine >/dev/null || { echo "wine not found - install wine (with 32-bit support) first" >&2; exit 1; }
echo "wine: $(wine --version)"

if [ -d "$WINEPREFIX" ] && [ -f "$WINEPREFIX/system.reg" ]; then
  if ! grep -q '#arch=win32' "$WINEPREFIX/system.reg"; then
    echo "ERROR: $WINEPREFIX exists but is not a win32 prefix. Pick another WINEPREFIX." >&2; exit 1
  fi
  echo "reusing prefix $WINEPREFIX"
else
  echo "creating win32 prefix at $WINEPREFIX ..."
  wineboot -u >/dev/null 2>&1
fi

# Windows version the program sees (MFC-era apps are happiest on winxp).
wine winecfg -v "$WINVER" >/dev/null 2>&1 || echo "warning: could not set Windows version to $WINVER"

# Serial permissions: Wine opens the tty as your user, so you need the device's group.
if [ -n "$COM1" ]; then
  if [ ! -e "$COM1" ]; then
    echo "warning: $COM1 does not exist right now (adapter unplugged?) - symlink created anyway"
  else
    grp=$(stat -c %G "$COM1")
    if ! id -nG | tr ' ' '\n' | grep -qx "$grp"; then
      echo "NOTE: $COM1 is group '$grp' and you are not in it:  sudo usermod -aG $grp $USER  (then log out/in)"
    fi
  fi
  mkdir -p "$WINEPREFIX/dosdevices"
  ln -sfn "$COM1" "$WINEPREFIX/dosdevices/com1"
  echo "com1 -> $COM1"
fi

# MSCOMM32.OCX: HGS drives the serial port through this ActiveX control, which is
# NOT in the repo (Microsoft-licensed; take it from the original HGS install
# media / the Windows machine's system32 or the HGS Bin folder).
if [ -n "$OCX" ]; then
  [ -f "$OCX" ] || { echo "no such file: $OCX" >&2; exit 1; }
  cp -f "$OCX" "$WINEPREFIX/drive_c/windows/system32/MSCOMM32.OCX"
  if wine regsvr32 /s 'C:\windows\system32\MSCOMM32.OCX'; then
    echo "MSCOMM32.OCX registered"
  else
    echo "warning: regsvr32 MSCOMM32.OCX failed - the program will report no COM port" >&2
  fi
fi

# Install the program into the sandbox's C: drive.
if [ -n "$EXE" ]; then
  [ -f "$EXE" ] || { echo "no such file: $EXE" >&2; exit 1; }
  name=$(basename "$EXE" .exe); name=${name%.EXE}
  dest="$WINEPREFIX/drive_c/Program Files/$name"
  mkdir -p "$dest"
  cp -f "$EXE" "$dest/"
  echo "installed -> $dest/$(basename "$EXE")"
  echo "run it:   sandbox/run.sh --tap ${COM1:-/dev/ttyUSB0} \"$dest/$(basename "$EXE")\""
fi

echo "done. WINEPREFIX=$WINEPREFIX"
