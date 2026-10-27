#!/usr/bin/env bash
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
# Quick status: is the Orbi on the network, is a shell available?
# Note: the image has no telnetd since 2026-10-02 - SSH :22 is the normal path, telnetd :2323 only
# exists if scripts/net-shell.sh started it by hand.
set -u
DIR="${WORKDIR:-$PWD}"   # working dir that holds work/ and dumps/
TARGET="${ORBI_TARGET_IP:-192.168.1.1}"
SSH_PORT="${ORBI_SSH_PORT:-22}"
TELNET_PORT="${ORBI_TCP_PORT:-2323}"
KEY="${ORBI_SSH_KEY:-$HOME/.ssh/id_ed25519}"
echo "target: $TARGET (ssh $SSH_PORT, telnet $TELNET_PORT)"
if ping -c 2 -W 2 "$TARGET" > /dev/null 2>&1; then echo "ping: OK"; else echo "ping: FAIL"; fi
port_state() {
  python3 - "$TARGET" "$1" <<'PY'
import socket, sys
try:
    s = socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=3); s.close()
    print("open")
except Exception:
    print("closed")
PY
}
if [ "$(port_state "$SSH_PORT")" = "open" ]; then
  if ssh -q -i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
     -o BatchMode=yes -o ConnectTimeout=6 "root@$TARGET" 'echo ok' > /dev/null 2>&1; then
    echo "ssh shell: OK (key $KEY)"
  else
    echo "ssh shell: port open but key auth FAILED"
  fi
else
  echo "ssh shell: FAIL (port closed)"
fi
case "$(port_state "$TELNET_PORT")" in
  open)   echo "telnet shell: open (passwordless root - lab only)";;
  closed) echo "telnet shell: closed (expected: removed from the image 2026-10-02)";;
esac
L="$(cat "$DIR/logs/.current" 2>/dev/null || true)"
if [ -n "$L" ]; then echo "uart log: $L ($(wc -c < "$L") bytes)"; else echo "uart log: none"; fi
pgrep -f 'capture.py' > /dev/null && echo "uart capture: running" || echo "uart capture: stopped"
