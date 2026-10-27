#!/usr/bin/env bash
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
# Build a bootable OpenWrt image set for a Netgear Orbi Pro "IPQ6018 starling" board
# (SXS30 satellite / SXR30 router) that boots under the *vendor* U-Boot:
#   1. custom DTB   - fixed NAND partitions incl. a slot-B "rootfs" UBI partition, because the
#                     vendor SMEM table has no rootfs and CONFIG_MTD_CMDLINE_PARTS is off in the
#                     OpenWrt qualcommax kernel (so mtdparts= is silently ignored)
#   2. kernel FIT   - upstream OpenWrt ipq60xx kernel (rbs350 == rbr350 kernel, byte identical)
#                     + the custom DTB, booted with a plain `bootm` (no signature check involved)
#   3. UBI image    - volumes kernel / rootfs / rootfs_data, to be written into slot B
#
# Usage:
#   DEV=sxs30 scripts/openwrt-build-image.sh     # 256 MiB NAND, slot B = 0x6600000, 75 MiB
#   DEV=sxr30 scripts/openwrt-build-image.sh     # 512 MiB NAND, slot B = 0x8800000, 109 MiB
#
# Outputs in work/openwrt/build/: <dev>.dtb, openwrt-<dev>.itb, openwrt-<dev>.ubi, SHA256SUMS.
# Needs: dtc, fdtget, ubinize (mtd-utils). mkimage is NOT needed (scripts/openwrt-make-fit.py).
set -euo pipefail
: "${WORKDIR:=$PWD}"
cd "$WORKDIR"   # working dir that holds work/ and dumps/ (override with WORKDIR=...)
DEV="${DEV:-sxs30}"
W=work/openwrt
B=$W/build
SYS=$W/sysup/sysupgrade-netgear_rbs350
mkdir -p "$B"

case "$DEV" in
  sxs30)
    LAYOUT=sxs30
    ROOTFS_OFF=0x6600000   # slot B base (mtd25 firmware2)
    ROOTFS_SIZE=0x4b00000  # 75 MiB
    # upstream satellite DTB: only 2 GE ports enabled, "wan" label -> the script fixes both
    BASE_FIT=$SYS/kernel
    MODEL=""
    COMPAT=""
    ;;
  sxr30)
    LAYOUT=sxr30
    ROOTFS_OFF=0x8800000   # slot B base (mtd25 firmware2) on the 512 MiB NAND variant
    ROOTFS_SIZE=0x6d00000  # 109 MiB
    # upstream *router* DTB (rbr350): all four GE ports already enabled; only the label changes
    BASE_FIT=$W/openwrt-qualcommax-ipq60xx-netgear_rbr350-initramfs-uImage.itb
    MODEL="Netgear SXR30"
    COMPAT="netgear,sxr30"
    ;;
  *) echo "DEV must be sxs30 or sxr30 (got '$DEV')"; exit 2 ;;
esac

[ -s "$SYS/kernel" ] || { echo "missing $SYS/kernel (run the sysupgrade download step)"; exit 1; }
[ -s "$SYS/root" ]   || { echo "missing $SYS/root"; exit 1; }
[ -s "$BASE_FIT" ]   || { echo "missing $BASE_FIT"; exit 1; }

# --- 1. extract the upstream kernel (gzip Image) and the base DTB --------------------------------
# NB the *initramfs* ITB carries an initramfs-embedded kernel (13 MB) - never install that one: the
# 6 MB no-initramfs kernel from the sysupgrade tarball is what belongs in the UBI `kernel` volume.
# Kernel bytes are identical for rbr350 and rbs350, only the DTB differs, so mix the two freely.
python3 - "$SYS/kernel" "$BASE_FIT" "$B/kernel.gz" "$B/stock-$DEV.dtb" <<'PY'
import subprocess, sys
ksrc, fit, kout, dout = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
def get(src, node):
    h = subprocess.check_output(["fdtget","-t","x",src,"/images/%s"%node,"data"]).decode()
    return bytes(int(t,16) for t in h.split())
