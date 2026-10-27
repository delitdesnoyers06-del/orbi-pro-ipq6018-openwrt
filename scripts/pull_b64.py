#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""Host-initiated pull of device data via the target's busybox base64.
Decodes strictly per output line (busybox base64 wraps at 76 chars, 4-aligned),
so prompt/junk lines can never shift the base64 alignment.

Usage: pull_b64.py <target-device> <outfile> <expected-bytes> [timeout]
"""
import base64
import os
import re
import socket
import sys
import time

HOST = os.environ.get("ORBI_TARGET_IP", "192.168.1.1")
PORT = 2323


def _clean(line):
    s = re.sub(r"[^A-Za-z0-9+/=]", "", line)
    if not s:
        return b""
    eq = s.find("=")
    if eq != -1:
        s = s[: eq + (4 - (eq % 4))]
    s = s[: (len(s) // 4) * 4]
    if not s:
        return b""
    try:
        return base64.b64decode(s)
    except Exception:  # noqa: BLE001
        return b""


def _connect(host, port, timeout):
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(1.0)
    deadline = time.time() + 10
    buf = b""
    while time.time() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk
        if buf.endswith(b"# "):
            break
    sock.settimeout(timeout)
    return sock


def pull(cmd, out, size, timeout=300.0, host=HOST, port=PORT):
    """Run `cmd` on the target (must base64-encode its data) and save `size` bytes."""
    sock = _connect(host, port, timeout)
    sock.sendall((cmd + "\n").encode())

    written = 0
    textbuf = ""
    first_line = True
    deadline = time.time() + timeout

    with open(out, "wb") as fh:
        while written < size and time.time() < deadline:
            try:
                chunk = sock.recv(262144)
            except socket.timeout:
                continue
            if not chunk:
                break
            textbuf += chunk.decode("latin-1")
            if first_line:
                nl = textbuf.find("\n")
                if nl < 0:
                    continue
                textbuf = textbuf[nl + 1:]
                first_line = False
            while "\n" in textbuf and written < size:
                line, textbuf = textbuf.split("\n", 1)
                data = _clean(line)
                if not data:
                    continue
                if len(data) > size - written:
                    data = data[: size - written]
                fh.write(data)
                written += len(data)
        if written < size and textbuf:
            data = _clean(textbuf)
            if data:
                data = data[: size - written]
                fh.write(data)
                written += len(data)
    sock.close()
    return written


def main():
    dev = sys.argv[1]
    out = sys.argv[2]
    size = int(sys.argv[3])
    timeout = float(sys.argv[4]) if len(sys.argv) > 4 else max(120.0, size / 1048576.0 * 12)
    t0 = time.time()
    written = pull("base64 " + dev, out, size, timeout)
    dt = time.time() - t0
    rate = (written / 1048576.0) / dt if dt else 0
    print("{}: {} bytes (expected {}), {:.1f}s, {:.2f} MiB/s".format(out, written, size, dt, rate))
    sys.exit(0 if written == size else 3)


if __name__ == "__main__":
    main()
