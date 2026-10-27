#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""Send Ctrl-C (to break out of whatever holds the console) and then a command.
Usage: console_cmd.py "<command>" [port]
at the console and prints the newly captured output.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.dirname(HERE)
port = sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyUSB0"
cmd = sys.argv[1] if len(sys.argv) > 1 else ""

with open(os.path.join(DIR, "logs", ".current")) as fh:
    log = fh.read().strip()
before = os.path.getsize(log)

fd = os.open(port, os.O_WRONLY | os.O_NOCTTY)
for _ in range(3):
    os.write(fd, b"\x03")
    time.sleep(0.35)
os.write(fd, b"\r\n")
time.sleep(0.4)
if cmd:
    os.write(fd, (cmd + "\r\n").encode())
time.sleep(2.0)
os.close(fd)

with open(log, "rb") as fh:
    fh.seek(before)
    data = fh.read()
sys.stdout.write(data.decode("latin-1", "replace").replace("\r", ""))
