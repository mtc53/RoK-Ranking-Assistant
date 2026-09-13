#!/usr/bin/env python3
"""Works out why the War Room site is not reachable, in plain English.

Run this ON the VPS (double-click check.bat). It looks at each thing that
has to be true, in order, and stops at the first one that is not.
"""
from __future__ import annotations

import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORTS = [8081, 443, 80, 8000]


def line(char="-"):
    print(char * 62)


def listening(port: int) -> bool:
    """Is anything accepting connections on this port, locally?"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def http_ok(port: int):
    """Try https first on 443, otherwise plain http. Returns (status, bytes, scheme)."""
    loose = ssl.create_default_context()
    loose.check_hostname = False
    loose.verify_mode = ssl.CERT_NONE
    order = ["https", "http"] if port == 443 else ["http", "https"]
    for scheme in order:
        try:
            ctx = loose if scheme == "https" else None
            with urllib.request.urlopen(f"{scheme}://127.0.0.1:{port}/",
                                        timeout=4, context=ctx) as r:
                return r.status, len(r.read(2048)), scheme
        except urllib.error.HTTPError as e:
            return e.code, 0, scheme
        except Exception:
            continue
    return None, 0, order[0]


def firewall_rules() -> str:
    try:
        out = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "name=all", "dir=in"],
            capture_output=True, text=True, timeout=25,
        )
        return out.stdout or ""
    except Exception:
        return ""


def local_ips() -> list[str]:
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


def main() -> None:
    print()
    line("=")
    print("  KINGDOM WAR ROOM  -  what is wrong?")
    line("=")

    print(f"\n[1] Python            OK  ({sys.version.split()[0]})")

    missing = [f for f in ("index.html", "server.py") if not (HERE / f).is_file()]
    if missing:
        print(f"[2] Files             MISSING: {', '.join(missing)}")
        print("\n  >> Put index.html and server.py in this same folder:")
        print(f"     {HERE}")
        return finish()
    print("[2] Files             OK  (index.html and server.py are here)")

    live = [p for p in PORTS if listening(p)]
    if not live:
        print("[3] Server running    NO")
        print("\n  >> The site is not running on this machine at all.")
        print("     Double-click start.bat and LEAVE the black window open.")
        print("     If it closes instantly, run it and read the message.")
        return finish()

    port = live[0]
    print(f"[3] Server running    OK  (listening on port {port})")

    status, size, scheme = http_ok(port)
    if status != 200:
        print(f"[4] Page loads        NO  (got {status or 'no response'})")
        print("\n  >> Something is on the port but it is not the War Room.")
        print("     On a Windows VPS that is usually IIS holding port 80.")
        print("     Stop IIS, or run:   start.bat 8000")
        return finish()
    print(f"[4] Page loads        OK  ({size} bytes over {scheme})")
    if scheme == "http" and port != 443:
        print("                          (not encrypted - normal; see README.txt)")

    rules = firewall_rules()
    allowed = f"LocalPort:                            {port}" in rules.replace("\r", "")
    named = "Kingdom War Room" in rules or "Alliance War Room" in rules
    if not (allowed or named):
        print(f"[5] Windows firewall  NOT OPEN for port {port}")
        print("\n  >> This is almost certainly your problem.")
        print("     Right-click open-firewall.bat -> Run as administrator")
        if port != 80:
            print(f"     (then run it again as:  open-firewall.bat {port})")
    else:
        print(f"[5] Windows firewall  looks open for port {port}")
        print("\n  >> Everything on THIS machine is fine, so the block is")
        print("     outside it - your VPS provider's own firewall.")
        print("     Log in to your VPS control panel and allow inbound")
        print(f"     TCP port {port}. On Solid VPS look for Firewall,")
        print("     Network Rules or Security Group.")

    ips = local_ips()
    print()
    line()
    if ips:
        shown = "" if port in (80, 443) else f":{port}"
        print("  Once open, your site address is:")
        for ip in ips:
            print(f"      {scheme}://{ip}{shown}")
        print("\n  (If that is a private address like 10.x or 192.168.x,")
        print("   use the public IP shown in your VPS control panel.)")
    finish()


def finish() -> None:
    print()
    line("=")
    input("  Press Enter to close...")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n  The check itself failed: {exc}")
        finish()
