#!/usr/bin/env bash
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
# Start a background UART capture.
# Usage: start-capture.sh [seconds] [port]   (defaults: 900 /dev/ttyUSB0)
# Stop early: touch <log>.stop
set -u
DIR="${WORKDIR:-$PWD}"   # working dir that holds work/ and dumps/
SECS="$1"
if [ -z "$SECS" ]; then SECS=900; fi
PORT="$2"
if [ -z "$PORT" ]; then PORT=/dev/ttyUSB0; fi
TS="$(date +%Y%m%d-%H%M%S)"
SAFE="$(basename "$PORT")"
LOG="$DIR/logs/$SAFE-$TS.log"

if [ ! -e "$PORT" ]; then echo "ERROR: $PORT missing (adapter unplugged?)"; exit 1; fi
chmod +x "$DIR/scripts/capture.py" 2>/dev/null

# refuse to run if something else (screen/minicom/...) still owns the port
HOLDER="$(fuser "$PORT" 2>/dev/null | tr -d ' \n')"
if [ -n "$HOLDER" ]; then echo "ERROR: $PORT is busy (pids: $HOLDER) - close screen/minicom first"; exit 1; fi

if ! stty -F "$PORT" 115200 cs8 -cstopb -parenb -crtscts -ixon -ixoff raw -echo; then
  echo "ERROR: stty failed on $PORT"; exit 1
fi

rm -f "$LOG.stop"
printf '%s\n' "$LOG" > "$DIR/logs/.current"
printf '%s\n' "$PORT" > "$DIR/logs/.current-port"
setsid nohup python3 "$DIR/scripts/capture.py" "$PORT" "$LOG" "$SECS" > "$DIR/logs/capture.out" 2>&1 < /dev/null &
sleep 2
echo "port=$PORT"
echo "log=$LOG"
echo "--- capture.out ---"
cat "$DIR/logs/capture.out"
echo "--- pid ---"
pgrep -f "capture.py $PORT" | tr '\n' ' '
echo