open(kout,"wb").write(get(ksrc,"kernel-1"))
open(dout,"wb").write(get(fit,"fdt-1"))
print("kernel.gz %d B from %s ; base dtb %d B from %s"
      % (len(open(kout,'rb').read()), ksrc, len(open(dout,'rb').read()), fit))
PY

# the rootfs squashfs comes from the sysupgrade tarball (identical for rbr350 and rbs350)
cp "$SYS/root" "$B/root.sqsh"

# --- 2. custom DTB (fixed NAND partitions) -------------------------------------------------------
dtc -I dtb -O dts "$B/stock-$DEV.dtb" -o "$B/stock-$DEV.dts" 2>/dev/null
EXTRA=()
[ -n "$MODEL" ] && EXTRA+=(--model "$MODEL")
[ -n "$COMPAT" ] && EXTRA+=(--compatible "$COMPAT")
python3 scripts/openwrt-make-dtb.py "$B/stock-$DEV.dts" "$B/$DEV.dts" \
    --layout "$LAYOUT" --rootfs-off "$ROOTFS_OFF" --rootfs-size "$ROOTFS_SIZE" "${EXTRA[@]+"${EXTRA[@]}"}"
dtc -I dts -O dtb -o "$B/$DEV.dtb" "$B/$DEV.dts" 2>/dev/null

# --- 3. kernel FIT (no mkimage needed) -----------------------------------------------------------
python3 scripts/openwrt-make-fit.py \
    --kernel "$B/kernel.gz" --dtb "$B/$DEV.dtb" --out "$B/openwrt-$DEV.itb" \
    --desc "ARM64 OpenWrt FIT (Flattened Image Tree)" \
    --kdesc "ARM64 OpenWrt Linux kernel" \
    --fdesc "ARM64 OpenWrt $DEV device tree blob" \
    --load 0x41000000 --entry 0x41000000 --config-name config@1 --keep-dts "$B/openwrt-$DEV.its"

# --- 4. UBI image (kernel + squashfs + auto-resizing overlay) ------------------------------------
ROOTSZ=$(stat -c%s "$B/root.sqsh")
ROOTVOL=$(( (ROOTSZ + 1048575) / 1048576 ))
cat > "$B/ubinize.cfg" <<CFG
[kernel]
mode=ubi
vol_id=0
vol_type=dynamic
vol_name=kernel
image=$PWD/$B/openwrt-$DEV.itb

[rootfs]
mode=ubi
vol_id=1
vol_type=dynamic
vol_name=rootfs
image=$PWD/$B/root.sqsh
vol_size=${ROOTVOL}MiB

[rootfs_data]
mode=ubi
vol_id=2
vol_type=dynamic
vol_name=rootfs_data
vol_size=1MiB
vol_flags=autoresize
CFG
ubinize -o "$B/openwrt-$DEV.ubi" -m 2048 -p 128KiB -s 2048 "$B/ubinize.cfg" 2>&1 | tail -3

echo "=== results ==="
( cd "$B" && sha256sum "$DEV.dtb" "openwrt-$DEV.itb" "openwrt-$DEV.ubi" root.sqsh > "SHA256SUMS-$DEV" ) \
    && cat "$B/SHA256SUMS-$DEV"
UBISZ=$(stat -c%s "$B/openwrt-$DEV.ubi")
echo "UBI $UBISZ bytes = $(( (UBISZ + 131071) / 131072 )) PEBs, fits in $ROOTFS_SIZE byte partition"
echo "NAND slot B offset $ROOTFS_OFF (mtd25 firmware2), erase+write with:"
echo "  flash_erase /dev/mtd25 0 0 && nandwrite -p /dev/mtd25 /tmp/openwrt-$DEV.ubi"
echo "U-Boot env: setenv mtdparts 'mtdparts=nand0:${ROOTFS_SIZE}@${ROOTFS_OFF}(rootfs)'"
echo "FIT config:"; fdtget -t s "$B/openwrt-$DEV.itb" /configurations/config@1 kernel; fdtget -t s "$B/openwrt-$DEV.itb" /configurations/config@1 fdt
echo "DTB partitions:"
dtc -I dtb -O dts "$B/$DEV.dtb" 2>/dev/null | grep -E 'label = ' | sed 's/^[[:space:]]*/  /'
