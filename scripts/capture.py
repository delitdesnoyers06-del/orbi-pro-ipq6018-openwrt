#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""UART capture for Netgear Orbi SXS30 recon (Flipper Zero USB-UART bridge).
Survives port re-enumeration: reopens the device and re-applies termios on error.
Usage: capture.py <port> <rawlog> [seconds]
Raw bytes -> <rawlog>; timestamp/chunk sidecar -> <rawlog>.ts
Stop early: touch <rawlog>.stop
"""
import os, subprocess, sys, select, time

port = sys.argv[1]
out = sys.argv[2]
duration = float(sys.argv[3]) if len(sys.argv) > 3 else 900.0
stopfile = out + ".stop"
STTY = ["stty", "-F", port, "115200", "cs8", "-cstopb", "-parenb", "-crtscts", "-ixon", "-ixoff", "raw", "-echo"]


def log(f, msg):
    f.write((msg + "\n").encode())
    f.flush()


def open_port(f, tsf):
    while True:
        if os.path.exists(stopfile):
            return None
        try:
            fd = os.open(port, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as e:
            log(f, "[capture] open {} failed: {} - retrying".format(port, e))
            time.sleep(1.0)
            continue
        subprocess.run(STTY, capture_output=True)
        log(f, "[capture] {} open (stty 115200 8N1 raw)".format(port))
        tsf.write("[capture] reopened {}\n".format(port).encode())
        return fd


t0 = time.time()
first = True
with open(out, "ab", buffering=0) as f, open(out + ".ts", "ab", buffering=0) as tsf:
    log(f, "\n===== capture start {}  port={} 8N1 115200 =====".format(time.ctime(), port))
    tsf.write("capture start {}\n".format(time.ctime()).encode())
    while (time.time() - t0) < duration and not os.path.exists(stopfile):
        fd = open_port(f, tsf)
        if fd is None:
            break
        while (time.time() - t0) < duration and not os.path.exists(stopfile):
            try:
                r, _, _ = select.select([fd], [], [], 0.2)
            except OSError as e:
                log(f, "[capture] select error: {} - reopening".format(e))
                break
            if not r:
                continue
            try:
                data = os.read(fd, 8192)
            except OSError as e:
                log(f, "[capture] read error: {} - reopening".format(e))
                break
            if not data:
                continue
            if first:
                first = False
                tsf.write("first byte at {} (t+{:.2f}s)\n".format(time.ctime(), time.time() - t0).encode())
            f.write(data)
            preview = data[:80].replace(b"\r", b"").replace(b"\n", b"|").decode("latin-1")
            tsf.write("{} +{:.2f}s {} bytes: {}\n".format(time.ctime(), time.time() - t0, len(data), preview).encode())
            tsf.flush()
        try:
            os.close(fd)
        except OSError:
            pass
        time.sleep(0.5)
    log(f, "\n===== capture end {} =====".format(time.ctime()))
    tsf.write("capture end {}\n".format(time.ctime()).encode())
