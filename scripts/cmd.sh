#!/usr/bin/env bash
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
# Send a command to the captured console and print only the new output.
# Usage: cmd.sh "command" [wait-seconds] [port]
# Empty command = just press Enter. Multi-line: pass \\n in the argument.
set -u
DIR="${WORKDIR:-$PWD}"   # working dir that holds work/ and dumps/
CMD="${1-}"
WAIT="${2:-3}"
PORT="${3:-}"
if [ -z "$PORT" ]; then
  PORT="$(cat "$DIR/logs/.current-port" 2>/dev/null || echo /dev/ttyUSB0)"
fi
LOG="$(cat "$DIR/logs/.current")"

BEFORE=$(wc -c < "$LOG")
stty -F "$PORT" -hupcl 2>/dev/null
python3 "$DIR/scripts/send.py" "$PORT" "$CMD" 0.3
sleep "$WAIT"
AFTER=$(wc -c < "$LOG")
if [ "$AFTER" -le "$BEFORE" ]; then
  echo "[cmd.sh] no new output (${WAIT}s)"
else
  tail -c "+$((BEFORE + 1))" "$LOG" | tr -d '\r'
fi
