#!/usr/bin/env bash
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
# Install an OpenWrt UBI image into NAND slot B **from the vendor system, over telnet**.
#
#   openwrt-install-telnet.sh [DEV] [TARGET_IP]
#     DEV        sxs30 | sxr30  (default sxr30) - picks work/openwrt/build/openwrt-<DEV>.ubi
#     TARGET_IP  vendor system on the LAN (default $ORBI_TARGET_IP)
#
# Why telnet: the stock vendor rootfs has no dropbear (/sbin/ssh absent, :22 closed), so the old
# ssh-based installer cannot be used.  The console gives us a passwordless root shell and we start
# busybox `telnetd -l /bin/sh -p 2323` (see scripts/net-shell.sh); all transfers are then
# **host-initiated**, which is what makes this work behind the workstation's ufw.
#
# Safety properties:
#   * writes ONLY mtd25 ("firmware2", slot B).  Slot A, 0:ART, boarddata, 0:APPSBL* are untouched.
#   * the original slot-B content is in dumps(-<dev>)/mtd25-firmware2.bin for a byte-exact restore.
#   * image sha256 is verified twice: after the push, and again by reading NAND back.
#   * bootcmd is NOT touched here - do that afterwards (scripts/openwrt-set-bootcmd.sh).
set -u
: "${WORKDIR:=$PWD}"
cd "$WORKDIR"   # working dir that holds work/ and dumps/ (override with WORKDIR=...)
DEV="${1:-sxr30}"
TARGET="${2:-${ORBI_TARGET_IP:-192.168.1.1}}"
UBI="work/openwrt/build/openwrt-$DEV.ubi"
MTC=25

[ -s "$UBI" ] || { echo "missing $UBI (run DEV=$DEV scripts/openwrt-build-image.sh)"; exit 1; }
SIZE=$(stat -c%s "$UBI")
BLKS=$(( (SIZE + 131071) / 131072 ))
SHA=$(sha256sum "$UBI" | cut -d' ' -f1)
export ORBI_TARGET_IP="$TARGET"
echo "image  $UBI : $SIZE bytes = $BLKS x 128 KiB blocks"
echo "sha256 $SHA"
echo "target $TARGET :2323  ->  /dev/mtd$MTC (firmware2 / slot B)"

t() { python3 scripts/tcmd.py "$1" "${2:-20}" "$TARGET"; }

echo "[0/5] reachability"
if ! t 'true' 10 >/dev/null 2>&1; then
  echo "    no telnet shell on $TARGET:2323 - arm it from the console:"
  echo "    bash scripts/net-shell.sh            # (needs the UART console, sends ^C first)"
  exit 1
fi
t 'uname -a; cat /proc/mtd | sed -n "s/^mtd'"$MTC"':/mtd'"$MTC"':/p"'

echo "[1/5] push image to /tmp (base64 over the pty)"
python3 scripts/push_b64.py "$UBI" "/tmp/openwrt-$DEV.ubi" "$TARGET" 2323 | tail -4
GOT=$(t "sha256sum /tmp/openwrt-$DEV.ubi" 60 | grep -oE '\b[0-9a-f]{64}\b' | head -1)
[ "$GOT" = "$SHA" ] || { echo "PUSH VERIFY FAILED (got $GOT)"; exit 1; }
echo "    push verified"

echo "[2/5] erase slot B (mtd$MTC, $(( (0x6d00000) / 1048576 )) MiB max) - this takes a few minutes"
t "flash_erase /dev/mtd$MTC 0 0 >/dev/null 2>&1; echo ERASE_RC=\$?" 900

echo "[3/5] write $BLKS blocks"
t "nandwrite -p /dev/mtd$MTC /tmp/openwrt-$DEV.ubi >/dev/null 2>&1; echo WRITE_RC=\$?" 900

echo "[4/5] read back and verify"
# the pty echoes/wraps the command, so pick the 64-hex-digit token instead of field 1
GOT=$(t "dd if=/dev/mtd$MTC bs=131072 count=$BLKS 2>/dev/null | head -c $SIZE | sha256sum" 900 \
        | grep -oE '\b[0-9a-f]{64}\b' | head -1)
echo "    expected $SHA"
echo "    got      $GOT"
if [ "$GOT" != "$SHA" ]; then echo "VERIFY FAILED - do NOT set bootcmd; slot B is not what we wrote"; exit 1; fi
echo "VERIFY OK"

echo "[5/5] clean up"
t "rm -f /tmp/openwrt-$DEV.ubi; sync; echo CLEANUP_OK" 60
echo
echo "next: set the U-Boot env and boot it:"
echo "  DEV=$DEV bash scripts/openwrt-set-bootcmd.sh     # or do it by hand at the IPQ6018# prompt"
