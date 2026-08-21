#!/usr/bin/env python3
"""Tiny server for hosting the Kingdom War Room yourself.

Serves index.html and stores what the page saves, so every R5 who opens the
site sees the same weeks. Standard library only - no packages to install.

    python server.py            # http://localhost  (port 80)
    python server.py 9000       # a different port
    python server.py http       # force plain http even with a certificate

What it keeps, next to this file:
    state.json          everything the page has saved
    uploads/            each week's original .xlsx, written out as it arrives

Hosting it for real:
  - Run it behind nginx/Apache as a reverse proxy, or run it on a VPS and open
    the port. Put it behind your own login if the internet can reach it -
    there is deliberately no auth here, so anyone who can open the page can
    change the rankings.
  - Static-only hosting (GitHub Pages, S3) works too: upload just index.html.
    The page then saves into each person's own browser instead, and they move
    data around with the Download backup / Restore backup buttons.
"""
from __future__ import annotations

import base64
import json
import re
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "state.json"
UPLOADS = HERE / "uploads"
MAX_BODY = 64 * 1024 * 1024


def find_cert():
    """Locate the certificate, however it happens to be named.

    HTTPS stays OFF unless a file called https-on.txt sits next to this one.
    Without that guard a certificate-renewal tool could drop new .pem files
    into the folder months from now and silently switch the site to https,
    which then fails for everyone if port 443 is not open.

    With the guard on: cert.pem / key.pem win if present, otherwise win-acme's
    own naming is accepted so renewals are picked up without renaming. A full
    chain is preferred - some browsers reject a bare certificate.
    """
    if not (HERE / "https-on.txt").is_file():
        return None, None
    if (HERE / "cert.pem").is_file() and (HERE / "key.pem").is_file():
        return HERE / "cert.pem", HERE / "key.pem"
    keys = sorted(HERE.glob("*-key.pem"), key=lambda p: p.stat().st_mtime, reverse=True)
    for key in keys:
        stem = key.name[: -len("-key.pem")]
        for suffix in ("-crt-chain.pem", "-chain.pem", "-crt.pem", ".pem"):
            cert = HERE / (stem + suffix)
            if cert.is_file() and cert != key:
                return cert, key
    return None, None


