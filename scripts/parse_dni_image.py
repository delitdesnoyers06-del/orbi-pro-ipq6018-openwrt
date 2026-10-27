#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""Parse the Netgear DNI firmware container found on the Orbi SXS30 NAND (mtd22/mtd25).

Layout (slot A, verified against the U-Boot boot log):
  0x0000  ELF header + 3 program headers (52 + 3*32 = 0x94 bytes)
          phdr0 PT_NULL off=0x0     vaddr=0            filesz=0x94       (the header itself)
          phdr1 PT_NULL off=0x1000  vaddr=0x444c4000   filesz=0x1a38     (signature/manifest block)
          phdr2 PT_LOAD off=0x3000  vaddr=0x44000000   filesz=0x4c3c48   (signed kernel payload)
  0x3000  FIT image (magic 0xd00dfeed) - kernel@1 + 3 device trees
  0x4dffc0 legacy uImage header, payload = squashfs at 0x4e0000

Usage: parse_dni_image.py <dump.bin> [--json]
"""
import binascii
import json
import struct
import sys

ELF_MAGIC = b"\x7fELF"
FIT_MAGIC = b"\xd0\x0d\xfe\xed"
UIMAGE_MAGIC = b"\x27\x05\x19\x56"
SQSH_MAGIC = b"hsqs"
UIMAGE_HEADER_LEN = 64

UIMAGE_OS = {0: "invalid", 1: "openbsd", 2: "netbsd", 3: "freebsd", 4: "4_4bsd", 5: "linux",
             14: "vxworks", 17: "qnx", 22: "vxworks"}
UIMAGE_ARCH = {2: "arm", 3: "i386", 5: "mips", 6: "mips64", 7: "ppc", 10: "ia64", 11: "ppc64",
               22: "arm64", 26: "x86_64"}
UIMAGE_TYPE = {1: "standalone", 2: "kernel", 3: "ramdisk", 4: "multi", 5: "firmware", 6: "script",
               7: "filesystem", 8: "flatdt", 14: "kernel_noload"}
UIMAGE_COMP = {0: "none", 1: "gzip", 2: "bzip2", 3: "lzma", 4: "lzo", 5: "lz4", 6: "zstd"}

SQSH_COMP = {1: "gzip", 2: "lzma", 3: "lzo", 4: "xz", 5: "lz4", 6: "zstd"}


def parse_elf(data):
    if data[:4] != ELF_MAGIC:
        return None
    (etype, emach, ever) = struct.unpack("<HHI", data[16:24])
    phoff, shoff = struct.unpack("<II", data[28:36])
    ehsize, phentsize, phnum = struct.unpack("<HHH", data[40:46])
    phdrs = []
    for i in range(phnum):
        off = phoff + i * phentsize
        (p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align) = struct.unpack("<8I", data[off:off + 32])
        phdrs.append({"index": i, "type": p_type, "offset": p_offset, "vaddr": p_vaddr,
                      "paddr": p_paddr, "filesz": p_filesz, "memsz": p_memsz, "flags": p_flags,
                      "align": p_align, "end": p_offset + p_filesz})
    return {"class": data[4], "endian": data[5], "e_type": etype, "e_machine": emach,
            "e_version": ever, "e_phoff": phoff, "e_shoff": shoff, "e_ehsize": ehsize,
            "e_phentsize": phentsize, "e_phnum": phnum, "phdrs": phdrs}


def parse_uimage(data, off):
    if data[off:off + 4] != UIMAGE_MAGIC:
        return None
    (hcrc, timestamp, size, load, ep, dcrc) = struct.unpack(">IIIIII", data[off + 4:off + 28])
    os_id, arch, itype, comp = data[off + 28:off + 32]
    name = data[off + 32:off + 64].split(b"\x00")[0].decode("latin-1")
    payload = off + UIMAGE_HEADER_LEN
    calc = binascii.crc32(data[payload:payload + size]) & 0xFFFFFFFF
    hdr_calc = binascii.crc32(data[off + 4:off + 64]) & 0xFFFFFFFF
    return {"offset": off, "payload_offset": payload, "payload_end": payload + size,
            "header_crc": hcrc, "header_crc_ok": hdr_calc == hcrc, "timestamp": timestamp,
            "size": size, "load": load, "ep": ep, "data_crc": dcrc, "data_crc_ok": calc == dcrc,
            "data_crc_calc": calc, "os": UIMAGE_OS.get(os_id, os_id),
            "arch": UIMAGE_ARCH.get(arch, arch), "image_type": UIMAGE_TYPE.get(itype, itype),
            "compression": UIMAGE_COMP.get(comp, comp), "name": name}


def parse_squashfs(data, off):
    if data[off:off + 4] != SQSH_MAGIC:
        return None
    (magic, inodes, mkfs_time, block_size, fragments, comp, block_log, flags, no_ids, s_major, s_minor,
     root_inode, bytes_used, id_table_start, xattr_id_table_start, inode_table_start,
     directory_table_start, fragment_table_start, lookup_table_start) = struct.unpack("<5I6H8Q", data[off:off + 96])
    return {"offset": off, "inodes": inodes, "mkfs_time": mkfs_time, "block_size": block_size,
            "fragments": fragments, "compression": SQSH_COMP.get(comp, comp), "block_log": block_log,
            "flags": flags, "no_ids": no_ids, "version": "%d.%d" % (s_major, s_minor),
            "root_inode": root_inode, "bytes_used": bytes_used, "id_table_start": id_table_start,
            "xattr_id_table_start": xattr_id_table_start, "inode_table_start": inode_table_start,
            "directory_table_start": directory_table_start, "fragment_table_start": fragment_table_start,
            "lookup_table_start": lookup_table_start}


def fdt_strings(blob):
    """Minimal FDT scan: return (properties {name: bytes}, node paths) without a full parser."""
    if blob[:4] != FIT_MAGIC:
        return {}, []
    (totalsize, off_dt_struct, off_dt_strings, off_mem_rsvmap, version, last_comp_version) = struct.unpack(">IIIIII", blob[4:28])
    strings = blob[off_dt_strings:totalsize]
    pos = off_dt_struct
    props = []
    path = []
    while pos < totalsize:
        token = struct.unpack(">I", blob[pos:pos + 4])[0]
        pos += 4
        if token == 1:      # FDT_BEGIN_NODE
            end = blob.index(b"\x00", pos)
            name = blob[pos:end].decode("latin-1")
            path.append(name)
            pos = (end + 4) & ~3
        elif token == 2:    # FDT_END_NODE
            if path:
                path.pop()
        elif token == 3:    # FDT_PROP
            length, nameoff = struct.unpack(">II", blob[pos:pos + 8])
            pos += 8
            s_end = strings.index(b"\x00", nameoff)
            pname = strings[nameoff:s_end].decode("latin-1")
            val = blob[pos:pos + length]
            pos = (pos + length + 3) & ~3
            props.append({"path": "/" + "/".join(path), "name": pname, "value": val})
        elif token == 9:    # FDT_END
            break
        else:
            break
    return props, ["/" + "/".join(p) for p in []]


def fit_summary(data, fit_off):
    size = struct.unpack(">I", data[fit_off + 4:fit_off + 8])[0]
    blob = data[fit_off:fit_off + size]
    props, _ = fdt_strings(blob)
    images = {}
    for p in props:
        key = (p["path"], p["name"])
        images.setdefault(p["path"], {})[p["name"]] = p["value"]
    out = []
    for path, fields in images.items():
        if not path.startswith("/images/"):
            continue
        entry = {"node": path}
        for k in ("description", "type", "arch", "compression", "os", "load", "entry"):
            if k in fields:
                val = fields[k].split(b"\x00")[0].decode("latin-1")
                if k in ("load", "entry") and len(fields[k]) == 4:
                    val = "%#x" % struct.unpack(">I", fields[k])[0]
                entry[k] = val
        for k, v in fields.items():
            if k.startswith("data-size") and len(v) == 4:
                entry[k] = struct.unpack(">I", v)[0]
            if k.startswith("data-position") and len(v) == 4:
                entry[k] = fit_off + struct.unpack(">I", v)[0]
            if k in ("value") and len(v) == 20:
                entry["sha1"] = v.hex()
            if k in ("value") and len(v) == 4:
                entry["crc32"] = "%08x" % struct.unpack(">I", v)[0]
        out.append(entry)
    return {"size": size, "end": fit_off + size, "images": out,
            "description": next((p["value"].split(b"\x00")[0].decode("latin-1")
                                 for p in props if p["path"] == "/" and p["name"] == "description"), None)}


def analyse(path):
    data = open(path, "rb").read()
    res = {"file": path, "size": len(data)}
    elf = parse_elf(data)
    res["elf"] = elf
    fits = [i for i in (data.find(FIT_MAGIC),) if i >= 0]
    fit_off = fits[0] if fits else None
    if fit_off is not None:
        res["fit"] = fit_summary(data, fit_off)
        res["fit"]["offset"] = fit_off
    uimgs = []
    pos = data.find(UIMAGE_MAGIC)
    while pos != -1 and len(uimgs) < 8:
        hdr = parse_uimage(data, pos)
        if hdr:
            uimgs.append(hdr)
        pos = data.find(UIMAGE_MAGIC, pos + 1)
    res["uimages"] = uimgs
    sq = []
    pos = data.find(SQSH_MAGIC)
    while pos != -1 and len(sq) < 8:
        s = parse_squashfs(data, pos)
        if s:
            sq.append(s)
        pos = data.find(SQSH_MAGIC, pos + 1)
    res["squashfs"] = sq
    res["metadata_block"] = None
    if elf:
        m = next((p for p in elf["phdrs"] if p["offset"] == 0x1000), None)
        if m:
            blk = data[m["offset"]:m["end"]]
            res["metadata_block"] = {"offset": m["offset"], "size": len(blk),
                                     "first_64_hex": blk[:64].hex(),
                                     "printable": "".join(chr(b) if 32 <= b < 127 else "." for b in blk[:256])}
    return res


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    res = analyse(sys.argv[1])
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2))
        return 0
    print("file      : {file}  ({size} bytes, {mib:.2f} MiB)".format(mib=res["size"] / 1048576.0, **res))
    elf = res["elf"]
    if elf:
        print("ELF       : class={class} endian={endian} e_machine={e_machine:#x} phnum={e_phnum}".format(**elf))
        for p in elf["phdrs"]:
            print("  phdr{index}: type={type:#x} off={offset:#x} vaddr={vaddr:#x} filesz={filesz:#x} memsz={memsz:#x} end={end:#x}".format(**p))
    if res.get("fit"):
        f = res["fit"]
        print("FIT       : off={offset:#x} size={size} end={end:#x} desc={description}".format(**f))
        for img in f["images"]:
            print("   {node:<22} type={type:<8} comp={compression:<10} data_pos={data-position:#x} size={data-size:<9} load={load}".format(**{k: img.get(k, "-") for k in ("node", "type", "compression", "data-position", "data-size", "load")}))
    for u in res["uimages"]:
        print("uImage    : off={offset:#x} payload={payload_offset:#x}..{payload_end:#x} size={size} "
              "name='{name}' arch={arch} type={image_type} comp={compression} "
              "hdr_crc_ok={header_crc_ok} data_crc_ok={data_crc_ok}".format(**u))
    for s in res["squashfs"]:
        print("squashfs  : off={offset:#x} v{version} comp={compression} block={block_size} "
              "inodes={inodes} bytes_used={bytes_used} root_inode={root_inode:#x} "
              "inode_table={inode_table_start:#x} dir_table={directory_table_start:#x} "
              "frag_table={fragment_table_start:#x}".format(**s))
    mb = res.get("metadata_block")
    if mb:
        print("meta blk  : off={offset:#x} size={size} head={first_64_hex}".format(**mb))
        print("            {}".format(mb["printable"][:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
