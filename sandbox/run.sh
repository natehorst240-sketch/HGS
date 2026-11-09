#!/usr/bin/env bash
# Run a Windows .exe in the sandbox with its COM1 tapped.
#
#   sandbox/run.sh --tap /dev/ttyUSB0 [--baud 9600] PROGRAM.exe [args]   # real adapter, log everything
#   sandbox/run.sh --sim [--file X.HG6] PROGRAM.exe [args]               # no hardware: dau_sim.py plays the DAU
#   sandbox/run.sh PROGRAM.exe [args]                                    # plain Wine, whatever com1 already points at
#
# Logs go to sandbox/logs/<timestamp>.log (decode_capture.py-compatible).
# Env: WINEPREFIX (default ~/.hgs_sandbox), WINEDEBUG (default -all; try +comm to see Wine's serial layer).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
export WINEPREFIX="${WINEPREFIX:-$HOME/.hgs_sandbox}"
export WINEDEBUG="${WINEDEBUG:--all}"

TAP=""; SIM=0; BAUD=9600; FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tap)  TAP="$2"; shift 2 ;;
    --sim)  SIM=1; shift ;;
    --baud) BAUD="$2"; shift 2 ;;
    --file) FILE="$2"; shift 2 ;;
    -h|--help) sed -n 2,10p "$0"; exit 0 ;;
    *) break ;;
  esac
done
[ $# -ge 1 ] || { echo "usage: $0 [--tap DEV | --sim] PROGRAM.exe [args]" >&2; exit 2; }
EXE="$1"; shift
[ -f "$EXE" ] || { echo "no such file: $EXE" >&2; exit 1; }
[ -d "$WINEPREFIX" ] || { echo "no sandbox at $WINEPREFIX - run sandbox/setup.sh first" >&2; exit 1; }

mkdir -p "$HERE/logs"
LOG="$HERE/logs/$(date +%Y%m%d_%H%M%S).log"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

if [ -n "$TAP" ]; then
  python3 "$HERE/serialtap.py" --real "$TAP" --baud "$BAUD" --log "$LOG" &
  PIDS+=($!)
  sleep 0.5
  echo "tap running; log -> $LOG"
elif [ "$SIM" = 1 ]; then
  PEER="$HERE/logs/.peer"
  rm -f "$PEER"
  python3 "$HERE/serialtap.py" --virtual --peer-file "$PEER" --log "$LOG" &
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
