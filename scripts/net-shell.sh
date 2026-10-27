#!/usr/bin/env bash
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
# Bring up a passwordless root shell on the Orbi over the LAN (busybox telnetd, port 2323).
# Runs the commands over the UART console, because the telnet shell does not exist yet.
set -u
DIR="${WORKDIR:-$PWD}"   # working dir that holds work/ and dumps/
python3 "$DIR/scripts/console_cmd.py" 'mkdir -p /dev/pts; mknod -m 666 /dev/ptmx c 5 2 2>/dev/null; echo 1 > /tmp/enable_telnet; /usr/sbin/utelnetd -d -i br-lan 2>/dev/null; telnetd -l /bin/sh -p 2323; sleep 1; netstat -ltn | grep -E ":(23|2323) "'
echo
python3 "$DIR/scripts/status.sh" 2>/dev/null || true
