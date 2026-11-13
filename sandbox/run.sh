#!/usr/bin/env bash
# Run a Windows .exe in the sandbox with its COM1 tapped.
#
#   sandbox/run.sh --tap /dev/ttyUSB0 [--baud 9600] PROGRAM.exe [args]   # real adapter, log everything
#   sandbox/run.sh --sim [--file X.HG6] PROGRAM.exe [args]               # no hardware: dau_sim.py plays the DAU
#   sandbox/run.sh PROGRAM.exe [args]                                    # plain Wine, whatever com1 already points at
#   add --wireshark to either tapped mode to open Wireshark live on the serial stream
#   (HGS decode: sandbox/wireshark/hgs.lua). For a terminal view instead, in another
#   shell:  sandbox/sniff.py sandbox/logs/<timestamp>.log
#
# Logs go to sandbox/logs/<timestamp>.log (decode_capture.py-compatible) and
# <timestamp>.pcapng (Wireshark).
# Env: WINEPREFIX (default ~/.hgs_sandbox), WINEDEBUG (default -all; try +comm to see Wine's serial layer).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
export WINEPREFIX="${WINEPREFIX:-$HOME/.hgs_sandbox}"
export WINEDEBUG="${WINEDEBUG:--all}"

TAP=""; SIM=0; BAUD=9600; FILE=""; WS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tap)  TAP="$2"; shift 2 ;;
    --sim)  SIM=1; shift ;;
    --baud) BAUD="$2"; shift 2 ;;
    --file) FILE="$2"; shift 2 ;;
    --wireshark) WS=1; shift ;;
    -h|--help) sed -n 2,10p "$0"; exit 0 ;;
    *) break ;;
  esac
done
[ $# -ge 1 ] || { echo "usage: $0 [--tap DEV | --sim] PROGRAM.exe [args]" >&2; exit 2; }
EXE="$1"; shift
[ -f "$EXE" ] || { echo "no such file: $EXE" >&2; exit 1; }
[ -d "$WINEPREFIX" ] || { echo "no sandbox at $WINEPREFIX - run sandbox/setup.sh first" >&2; exit 1; }

mkdir -p "$HERE/logs"
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="$HERE/logs/$STAMP.log"
PCAP="$HERE/logs/$STAMP.pcapng"
PIDS=()
if [ "$WS" = 1 ]; then
  command -v wireshark >/dev/null || { echo "wireshark not installed" >&2; exit 1; }
  [ -n "$TAP" ] || [ "$SIM" = 1 ] || { echo "--wireshark needs --tap or --sim" >&2; exit 1; }
  PCAP="$HERE/logs/.live_$STAMP.fifo"
  mkfifo "$PCAP"
  if [ ! -r /usr/bin/dumpcap ] || ! id -nG | tr ' ' '\n' | grep -qx wireshark; then
    echo "NOTE: live capture needs your user in the 'wireshark' group:  sudo usermod -aG wireshark $USER  (then open a new terminal)"
  fi
  wireshark -X "lua_script:$HERE/wireshark/hgs.lua" -k -i "$PCAP" >/dev/null 2>&1 &
  PIDS+=($!)
  echo "wireshark started on $PCAP (frames are buffered until it opens the pipe)"
fi
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; rm -f "$HERE"/logs/.live_*.fifo; }
trap cleanup EXIT

if [ -n "$TAP" ]; then
  python3 "$HERE/serialtap.py" --real "$TAP" --baud "$BAUD" --log "$LOG" --pcap "$PCAP" &
  PIDS+=($!)
  sleep 0.5
  echo "tap running; log -> $LOG"
elif [ "$SIM" = 1 ]; then
  PEER="$HERE/logs/.peer"
  rm -f "$PEER"
  python3 "$HERE/serialtap.py" --virtual --peer-file "$PEER" --log "$LOG" --pcap "$PCAP" &
  PIDS+=($!)
  for _ in $(seq 1 50); do [ -s "$PEER" ] && break; sleep 0.1; done
  [ -s "$PEER" ] || { echo "serialtap did not come up" >&2; exit 1; }
  python3 "$HERE/dau_sim.py" "$(cat "$PEER")" ${FILE:+--file "$FILE"} --baud "$BAUD" &
  PIDS+=($!)
  echo "simulated DAU on $(cat "$PEER"); log -> $LOG"
fi

echo "starting: wine $EXE $*"
# Run from the exe's own folder: MFC apps expect their .ini/.dat beside them.
cd "$(dirname "$EXE")"
wine "./$(basename "$EXE")" "$@" || echo "wine exited with status $?"
