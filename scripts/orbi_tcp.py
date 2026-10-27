"""Minimal client for the Orbi's telnetd root shell (busybox telnetd -l /bin/sh on port 2323)."""
import os
import re
import socket
import time

HOST = os.environ.get("ORBI_TARGET_IP", "192.168.1.1")
PORT = 2323


def run(cmd, timeout=20.0, host=HOST, port=PORT):
    """Run one command; return its output with echo/marker/negotiation stripped."""
    marker = "TEND{}".format(int(time.time() * 1000) % 1000000)
    done_re = re.compile(r"(?:^|\n)" + marker + r"_\d+")

    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(0.5)
    time.sleep(0.2)
    try:
        sock.recv(8192)
    except socket.timeout:
        pass
    sock.sendall((cmd + "\n").encode("latin-1"))
    sock.sendall(("echo {}_$?\n".format(marker)).encode())

    buf = b""
    text = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk
        text = buf.decode("latin-1").replace("\r\n", "\n").replace("\r", "")
        if done_re.search(text):
            time.sleep(0.2)
            try:
                buf += sock.recv(65536)
            except (socket.timeout, OSError):
                pass
            text = buf.decode("latin-1").replace("\r\n", "\n").replace("\r", "")
            break
    sock.close()

    text = re.sub("[\x00-\x08\x0b-\x1f]", "", text)
    cmdfirst = cmd.strip().splitlines()[0] if cmd.strip() else ""
    kept = []
    for line in text.split("\n"):
        stripped = line.strip()
        if re.match(re.escape(marker) + r"_\d+$", stripped):
            continue
        if marker in stripped and "echo " in stripped:
            continue
        if cmdfirst and stripped == cmdfirst:
            continue
        kept.append(line)
    return "\n".join(kept).strip()
