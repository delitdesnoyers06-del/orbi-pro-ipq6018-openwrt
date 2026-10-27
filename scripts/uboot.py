#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""Catch the U-Boot prompt across a reboot and dump its environment (READ-ONLY).

The Orbi's APPSBL prints `Hit any key to stop autoboot:  2`, so we reboot the box and spam a
key during that window, then run a read-only command set and (by default) `boot` to resume.

Usage: uboot.py [--cmds "a;b;c"] [--no-boot] [--wait 45] [--port /dev/ttyUSB0]
"""
import argparse
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.dirname(HERE)
DEFAULT_CMDS = ["version", "printenv", "bdinfo", "nand info", "mtdparts", "help"]
PROMPT_RE = re.compile(rb"(IPQ\d*#|U-Boot>\s|DNI>\s|\n=>\s)")
SPAM_STOP = re.compile(rb"(IPQ\d*#|U-Boot>\s|DNI>\s|\n=>\s)")
WINDOW = 600


def current_log():
    with open(os.path.join(DIR, "logs", ".current")) as fh:
        return fh.read().strip()


def read_from(path, offset):
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            return fh.read()
    except OSError:
        return b""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmds", default=";".join(DEFAULT_CMDS))
    ap.add_argument("--sep", default=";", help="command separator in --cmds (values may contain ;)")
    ap.add_argument("--no-boot", action="store_true")
    ap.add_argument("--wait", type=float, default=45.0, help="seconds to spam for the prompt")
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--gap", type=float, default=1.5, help="seconds to wait after each command")
    ap.add_argument("--reboot", default="yes", choices=["yes", "no"],
                    help="send Ctrl-C + reboot over the console first")
    ap.add_argument("--assume-prompt", action="store_true",
                    help="skip detection: the console is already at the U-Boot prompt")
    ap.add_argument("--resume-cmd", default="reset",
                    help="command sent after --cmds when --no-boot is not given (there is no 'boot' "
                         "command on this U-Boot: use reset (default) or 'run bootcmd')")
    args = ap.parse_args()

    log = current_log()
    start = os.path.getsize(log)
    print("[uboot] log={} start_offset={}".format(log, start), flush=True)

    fd = os.open(args.port, os.O_WRONLY | os.O_NOCTTY)

    if args.reboot == "yes":
        for _ in range(2):
            os.write(fd, b"\x03")          # free the console from hyd/led-control
            time.sleep(0.4)
        os.write(fd, b"\r\n")
        time.sleep(0.5)
        os.write(fd, b"reboot\r\n")
        print("[uboot] reboot sent, spamming keys for the autoboot window", flush=True)
        time.sleep(3.0)

    caught = bool(args.assume_prompt)
    deadline = time.time() + args.wait
    while time.time() < deadline and not caught:
        os.write(fd, b" ")
        time.sleep(0.08)
        window = read_from(log, start)
        tail = window[-WINDOW:]
        if b"Hit any key" in window and PROMPT_RE.search(tail):
            caught = True
        elif b"autoboot" in window and PROMPT_RE.search(tail):
            caught = True

    if not caught:
        print("[uboot] prompt NOT caught in {:.0f}s (device booted normally)".format(args.wait))
        os.close(fd)
        print(read_from(log, start).decode("latin-1", "replace")[-2000:])
        return 1

    time.sleep(0.5)
    os.write(fd, b"\r\n")
    time.sleep(0.5)
    print("[uboot] PROMPT CAUGHT - running read-only command set", flush=True)
    for cmd in [c for c in args.cmds.split(args.sep) if c.strip()]:
        os.write(fd, (cmd.strip() + "\r\n").encode())
        time.sleep(args.gap)
    if not args.no_boot:
        os.write(fd, (args.resume_cmd + "\r\n").encode())
        time.sleep(1.0)
    os.close(fd)

    session = read_from(log, start)
    out = os.path.join(DIR, "logs", "uboot-{}.log".format(time.strftime("%Y%m%d-%H%M%S")))
    with open(out, "wb") as fh:
        fh.write(session)
    print("[uboot] saved {}".format(out))
    print(session.decode("latin-1", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
