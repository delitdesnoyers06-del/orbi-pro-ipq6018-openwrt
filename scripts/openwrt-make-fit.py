#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""Build a U-Boot FIT (.itb) without mkimage - pure dtc + python.

Usage:
  openwrt-make-fit.py --kernel KERNEL.gz --dtb BOARD.dtb --out BOARD.itb \
      [--desc "ARM64 OpenWrt FIT"] [--kdesc "ARM64 OpenWrt Linux-6.18.54"] \
      [--fdesc "ARM64 OpenWrt <board> device tree blob"] [--load 0x41000000] \
      [--entry 0x41000000] [--arch arm64] [--compression gzip] [--config-name sxs30]

Why: `mkimage -f image.its` is just "compile the .its with /incbin/ data and put the digests in".
dtc can compile the same .its (it understands /incbin/), so the only thing mkimage adds is the
hash values - which are computed here in python (crc32 + sha1) and inlined as literal bytes.
Result: byte-for-byte reproducible FITs on a machine that has no u-boot-tools installed.

The FIT layout produced matches what `mkimage -f` produced for the first (SXS30) build:
  /images/kernel-1  (type=kernel, load/entry, hash-1 crc32, hash-2 sha1)
  /images/fdt-1     (type=flat_dt, hash-1 crc32, hash-2 sha1)
  /configurations/default = "config@1", config@1 {kernel, fdt}
"""
import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import zlib


def hexbytes(data):
    return "[" + " ".join("%02x" % b for b in data) + "]"


def digests(data):
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return {
        "crc32": crc.to_bytes(4, "big"),
        "sha1": hashlib.sha1(data).digest(),
        "sha256": hashlib.sha256(data).digest(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--dtb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--desc", default="FIT image for the IPQ6018 Orbi Pro boards")
    ap.add_argument("--kdesc", default="Linux kernel")
    ap.add_argument("--fdesc", default="device tree blob")
    ap.add_argument("--load", default="0x41000000")
    ap.add_argument("--entry", default=None)
    ap.add_argument("--arch", default="arm64")
    ap.add_argument("--compression", default="gzip")
    ap.add_argument("--config-name", default="config@1")
    ap.add_argument("--keep-dts", default=None, help="write the intermediate .its here")
    args = ap.parse_args()

    kdata = open(args.kernel, "rb").read()
    fdata = open(args.dtb, "rb").read()
    entry = args.entry or args.load
    kd, fd = digests(kdata), digests(fdata)
    # /incbin/ resolves relative to the .its file, which lives in a temp dir -> use absolute paths
    kabs = os.path.abspath(args.kernel)
    fabs = os.path.abspath(args.dtb)
    args.out = os.path.abspath(args.out)

    its = f"""/dts-v1/;
/ {{
\tdescription = "{args.desc}";
\t#address-cells = <1>;
\timages {{
\t\tkernel-1 {{
\t\t\tdescription = "{args.kdesc}";
\t\t\tdata = /incbin/("{kabs}");
\t\t\ttype = "kernel";
\t\t\tarch = "{args.arch}";
\t\t\tos = "linux";
\t\t\tcompression = "{args.compression}";
\t\t\tload = <{args.load}>;
\t\t\tentry = <{entry}>;
\t\t\thash-1 {{
\t\t\t\talgo = "crc32";
\t\t\t\tvalue = {hexbytes(kd['crc32'])};
\t\t\t}};
\t\t\thash-2 {{
\t\t\t\talgo = "sha1";
\t\t\t\tvalue = {hexbytes(kd['sha1'])};
\t\t\t}};
\t\t}};
\t\tfdt-1 {{
\t\t\tdescription = "{args.fdesc}";
\t\t\tdata = /incbin/("{fabs}");
\t\t\ttype = "flat_dt";
\t\t\tarch = "{args.arch}";
\t\t\tcompression = "none";
\t\t\thash-1 {{
\t\t\t\talgo = "crc32";
\t\t\t\tvalue = {hexbytes(fd['crc32'])};
\t\t\t}};
\t\t\thash-2 {{
\t\t\t\talgo = "sha1";
\t\t\t\tvalue = {hexbytes(fd['sha1'])};
\t\t\t}};
\t\t}};
\t}};
\tconfigurations {{
\t\tdefault = "{args.config_name}";
\t\t{args.config_name} {{
\t\t\tdescription = "{args.fdesc}";
\t\t\tkernel = "kernel-1";
\t\t\tfdt = "fdt-1";
\t\t}};
\t}};
}};
"""
    dts = args.keep_dts
    if not dts:
        dts = tempfile.mktemp(suffix=".its")
    with open(dts, "w") as fh:
        fh.write(its)
    subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-o", args.out, dts], check=True)
    print("%s: %d bytes (kernel %d, dtb %d) crc32 %08x / %08x"
          % (args.out, len(open(args.out, "rb").read()), len(kdata), len(fdata),
             int.from_bytes(kd["crc32"], "big"), int.from_bytes(fd["crc32"], "big")))


if __name__ == "__main__":
    sys.exit(main())
