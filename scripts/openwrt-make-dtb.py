#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""Rewrite the NAND `partitions` node of a decompiled DTS from qcom,smem-part to a fixed table.

Usage:
  openwrt-make-dtb.py <stock.dts> <out.dts> [options]

Options:
  --layout sxs30|sxr30   preset for the two known Orbi Pro "starling" boards (default: sxs30)
  --rootfs-off OFF       NAND offset of the read/write `rootfs` NAND partition (UBI lives here)
  --rootfs-size SIZE     size of that partition
  --model "Netgear SXR30"        rewrite /model
  --compatible "netgear,sxr30"   rewrite /compatible (first string wins)

Why a fixed table at all: the OpenWrt qualcommax kernel has CONFIG_MTD_CMDLINE_PARTS **off**
(`mtdparts=` is silently ignored - proven on hardware) and the DTB from upstream uses
`qcom,smem-part`, i.e. the bootloader's SMEM table, which only contains the 16 QTI partitions
(`0:sbl1`..`0:art`). Without this rewrite the OpenWrt kernel cannot see NAND at all, so there is no
`rootfs` partition to put a UBI on, and no `0:art` partition for the ath11k calibration.

The two boards differ only by NAND size, hence the two presets:
  sxs30  256 MiB NAND, slot B at 0x6600000, 0x4b00000 bytes  (75 MiB)
  sxr30  512 MiB NAND, slot B at 0x8800000, 0x6d00000 bytes  (109 MiB)
