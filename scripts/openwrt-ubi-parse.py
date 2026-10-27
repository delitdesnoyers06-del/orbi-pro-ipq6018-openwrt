#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""Parse a raw UBI image (ubinize output): PEB/EC/VID headers, layout volume table, volumes.

Usage: openwrt-ubi-parse.py <image> [peb_size]
"""
import struct, sys

def be32(b, o): return struct.unpack_from(">I", b, o)[0]
def be64(b, o): return struct.unpack_from(">Q", b, o)[0]

def main():
    path = sys.argv[1]
    peb = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0x20000
    d = open(path, "rb").read()
    n = len(d) // peb
    print("image %s size %d (%#x) = %d PEBs" % (path, len(d), len(d), n))
    vols = {}
    layout = None
    for i in range(n):
        off = i * peb
        if d[off:off+4] != b"UBI#":
            print("  PEB %3d: no EC magic" % i); continue
        vid_off = be32(d, off+16); data_off = be32(d, off+20); seq = be32(d, off+24)
        vo = off + vid_off
        if d[vo:vo+4] != b"UBI!":
            print("  PEB %3d: EC vid_off=%#x data_off=%#x seq=%#x, no VID" % (i, vid_off, data_off, seq)); continue
        vt = d[vo+5]; vol_id = be32(d, vo+8); lnum = be32(d, vo+12)
        data_size = be32(d, vo+20); used_ebs = be32(d, vo+24)
        vols.setdefault(vol_id, []).append((i, lnum, vt))
        if vol_id == 0x7FFFFFFF:
            print("  PEB %3d: layout vol_id=%#x lnum=%d vid_off=%#x data_off=%#x data_size=%d used_ebs=%d" % (i, vol_id, lnum, vid_off, data_off, data_size, used_ebs))
            if lnum == 0: layout = off + data_off
        else:
            print("  PEB %3d: vol_id=%-3d lnum=%-3d vol_type=%d data_size=%d used_ebs=%d" % (i, vol_id, lnum, vt, data_size, used_ebs))
    if layout is not None:
        print("-- volume table --")
        for k in range(8):
            r = layout + k*172
            reserved = be32(d, r); align = be32(d, r+4); pad = be32(d, r+8)
            vtype = d[r+12]; nl = struct.unpack_from(">H", d, r+14)[0]
            name = d[r+16:r+16+min(nl,128)].decode("latin-1")
            flags = d[r+16+128]
            if nl == 0: continue
            print("  id=%-3d name=%-14s reserved_pebs=%-4d alignment=%-3d data_pad=%-4d vol_type=%d flags=%#x" % (k, name, reserved, align, pad, vtype, flags))
    print("-- volumes --")
    for vid in sorted(vols):
        print("  vol_id %-10d pebs=%d" % (vid, len(vols[vid])))

if __name__ == "__main__":
    main()
