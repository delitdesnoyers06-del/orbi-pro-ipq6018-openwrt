#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""Push a file to the Orbi over its telnet shell (:2323), base64-encoded.

Needed because the target may only offer the passwordless telnetd (e.g. while it is running the
*first* custom image during a recovery) and because the workstation's ufw blocks the target from
fetching anything from us - but a connection *from* the workstation *to* the target is fine.

How it works: we open the telnet port, start `base64 -d > <target-path>`, stream the base64 text
(the pty is in canonical mode; base64 is pure ASCII so no telnet IAC bytes occur), send ^D to close
base64's stdin, then ask the shell for `wc -c` and `sha256sum` and compare with the local file.

The caller should keep the payload modest (tens of MB is fine; the pty roughly halves the
effective rate) and always checks the returned sha256.

Usage: push_b64.py <local-file> <target-path> [host] [port]
"""
import base64
import hashlib
import os
import socket
import sys
import time

CHUNK = 4096

def read_until(sock, needle, timeout=180.0, occurrence=1):
    """Read until needle has been seen `occurrence` times.

    The pty echoes everything we send, so a marker command is echoed *before* its output:
    occurrence=1 would match the echo and return too early.
    """
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if buf.count(needle) >= occurrence:
            return buf
        try:
            data = sock.recv(65536)
        except socket.timeout:
            continue
        if not data:
            break
        buf += data
    return buf


def drain(sock):
    """Discard whatever the pty echoed, so our writes never stall on TCP backpressure."""
    sock.settimeout(0)
    try:
        while sock.recv(262144):
            pass
    except (BlockingIOError, OSError):
        pass
    sock.settimeout(20.0)

def main():
    src, dst = sys.argv[1], sys.argv[2]
    host = sys.argv[3] if len(sys.argv) > 3 else "192.168.1.1"
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 2323

    blob = open(src, "rb").read()
    local_sha = hashlib.sha256(blob).hexdigest()
    payload = base64.b64encode(blob).decode()
    lines = [payload[i:i + 76] for i in range(0, len(payload), 76)]
    print("[push] {} -> {}:{}  {} bytes -> {} base64 lines  sha256 {}".format(
        src, host, port, len(blob), len(lines), local_sha[:16]), flush=True)

    sock = socket.create_connection((host, port), timeout=20)
    sock.settimeout(2.0)
    read_until(sock, b"# ", 10)
    sock.settimeout(20.0)

    # the pty echoes every byte we send - that doubles the traffic and is what makes large pushes
    # crawl, so turn the echo off first
    sock.sendall(b"stty -echo 2>/dev/null\n")
    time.sleep(0.5)
    drain(sock)

    # start the decoder
    sock.sendall("base64 -d > {}\n".format(dst).encode())
    time.sleep(0.4)

    t0 = time.time()
    sent = 0
    for i, line in enumerate(lines):
        sock.sendall((line + "\n").encode())
        sent += len(line)
        if i % 1024 == 0:
            drain(sock)                      # cheap safety net in case stty -echo failed
            time.sleep(0.002)
        if i % 2048 == 0 and i:
            rate = sent / max(time.time() - t0, 0.001) / 1048576.0
            print("  ... {}/{} lines ({:.1f} MiB sent, {:.2f} MiB/s)".format(i, len(lines), sent / 1048576.0, rate), flush=True)
    drain(sock)
    sock.sendall(b"\x04")                    # ^D = EOF for base64 -d
    time.sleep(1.0)
    drain(sock)

    # verify on the target (the marker is matched twice: once in the echo, once in the output)
    sock.settimeout(60.0)
    marker = "PUSH_{}".format(os.getpid())
    sock.sendall(("echo {}_B; wc -c < {}; sha256sum {}; echo {}_E\n".format(
        marker, dst, dst, marker)).encode())
    # with the echo off the marker appears once; if stty failed it appears twice, so accept either
    out = read_until(sock, ("\n" + marker + "_E").encode(), 180, occurrence=1)
    sock.close()

    text = out.decode("latin-1", "replace")
    print(text[-400:])
    ok_size = str(len(blob)) in text
    ok_sha = local_sha in text
    dt = time.time() - t0
    print("[push] {} bytes in {:.0f}s ({:.2f} MiB/s)  size_ok={} sha_ok={}".format(
        len(blob), dt, len(blob) / dt / 1048576.0, ok_size, ok_sha))
    return 0 if (ok_sha and ok_size) else 3

if __name__ == "__main__":
    sys.exit(main())
