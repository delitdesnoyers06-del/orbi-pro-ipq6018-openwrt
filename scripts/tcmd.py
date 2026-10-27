#!/usr/bin/env python3
# Part of the Orbi Pro (IPQ6018) open-firmware porting toolkit - see ../GUIDE.md
# and ../GOTCHAS.md.  Generic: no site-specific addresses, keys or credentials.
"""CLI: tcmd.py "<command>" [timeout] [host] [port]"""
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import orbi_tcp

cmd = sys.argv[1]
timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
host = sys.argv[3] if len(sys.argv) > 3 else orbi_tcp.HOST
port = int(sys.argv[4]) if len(sys.argv) > 4 else orbi_tcp.PORT

print(orbi_tcp.run(cmd, timeout, host, port))