Everything below slot A is identical on both (same offsets and sizes), which is why one script covers
both: only the `rootfs` entry and the vendor A/B header block change place.
"""
import sys

# (offset, size, label, read-only)  -- offsets from the vendor/SMEM layout; identical on both boards
PARTS = [
    (0x0000000, 0x0180000, "0:sbl1",        True),
    (0x0180000, 0x0100000, "0:mibib",       True),
    (0x0280000, 0x0080000, "0:bootconfig",  True),
    (0x0300000, 0x0080000, "0:bootconfig1", True),
    (0x0380000, 0x0380000, "0:qsee",        True),
    (0x0700000, 0x0380000, "0:qsee_1",      True),
    (0x0a80000, 0x0080000, "0:devcfg",      True),
    (0x0b00000, 0x0080000, "0:devcfg_1",    True),
    (0x0b80000, 0x0080000, "0:rpm",         True),
    (0x0c00000, 0x0080000, "0:rpm_1",       True),
    (0x0c80000, 0x0080000, "0:cdt",         True),
    (0x0d00000, 0x0080000, "0:cdt_1",       True),
    (0x0d80000, 0x0080000, "0:appsblenv",   True),
    (0x0e00000, 0x0180000, "0:appsbl",      True),
    (0x0f80000, 0x0180000, "0:appsbl_1",    True),
    (0x1100000, 0x0080000, "0:art",         True),
    # maintenance window: the last block of the vendor slot-A kernel partition holds the rootfs
    # uImage header; exposing it lets OpenWrt fix/restore that header (writable on purpose)
    (0x1fc0000, 0x0020000, "vendor_hdr",     False),
]

# board preset -> (rootfs offset, rootfs size)
LAYOUTS = {
    "sxs30": (0x6600000, 0x4b00000),   # 256 MiB NAND, slot B = firmware2
    "sxr30": (0x8800000, 0x6d00000),   # 512 MiB NAND, slot B = firmware2
}


def find_partitions_block(text):
    key = 'compatible = "qcom,smem-part";'
    ki = text.index(key)
    start = text.rindex("partitions {", 0, ki)
    i = text.index("{", start)
    depth = 0
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                j = i + 1
                while j < len(text) and text[j] not in "\n":
                    j += 1
                return start, j
        i += 1
    raise SystemExit("unterminated partitions node")


def main(argv):
    args = argv[1:]
    opts = {}
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 >= len(args):
                raise SystemExit("missing value for %s" % a)
            opts[key] = args[i + 1]
            i += 2
        else:
            pos.append(a)
            i += 1
    if len(pos) != 2:
        raise SystemExit(__doc__)
    src, dst = pos
    layout = opts.get("layout", "sxs30")
    if layout not in LAYOUTS:
        raise SystemExit("unknown layout %r (known: %s)" % (layout, ", ".join(LAYOUTS)))
    rootfs_off = int(opts["rootfs-off"], 0) if "rootfs-off" in opts else LAYOUTS[layout][0]
    rootfs_size = int(opts["rootfs-size"], 0) if "rootfs-size" in opts else LAYOUTS[layout][1]

    text = open(src).read()

    # The upstream rbx350 DTS only enables the GE ports the *consumer* variants have; the SXK30
    # boards (SXR30 router and SXS30 satellite) both have four RJ45 jacks on the QCA8075 package.
    # Upstream: port@2 = "wan", port@3 = "lan3", port@4 = "lan2", port@5 = "lan1".
    # On the rbs350 DTB port@2 and port@3 are disabled -> drop those two status lines.
    # On the rbr350 DTB they are already enabled -> nothing to do (idempotent for both bases).
    for mac_cell in ("0x26 0x03", "0x26 0x02"):
        old = ('\t\t\t\t\tnvmem-cells = <%s>;\n'
               '\t\t\t\t\tnvmem-cell-names = "mac-address";\n'
               '\t\t\t\t\tstatus = "disabled";\n' % mac_cell)
        if old in text:
            text = text.replace(old, old.replace('\t\t\t\t\tstatus = "disabled";\n', ''))
    # the fourth jack is a LAN port on these boards (the vendor bridges all four in br-lan)
    text = text.replace('\t\t\t\t\tlabel = "wan";', '\t\t\t\t\tlabel = "lan4";')

    if "model" in opts:
        import re
        text = re.sub(r'(\n\tmodel = ")[^"]*(";)', r'\g<1>%s\g<2>' % opts["model"], text, count=1)
    if "compatible" in opts:
        import re
        text = re.sub(r'(\n\tcompatible = ")[^"]*(",)', r'\g<1>%s\g<2>' % opts["compatible"],
                      text, count=1)

    # NB: locate the partitions node only *after* the edits above - they change the
    # length of the text, so offsets taken earlier would be stale (this cost one boot loop).
    s, e = find_partitions_block(text)
    out = ['partitions {',
           '\t\t\t\t\tcompatible = "fixed-partitions";',
           "\t\t\t\t\t#address-cells = <0x01>;",
           "\t\t\t\t\t#size-cells = <0x01>;"]
    for off, size, label, ro in PARTS:
        out += ["",
                "\t\t\t\t\tpartition@%x {" % off,
                '\t\t\t\t\t\tlabel = "%s";' % label,
                "\t\t\t\t\t\treg = <0x%x 0x%x>;" % (off, size)]
        if ro:
            out.append("\t\t\t\t\t\tread-only;")
        out.append("\t\t\t\t\t};")
    # boarddata with MAC nvmem at offset 0 (vendor boarddata1: base MAC at 0x0)
    out += ["",
            "\t\t\t\t\tpartition@1300000 {",
            '\t\t\t\t\t\tlabel = "boarddata";',
            "\t\t\t\t\t\treg = <0x1300000 0x100000>;",
            "\t\t\t\t\t\tread-only;",
            "\t\t\t\t\t\tnvmem-layout {",
            '\t\t\t\t\t\t\tcompatible = "fixed-layout";',
            "\t\t\t\t\t\t\t#address-cells = <0x01>;",
            "\t\t\t\t\t\t\t#size-cells = <0x01>;",
            "",
            "\t\t\t\t\t\t\tmacaddr@0 {",
            '\t\t\t\t\t\t\t\tcompatible = "mac-base";',
            "\t\t\t\t\t\t\t\treg = <0x00 0x06>;",
            "\t\t\t\t\t\t\t\t#nvmem-cell-cells = <0x01>;",
            "\t\t\t\t\t\t\t\tphandle = <0x26>;",
            "\t\t\t\t\t\t\t};",
            "\t\t\t\t\t\t};",
            "\t\t\t\t\t};",
            "",
            "\t\t\t\t\tpartition@%x {" % rootfs_off,
            '\t\t\t\t\t\tlabel = "rootfs";',
            "\t\t\t\t\t\treg = <0x%x 0x%x>;" % (rootfs_off, rootfs_size),
            "\t\t\t\t\t};",
            "\t\t\t\t};"]

    new = text[:s] + "\n".join(out) + text[e:]
    open(dst, "w").write(new)
    print("rewrote %s -> %s (%d -> %d bytes) rootfs=0x%x+0x%x (%d MiB)"
          % (src, dst, len(text), len(new), rootfs_off, rootfs_size,
             rootfs_size // 1048576))


if __name__ == "__main__":
    main(sys.argv)