def safe_name(text: str) -> str:
    """A filename that cannot escape the uploads folder."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(text)).strip(". ")
    return (cleaned or "week")[:80]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    # Anything on a public port gets probed by bots within minutes, and an
    # https:// request to this http:// server arrives as a page of binary
    # rubbish. None of it matters, and all of it makes the window unreadable,
    # so junk is counted quietly instead of printed.
    junk = 0

    def _is_junk(self, text: str) -> bool:
        return not all(32 <= ord(c) < 127 or c in "\t" for c in text[:200])

    def log_message(self, fmt, *args):
        try:
            msg = fmt % args
        except Exception:
            return
        if self._is_junk(msg):
            return          # counted once in log_error, not twice
        sys.stderr.write("%s %s\n" % (self.address_string(), msg))

    def log_error(self, fmt, *args):
        try:
            msg = fmt % args
        except Exception:
            return
        if "Bad request" in msg or "Bad HTTP" in msg or self._is_junk(msg):
            Handler.junk += 1
            if Handler.junk in (1, 10) or Handler.junk % 100 == 0:
                sys.stderr.write(
                    f"  ({Handler.junk} ignored probes from the internet - "
                    f"normal, nothing to do)\n")
            return
        sys.stderr.write("%s %s\n" % (self.address_string(), msg))

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/api/state") or self.path == "/api/state":
            if STATE.is_file():
                try:
                    return self._json(200, json.loads(STATE.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    pass
            # 200 with nothing in it: the page needs to know a server IS here.
            return self._json(200, {})
        return super().do_GET()

    def do_PUT(self):
        if not (self.path == "/api/state" or self.path.endswith("/api/state")):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._json(413, {"error": "body too large"})
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return self._json(400, {"error": "not valid JSON"})

        STATE.write_text(json.dumps(payload), encoding="utf-8")
        written = self._write_uploads(payload)
        self._json(200, {"ok": True, "weeks": len(payload.get("weeks", [])),
                         "sheets": written})

    def _write_uploads(self, payload) -> int:
        """Drop each archived workbook onto disk as a real .xlsx."""
        count = 0
        for week in payload.get("weeks", []):
            info = week.get("file")
            if not info or not info.get("b64"):
                continue
            UPLOADS.mkdir(exist_ok=True)
            name = safe_name(week.get("label") or Path(info.get("name", "week")).stem)
            target = UPLOADS / f"{name}.xlsx"
            try:
                data = base64.b64decode(info["b64"])
            except (ValueError, TypeError):
                continue
            if not target.is_file() or target.read_bytes() != data:
                target.write_bytes(data)
            count += 1
        return count


class Server(ThreadingHTTPServer):
    # Windows would otherwise happily start a SECOND copy on a port that is
    # already in use - it binds, then quietly receives nothing. Better to
    # fail loudly and tell the user the port is taken.
    allow_reuse_address = False


class TLSServer(Server):
    """HTTPS, with the certificate re-read whenever it changes on disk.

    Certificates last 90 days and are renewed by a background task. Wrapping
    each connection as it arrives - rather than the listening socket once at
    startup - means a renewal is picked up without restarting anything.
    """

    def __init__(self, addr, handler, cert, key):
        super().__init__(addr, handler)
        self.cert, self.key = cert, key
        self._stamp = None
        self._ctx = None
        self._lock = threading.Lock()

    def _context(self):
        stamp = (self.cert.stat().st_mtime, self.key.stat().st_mtime)
        with self._lock:
            if stamp != self._stamp or self._ctx is None:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(str(self.cert), str(self.key))
                self._ctx, self._stamp = ctx, stamp
            return self._ctx

    def get_request(self):
        sock, addr = self.socket.accept()
        try:
            return self._context().wrap_socket(sock, server_side=True), addr
        except (ssl.SSLError, OSError):
            sock.close()                      # a probe, or plain http on 443
            raise BlockingIOError


class RedirectHandler(BaseHTTPRequestHandler):
    """Port 80 once HTTPS is on: renewal checks, then send everyone to https."""

    def do_GET(self):
        # Let's Encrypt proves the domain is yours by fetching a file from
        # here, so this path must keep working over plain http.
        if self.path.startswith("/.well-known/acme-challenge/"):
            name = Path(self.path.split("?")[0]).name
            token = HERE / ".well-known" / "acme-challenge" / name
            if token.is_file() and ".." not in self.path:
                body = token.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        host = (self.headers.get("Host") or "").split(":")[0]
        self.send_response(301)
        self.send_header("Location", f"https://{host}{self.path}")
        self.end_headers()

    do_HEAD = do_GET

    def log_message(self, fmt, *args):
        pass                                   # the https side does the logging

    def log_error(self, fmt, *args):
        pass


def bind(cls, port, *args):
    try:
        return cls(("0.0.0.0", port), *args)
    except OSError:
        print(f"\n  Port {port} is already being used on this machine.\n")
        print("  Either the War Room is already running (check for another")
        print("  black window), or something else - often IIS on port 80 -")
        print("  has it. Pick a different port, for example:\n")
        print("      start.bat 8000\n")
        sys.exit(1)


def main() -> None:
    # When this runs as a startup task its output goes to a file, and block
    # buffering would hold messages back for ages. Keep it line by line.
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    args = [a for a in sys.argv[1:]]
    # "server.py http" forces plain http even when a certificate is present.
    force_http = any(a.lower() in ("http", "--http", "-http") for a in args)
    args = [a for a in args if a.isdigit()]

    cert, key = find_cert()
    if force_http:
        cert = key = None
    default_port = 443 if cert else 80
    port = int(args[0]) if args else default_port

    if cert:
        server = bind(TLSServer, port, Handler, cert, key)
        scheme = "https"
        # Port 80 stays up for renewals and to bounce http visitors across.
        # If it is unavailable that is a nuisance, not a reason to stop.
        if port == 443:
            try:
                redirect = Server(("0.0.0.0", 80), RedirectHandler)
                threading.Thread(target=redirect.serve_forever, daemon=True).start()
                print("  http on port 80 redirects to https")
            except OSError:
                print("  (port 80 is busy - http visitors will not be redirected,")
                print("   and certificate renewal may fail)")
    else:
        server = bind(Server, port, Handler)
        scheme = "http"

    shown = "" if port in (80, 443) else f":{port}"
    print(f"Kingdom War Room  ->  {scheme}://localhost{shown}")
    print(f"  serving   {HERE}")
    print(f"  state     {STATE}")
    print(f"  uploads   {UPLOADS}")
    if cert:
        print(f"  encrypted using {cert.name}")
    else:
        print("  plain http (not encrypted) - this is the normal setup")
    print("  Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
