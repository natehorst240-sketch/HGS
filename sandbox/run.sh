#!/usr/bin/env bash
# Run a Windows .exe in its sandbox, with its COM1 tapped and/or its activity traced.
#
#   sandbox/run.sh [--name NAME] --tap /dev/ttyUSB0 [--baud 9600] PROGRAM.exe [args]  # real adapter, log everything
#   sandbox/run.sh [--name NAME] --sim [--file X.HG6] [--pace] PROGRAM.exe [args]     # no hardware: dau_sim.py plays the DAU
#       --pace streams records at real 9600-baud timing (a full file takes ~10 min) instead of instantly
#   sandbox/run.sh [--name NAME] --trace PROGRAM.exe [args]                           # what does it touch? files/registry/DLLs/ports
#   sandbox/run.sh [--name NAME] PROGRAM.exe [args]                                   # plain Wine
#   --wireshark with --tap/--sim opens Wireshark live (HGS decode: sandbox/wireshark/hgs.lua).
#   For a terminal view instead, in another shell:  sandbox/sniff.py sandbox/logs/<timestamp>.log
#
# --name picks the prefix (~/.NAME_sandbox, default hgs). --trace writes
# sandbox/logs/<timestamp>.trace and prints a summary (sandbox/tracesum.py)
# of every file, registry key, DLL and COM port the program used: the map of
# what a native rewrite has to replace. Serial logs go to sandbox/logs/<timestamp>.log
# (decode_capture.py-compatible) and <timestamp>.pcapng (Wireshark).
# Env: WINEPREFIX overrides the prefix, WINEDEBUG (default -all; try +comm for Wine's serial layer).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)

NAME="hgs"; TAP=""; SIM=0; BAUD=9600; FILE=""; WS=0; TRACE=0; PACE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    --tap)  TAP="$2"; shift 2 ;;
    --sim)  SIM=1; shift ;;
    --baud) BAUD="$2"; shift 2 ;;
    --file) FILE="$2"; shift 2 ;;
    --wireshark) WS=1; shift ;;
    --pace) PACE="--pace"; shift ;;
    --trace) TRACE=1; shift ;;
    -h|--help) sed -n 2,16p "$0"; exit 0 ;;
    *) break ;;
  esac
done
[ $# -ge 1 ] || { echo "usage: $0 [--name NAME] [--tap DEV | --sim] [--trace] PROGRAM.exe [args]" >&2; exit 2; }
EXE="$1"; shift
[ -f "$EXE" ] || { echo "no such file: $EXE" >&2; exit 1; }
export WINEPREFIX="${WINEPREFIX:-$HOME/.${NAME}_sandbox}"
[ -d "$WINEPREFIX" ] || { echo "no sandbox at $WINEPREFIX - run sandbox/setup.sh --name $NAME first" >&2; exit 1; }
export WINEDEBUG="${WINEDEBUG:--all}"

mkdir -p "$HERE/logs"
STAMP=$(date +%Y%m%d_%H%M%S)
LOG="$HERE/logs/$STAMP.log"
PCAP="$HERE/logs/$STAMP.pcapng"
TRACEFILE="$HERE/logs/$STAMP.trace"
PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; rm -f "$HERE"/logs/.live_*.fifo; }
trap cleanup EXIT

if [ "$WS" = 1 ]; then
  command -v wireshark >/dev/null || { echo "wireshark not installed" >&2; exit 1; }
  [ -n "$TAP" ] || [ "$SIM" = 1 ] || { echo "--wireshark needs --tap or --sim" >&2; exit 1; }
  if [ ! -r /usr/bin/dumpcap ] || ! id -nG | tr ' ' '\n' | grep -qx wireshark; then
    echo "NOTE: live capture needs your user in the 'wireshark' group:  sudo usermod -aG wireshark $USER  (then open a new terminal)"
  fi
  PCAP="$HERE/logs/.live_$STAMP.fifo"
  mkfifo "$PCAP"
  wireshark -X "lua_script:$HERE/wireshark/hgs.lua" -k -i "$PCAP" >/dev/null 2>&1 &
  PIDS+=($!)
  echo "wireshark started on $PCAP (frames are buffered until it opens the pipe)"
fi

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
  python3 "$HERE/dau_sim.py" "$(cat "$PEER")" ${FILE:+--file "$FILE"} --baud "$BAUD" $PACE &
  PIDS+=($!)
  echo "simulated DAU on $(cat "$PEER"); log -> $LOG"
fi

echo "starting: wine $EXE $*   (sandbox $NAME)"
# Run from the exe's own folder: MFC apps expect their .ini/.dat beside them.
cd "$(dirname "$EXE")"
if [ "$TRACE" = 1 ]; then
  echo "tracing to $TRACEFILE (this slows the program down a little)"
  WINEDEBUG="+file,+reg,+loaddll,+comm" wine "./$(basename "$EXE")" "$@" 2>"$TRACEFILE" || echo "wine exited with status $?"
  python3 "$HERE/tracesum.py" "$TRACEFILE"
else
  wine "./$(basename "$EXE")" "$@" || echo "wine exited with status $?"
fi
