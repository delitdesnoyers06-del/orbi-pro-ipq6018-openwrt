#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""Verified, bad-block-aware backup of the Orbi's NAND partitions.

For each partition the target reports its readable length and sha256 as produced by
`dd bs=65536` (which stops at an unreadable/bad eraseblock). Exactly that many bytes
are then pulled as base64 and verified against the target's hash.

Usage: dump.py [outdir] [index-filter]   (filter e.g. "0-33" or "5,22")
"""
import hashlib
import os
import re
import sys
import time

HERE = __file__.rsplit("/", 1)[0]
sys.path.insert(0, HERE)
import orbi_tcp
import pull_b64

OUTDIR = sys.argv[1] if len(sys.argv) > 1 else "dumps"
FILTER = sys.argv[2] if len(sys.argv) > 2 else ""
SKIP_DEFAULT = {34}          # nand0 = whole chip, union of mtd0..mtd33

os.makedirs(OUTDIR, exist_ok=True)


def log(msg):
    print("[{}] {}".format(time.strftime("%H:%M:%S"), msg), flush=True)


def parse_filter(spec, count):
    if not spec:
        return set(range(count)) - SKIP_DEFAULT
    wanted = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            wanted.update(range(int(a), int(b) + 1))
        elif chunk:
            wanted.add(int(chunk))
    return wanted


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


mtd_text = orbi_tcp.run("cat /proc/mtd", 20)
parts = []
for line in mtd_text.splitlines():
    m = re.match(r'\s*(mtd\d+):\s*([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+"(.*)"', line)
    if m:
        parts.append({"idx": int(m.group(1)[3:]), "size": int(m.group(2), 16), "name": m.group(4)})
if not parts:
    log("FATAL: could not parse /proc/mtd: {!r}".format(mtd_text[:200]))
    sys.exit(1)

wanted = parse_filter(FILTER, len(parts))
log("selected {} of {} partitions".format(len(wanted), len(parts)))

sums = open(os.path.join(OUTDIR, "SHA256SUMS-verified.txt"), "w")
report = []

for part in parts:
    idx, size, name = part["idx"], part["size"], part["name"]
    if idx not in wanted:
        continue
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    base = os.path.join(OUTDIR, "mtd{:02d}-{}".format(idx, safe))
    path = base + ".bin"
    dev = "/dev/mtd{}".format(idx)

    probe_timeout = max(90.0, 30.0 + size / 1048576.0 * 6.0)
    probe = orbi_tcp.run(
        "dd if={0} bs=65536 2>/dev/null | wc -c; dd if={0} bs=65536 2>/dev/null | sha256sum".format(dev),
        probe_timeout)
    nums = re.findall(r"^\s*(\d+)\s*$", probe, re.M)
    hexes = re.findall(r"\b([0-9a-fA-F]{64})\b", probe)
    if not nums or not hexes:
        log("mtd{:02d} PROBE FAILED: {!r}".format(idx, probe[-120:]))
        part.update(status="PROBE_FAIL", readable=0, sha256="")
        report.append(part)
        continue
    readable = int(nums[0])
    target_sum = hexes[0].lower()

    t0 = time.time()
    try:
        got = pull_b64.pull("dd if={} bs=65536 2>/dev/null | base64".format(dev), path,
                            readable, max(120.0, 60.0 + readable / 1048576.0 * 20.0))
    except Exception as err:  # noqa: BLE001
        log("mtd{:02d} PULL ERROR {!r}".format(idx, err))
        part.update(status="PULL_ERROR", readable=readable, sha256="")
        report.append(part)
        continue
    dt = time.time() - t0
    local_sum = sha256_file(path) if got == readable else ""
    ok = got == readable and local_sum == target_sum
    if not ok and os.path.exists(path):
        os.replace(path, base + ".bad")
    trunc = "" if readable == size else " TRUNCATED -{}B (bad block)".format(size - readable)
    log("mtd{:02d} {:>7.2f} MiB {:<22} {:>10} B {:>5.1f}s {}{}".format(
        idx, size / 1048576.0, name, got, dt, "OK" if ok else "FAIL", trunc))
    if ok:
        sums.write("{}  mtd{:02d}-{}.bin\n".format(target_sum, idx, safe))
        sums.flush()
        with open(base + ".meta", "w") as meta:
            meta.write("partition: {}\nname: {}\ndevice: {}\npartition_size: {}\nreadable_size: {}\nunreadable_tail: {}\nmethod: dd bs=65536 | base64 (bad blocks stop the read)\nsha256_readable: {}\ndumped: {}\n".format(
                idx, name, dev, size, readable, size - readable, target_sum, time.ctime()))
    part.update(status="OK" if ok else "FAIL", readable=readable, sha256=target_sum)
    report.append(part)

sums.close()
with open(os.path.join(OUTDIR, "dump-report.txt"), "w") as fh:
    fh.write("Orbi SXS30 mtd dump report {}\n".format(time.ctime()))
    fh.write("partition  size        name                   status  readable    sha256\n")
    for p in report:
        fh.write("mtd{:02d} {:>11} {:<22} {:<7} {:>10} {}\n".format(
            p["idx"], p["size"], p["name"], p.get("status", "?"), p.get("readable", 0), p.get("sha256", "")))

bad = [p for p in report if p.get("status") != "OK"]
log("done: {} partitions, {} problems".format(len(report), len(bad)))
for p in bad:
    log("  problem: mtd{:02d} {} {}".format(p["idx"], p["name"], p.get("status")))
