#!/usr/bin/env bash
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
#
# Download the upstream OpenWrt artifacts the build script consumes.
#
#   fetch-openwrt-artifacts.sh [base-url]
#
# Default base-url = the current qualcommax/ipq60xx snapshot.  Pin a dated snapshot for
# reproducibility, e.g.
#   fetch-openwrt-artifacts.sh https://downloads.openwrt.org/snapshots/targets/qualcommax/ipq60xx
#
# Produces (under $WORKDIR, default = cwd):
#   work/openwrt/sysup/sysupgrade-netgear_rbs350/{kernel,root}   <- unpacked from the sysupgrade tar
#   work/openwrt/openwrt-qualcommax-ipq60xx-netgear_rbr350-initramfs-uImage.itb   (router DTB source)
#
# Why these two: the *kernel bytes are identical* for rbr350 and rbs350 (same target build), so the
# kernel/rootfs are taken from the rbs350 sysupgrade tarball and only the device tree differs - the
# rbr350 DTB (all four GE ports enabled) is the right base for the SXR30 router, rbs350 for the
# SXS30 satellite.  Do NOT take the kernel from an *initramfs* ITB: that one embeds an initramfs and
# ignores the rootfs volume.
set -euo pipefail
WORKDIR="${WORKDIR:-$PWD}"
cd "$WORKDIR"
BASE="${1:-https://downloads.openwrt.org/snapshots/targets/qualcommax/ipq60xx}"
SYS="work/openwrt/sysup/sysupgrade-netgear_rbs350"
mkdir -p "$SYS" work/openwrt

say() { printf '\033[1m%s\033[0m\n' "$*"; }

say "== sysupgrade tarball (rbs350: kernel + squashfs root)"
SU="$BASE/openwrt-qualcommax-ipq60xx-netgear_rbs350-squashfs-sysupgrade.bin"
curl -fL --progress-bar -o work/openwrt/rbs350-sysupgrade.bin "$SU"
# the tarball contains a top-level directory (sysupgrade-netgear_rbs350/) - strip it
rm -rf "$SYS"; mkdir -p "$SYS"
tar -xf work/openwrt/rbs350-sysupgrade.bin -C "$SYS" --strip-components=1

say "== rbr350 initramfs ITB (source of the router device tree)"
RB="$BASE/openwrt-qualcommax-ipq60xx-netgear_rbr350-initramfs-uImage.itb"
curl -fL --progress-bar -o work/openwrt/openwrt-qualcommax-ipq60xx-netgear_rbr350-initramfs-uImage.itb "$RB"

say "== results"
ls -l "$SYS" work/openwrt/openwrt-qualcommax-ipq60xx-netgear_rbr350-initramfs-uImage.itb
sha256sum "$SYS/kernel" "$SYS/root" | sed 's#^#  #'
cat <<'EOF'

next:  DEV=sxr30 scripts/openwrt-build-image.sh        # or DEV=sxs30
       (needs dtc, fdtget, ubinize from mtd-utils; mkimage is NOT needed)
EOF
