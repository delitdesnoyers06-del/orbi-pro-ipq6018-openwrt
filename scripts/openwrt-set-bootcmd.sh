#!/usr/bin/env bash
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
# Point the vendor U-Boot at the OpenWrt UBI in slot B, save the env, and boot it.
#
#   DEV=sxs30|sxr30 scripts/openwrt-set-bootcmd.sh [--no-reset]
#
# The env keeps the stock boot sequence in `stockboot`, so the rollback is one command:
#     setenv bootcmd 'run stockboot'; saveenv
# and the stock system (slot A) is never modified.
#
# Numbers per board (only the slot-B window changes):
#   sxs30: 0x4b00000@0x6600000   (U-Boot `mtdparts`, UBI spans the whole firmware2 partition)
#   sxr30: 0x6d00000@0x8800000
#
# The U-Boot prompt has a watchdog: long command lists with multi-second gaps make the box reset
# between commands, and each reset eats the first character of the next line. Keep the list short.
set -u
: "${WORKDIR:=$PWD}"
cd "$WORKDIR"   # working dir that holds work/ and dumps/ (override with WORKDIR=...)
DEV="${DEV:-sxs30}"
PORT="${UART_PORT:-/dev/ttyUSB0}"
TARGET="${ORBI_TARGET_IP:-192.168.1.1}"
case "$DEV" in
  sxs30) MTPARTS='mtdparts=nand0:0x4b00000@0x6600000(rootfs)' ;;
  sxr30) MTPARTS='mtdparts=nand0:0x6d00000@0x8800000(rootfs)' ;;
  *) echo "DEV must be sxs30 or sxr30"; exit 2 ;;
esac

CMDS="setenv stockboot 'mii write 0x01 0x0 0x800; sleep 2; nmrp; bootdni; boot_DNI_secureboot'@@"
CMDS="${CMDS}setenv mtdids nand0=nand0@@"
CMDS="${CMDS}setenv mtdparts '$MTPARTS'@@"
CMDS="${CMDS}setenv openwrt_boot 'nand set_partition_offset 0; ubi part rootfs; ubi read 0x44000000 kernel; bootm 0x44000000'@@"
CMDS="${CMDS}setenv bootargs console=ttyMSM0,115200n8@@"
CMDS="${CMDS}setenv bootcmd 'run openwrt_boot; run stockboot'@@"
CMDS="${CMDS}printenv bootcmd mtdparts openwrt_boot@@"
CMDS="${CMDS}saveenv"
[ "${1:-}" = "--no-reset" ] || CMDS="${CMDS}@@reset"

pgrep -f "capture.py $PORT" >/dev/null 2>&1 || bash scripts/start-capture.sh 3600 "$PORT" >/dev/null 2>&1

: > "logs/openwrt-setboot-$DEV.log"
KEY="${ORBI_SSH_KEY:-$HOME/.ssh/id_ed25519}"
reboot_ssh() {
  ssh -q -i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o BatchMode=yes -o ConnectTimeout=5 "root@$TARGET" \
      'export PATH=/sbin:/usr/sbin:/bin:/usr/bin; sync; /sbin/reboot' 2>/dev/null
}
reboot_telnet() {
  python3 scripts/tcmd.py 'export PATH=/sbin:/usr/sbin:/bin:/usr/bin; sync; /sbin/reboot' 8 "$TARGET" >/dev/null 2>&1
}

if reboot_ssh; then
  echo "[set-bootcmd] rebooted over ssh (OpenWrt target)"
  python3 scripts/uboot.py --port "$PORT" --reboot no --wait 150 --gap 2 --sep '@@' --cmds "$CMDS" --no-boot \
    > "logs/openwrt-setboot-$DEV.log" 2>&1 || true
elif python3 scripts/tcmd.py true 8 "$TARGET" >/dev/null 2>&1; then
  echo "[set-bootcmd] device has a telnet shell -> arming the key-spammer, then rebooting it"
  python3 scripts/uboot.py --port "$PORT" --reboot no --wait 150 --gap 2 --sep '@@' --cmds "$CMDS" --no-boot \
    > "logs/openwrt-setboot-$DEV.log" 2>&1 &
  SPAM=$!
  sleep 3
  reboot_telnet || true
  wait "$SPAM" || true
else
  echo "[set-bootcmd] no telnet -> assuming the console sits at the U-Boot prompt"
  python3 scripts/uboot.py --port "$PORT" --reboot no --assume-prompt --gap 2 --sep '@@' --cmds "$CMDS" --no-boot \
    > "logs/openwrt-setboot-$DEV.log" 2>&1 || true
fi
echo "=== key lines ==="
grep -aE "bootcmd=|mtdparts=|openwrt_boot=|stockboot=|Saving Environment|Writing to NAND|PROMPT|prompt NOT" \
  "logs/openwrt-setboot-$DEV.log" | tail -20
