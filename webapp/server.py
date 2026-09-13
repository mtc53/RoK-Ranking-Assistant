#!/usr/bin/env python3
"""Tiny server for hosting the Kingdom War Room yourself.

Serves index.html and stores what the page saves, so every R5 who opens the
site sees the same weeks. Standard library only - no packages to install.

    python server.py            # http://localhost  (port 80)
    python server.py 9000       # a different port
    python server.py http       # force plain http even with a certificate

What it keeps, next to this file:
    state.json          everything the page has saved
    state.json.bak      the save before this one
    backups/            the last 10 saves, oldest pruned automatically
    uploads/            each week's original .xlsx, written out as it arrives
    password.txt        OPTIONAL - the password needed to change anything
    .secret             random bytes used to sign login cookies

With no password.txt anybody who can open the page can change the rankings.
Put a password in it and the site is read-only until someone logs in; reading
stays open so officers can be sent a link. Add an empty private.txt as well
if even reading should need the password. Both files are read once at
startup, so restart after changing them.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import os
import re
import secrets
import ssl
import sys
import threading
import time
from functools import lru_cache
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"
STATE = HERE / "state.json"
BACKUP = HERE / "state.json.bak"
BACKUPS = HERE / "backups"
UPLOADS = HERE / "uploads"
SECRET_FILE = HERE / ".secret"
PASSWORD_FILE = HERE / "password.txt"
PRIVATE_FILE = HERE / "private.txt"

MAX_BODY = 64 * 1024 * 1024
DRAIN_LIMIT = 4 * 1024 * 1024
KEEP_BACKUPS = 10
SESSION_DAYS = 30
MAX_CONNECTIONS = 96
PER_VISITOR = 16
IDLE_TIMEOUT = 20
WRITES_PER_MINUTE = 30
LOGIN_TRIES = 10
LOGIN_LOCKOUT = 15 * 60
COOKIE = "warroom"
LOCAL = {"127.0.0.1", "::1"}

LOCK = threading.RLock()


def read_state() -> dict:
    for path in (STATE, BACKUP):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            if path is BACKUP:
                sys.stderr.write(
                    "  state.json was unreadable - fell back to state.json.bak\n")
            return data
    return {}


def write_state(payload: dict) -> int:
    """Write to a temporary file and rename it over the real one, so a crash
    mid-save leaves either the old state or the new one, never half of each."""
    with LOCK:
        payload["_rev"] = int(read_state().get("_rev", 0)) + 1
        tmp = STATE.with_name("state.json.new")
        text = json.dumps(payload)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if STATE.is_file():
            os.replace(STATE, BACKUP)
        os.replace(tmp, STATE)
        _snapshot(text, payload["_rev"])
        return payload["_rev"]


def _snapshot(text: str, rev: int) -> None:
    try:
        BACKUPS.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (BACKUPS / f"state-{stamp}-{rev:06d}.json").write_text(text, encoding="utf-8")
        for old in sorted(BACKUPS.glob("state-*.json"))[:-KEEP_BACKUPS]:
            old.unlink(missing_ok=True)
    except OSError as exc:
        sys.stderr.write(f"  (could not write a backup copy: {exc})\n")


def valid_state(payload) -> bool:
    """Checked before anything is written, so bad input cannot replace good."""
    if not isinstance(payload, dict) or not isinstance(payload.get("weeks"), list):
        return False
    return all(isinstance(w, dict) for w in payload["weeks"])


def safe_name(text: str) -> str:
    """A filename that cannot escape the uploads folder."""
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(text)).strip(". ")
    return (cleaned or "week")[:80]


def sync_uploads(payload: dict, previous: dict) -> dict:
    """Write each week's workbook to uploads/ and leave a reference behind.

    The page sends a workbook as base64 the first time and only its hash
    afterwards, so a season of sheets is not re-uploaded to change one week.
    Returns the hash each week was stored under, which is what lets the page
    refer to it next time.
    """
    known = {}
    for week in previous.get("weeks", []):
        info = week.get("file") or {}
        if info.get("sha") and info.get("stored"):
            known[info["sha"]] = info["stored"]

    taken, held, by_digest = set(), {}, {}
    for week in payload.get("weeks", []):
        info = week.get("file")
        if not isinstance(info, dict):
            week["file"] = None
            continue

        raw = info.pop("b64", None)
        data = None
        if raw:
            try:
                data = base64.b64decode(raw, validate=True)
            except (ValueError, TypeError):
                data = None
        digest = (hashlib.sha256(data).hexdigest() if data is not None
                  else str(info.get("sha") or ""))
        if not digest:
            week["file"] = None
            continue

        base = safe_name(week.get("label")
                         or Path(str(info.get("name") or "week")).stem)
        wanted = f"{base}.xlsx"
        if wanted in taken:
            wanted = f"{base}-{digest[:8]}.xlsx"
        stored = by_digest.get(digest) or known.get(digest, wanted)

        if digest not in by_digest and stored != wanted                 and wanted not in taken and not (UPLOADS / wanted).is_file():
            try:
                if (UPLOADS / stored).is_file():
                    os.replace(UPLOADS / stored, UPLOADS / wanted)
                stored = wanted
            except OSError:
                pass

        target = UPLOADS / stored
        if data is not None and not target.is_file():
            UPLOADS.mkdir(exist_ok=True)
            target.write_bytes(data)
        if not target.is_file():
            week["file"] = None
            continue

        week["file"] = {"name": info.get("name") or stored, "sha": digest,
                        "size": target.stat().st_size, "stored": stored}
        by_digest[digest] = stored
        taken.add(stored)
        held[str(week.get("id"))] = digest

    _sweep(taken)
    return held


def _sweep(keep: set) -> None:
    """Removed and renamed weeks would otherwise leave sheets behind forever."""
    if not UPLOADS.is_dir():
        return
    for path in UPLOADS.glob("*.xlsx"):
        if path.name not in keep:
            try:
                path.unlink()
            except OSError:
                pass


def hydrate(state: dict) -> dict:
    """Put the archived workbooks back into the state the page receives."""
    out = dict(state)
    out.pop("_rev", None)
    weeks = []
    for week in state.get("weeks", []):
        info = week.get("file") or {}
        stored = info.get("stored")
        if stored:
            week = dict(week)
            path = UPLOADS / stored
            week["file"] = (dict(info, b64=base64.b64encode(path.read_bytes()).decode())
                            if path.is_file() else None)
        weeks.append(week)
    out["weeks"] = weeks
    return out


@lru_cache(maxsize=1)
def password():
    env = os.environ.get("WARROOM_PASSWORD")
    if env and env.strip():
        return env.strip()
    try:
        lines = PASSWORD_FILE.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return None
    return lines[0].strip() if lines and lines[0].strip() else None


@lru_cache(maxsize=1)
def secret() -> bytes:
    """Signing key for cookies, kept on disk so logins survive a restart."""
    with LOCK:
        try:
            raw = SECRET_FILE.read_text(encoding="utf-8").strip()
            if len(raw) >= 32:
                return raw.encode()
        except OSError:
            pass
        raw = secrets.token_hex(32)
        try:
            SECRET_FILE.write_text(raw, encoding="utf-8")
            if os.name != "nt":
                os.chmod(SECRET_FILE, 0o600)
        except OSError:
            pass
        return raw.encode()


def make_token() -> str:
    body = f"v1.{int(time.time()) + SESSION_DAYS * 86400}"
    return f"{body}.{hmac.new(secret(), body.encode(), hashlib.sha256).hexdigest()}"


def token_ok(token) -> bool:
    try:
        version, expiry, sig = str(token).split(".")
    except ValueError:
        return False
    good = hmac.new(secret(), f"{version}.{expiry}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        return int(expiry) > time.time()
    except ValueError:
        return False


class Limiter:
    """Recent attempts per address, for wrong passwords and floods of saves."""

    def __init__(self):
        self.hits = {}
        self.lock = threading.Lock()

    def hit(self, who: str, window: float) -> int:
        now = time.time()
        with self.lock:
            recent = [t for t in self.hits.get(who, []) if now - t < window]
            recent.append(now)
            self.hits[who] = recent
            if len(self.hits) > 2000:
                self.hits = {k: v for k, v in self.hits.items()
                             if v and now - v[-1] < window}
            return len(recent)

    def count(self, who: str, window: float) -> int:
        now = time.time()
        with self.lock:
            return len([t for t in self.hits.get(who, []) if now - t < window])

    def clear(self, who: str) -> None:
        with self.lock:
            self.hits.pop(who, None)


LOGINS = Limiter()
WRITES = Limiter()


class Handler(BaseHTTPRequestHandler):
    """Serves the page, the state API and the login, and nothing else.

    Serving the folder - what SimpleHTTPRequestHandler would do - also hands
    out state.json, the uploads, the log and the certificate's private key.
    """

    server_version = "WarRoom"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = IDLE_TIMEOUT
    _read_body = False

    junk = 0

    def _is_junk(self, text: str) -> bool:
        return not all(32 <= ord(c) < 127 or c in "\t" for c in text[:200])

    def log_message(self, fmt, *args):
        try:
            msg = fmt % args
        except Exception:
            return
        if not self._is_junk(msg):
            sys.stderr.write("%s %s\n" % (self.address_string(), msg))

    def log_error(self, fmt, *args):
        try:
            msg = fmt % args
        except Exception:
            return
        if "timed out" in msg:
            return
        if any(p in msg for p in ("Bad request", "Bad HTTP", "Request line")) \
                or self._is_junk(msg):
            Handler.junk += 1
            if Handler.junk in (1, 10) or Handler.junk % 100 == 0:
                sys.stderr.write(f"  ({Handler.junk} ignored probes from the "
                                 f"internet - normal, nothing to do)\n")
            return
        sys.stderr.write("%s %s\n" % (self.address_string(), msg))

    def handle_one_request(self):
        self._read_body = False
        super().handle_one_request()

    def _peer(self) -> str:
        return self.client_address[0] if self.client_address else "?"

    def _who(self) -> str:
        """The visitor, as seen through a reverse proxy on this machine.

        Behind a proxy every request arrives from loopback, so the connection
        cap, the save rate limit and the login lockout would otherwise apply
        to everyone at once. The forwarded address is only believed when the
        connection really did come from this machine.
        """
        peer = self._peer()
        if peer in LOCAL:
            sent = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if sent:
                return sent
        return peer

    def _secure(self) -> bool:
        if isinstance(self.server, TLSServer):
            return True
        if self._peer() in LOCAL:
            proto = (self.headers.get("X-Forwarded-Proto") or "").strip().lower()
            return proto == "https"
        return False

    def _drain(self) -> None:
        """Read an upload we are about to refuse.

        Answering while the browser is still sending aborts the connection,
        and the browser then reports a network error instead of the reason we
        sent - so "log in" would never be seen.
        """
        if self._read_body or self.command not in ("PUT", "POST"):
            return
        self._read_body = True
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if length > DRAIN_LIMIT:
            self.close_connection = True
        left = min(length, DRAIN_LIMIT)
        while left > 0:
            piece = self.rfile.read(min(left, 1 << 16))
            if not piece:
                return
            left -= len(piece)

    def _send(self, code: int, body: bytes, ctype: str, extra=()) -> None:
        self._drain()
        encoding = None
        if len(body) > 1400 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body, encoding = gzip.compress(body, 6), "gzip"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, payload, extra=()) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json",
                   [("Cache-Control", "no-store"), *extra])

    def _fail(self, code: int, message: str) -> None:
        self._json(code, {"error": message})

    def _logged_in(self) -> bool:
        if not password():
            return True
        raw = self.headers.get("Cookie")
        if not raw:
            return False
        try:
            morsel = SimpleCookie(raw).get(COOKIE)
        except Exception:
            return False
        return bool(morsel and token_ok(morsel.value))

    def _auth_state(self) -> str:
        if not password():
            return "off"
        return "ok" if self._logged_in() else "required"


    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in ("/", "/index.html"):
            return self._page()
        if path == "/api/state":
            return self._get_state()
        if self.path.startswith("/.well-known/acme-challenge/"):
            return self._acme()
        self._fail(404, "no such page")

    do_HEAD = do_GET

    def _page(self):
        if not INDEX.is_file():
            return self._fail(500, "index.html is missing from the server folder")
        stat = INDEX.stat()
        tag = f'W/"{int(stat.st_mtime)}-{stat.st_size}"'
        if self.headers.get("If-None-Match") == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        csp = ("default-src 'self'; img-src 'self' data:; "
               "script-src 'self' 'unsafe-inline'; "
               "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
               "font-src 'self' https://fonts.gstatic.com; "
               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8",
                   [("Cache-Control", "no-cache"), ("ETag", tag),
                    ("Content-Security-Policy", csp)])

    def _acme(self):
        """Certificate renewal fetches a file from here over plain http."""
        name = Path(self.path.split("?")[0]).name
        token = HERE / ".well-known" / "acme-challenge" / name
        if ".." in self.path or not token.is_file():
            return self._fail(404, "no such token")
        self._send(200, token.read_bytes(), "text/plain")

    def _get_state(self):
        if PRIVATE_FILE.is_file() and not self._logged_in():
            return self._fail(401, "log in to see this kingdom's data")
        with LOCK:
            state = read_state()
            body = hydrate(state) if state else {}
        self._json(200, body, [("X-WarRoom-Rev", str(state.get("_rev", 0))),
                               ("X-WarRoom-Auth", self._auth_state())])

    def do_POST(self):
        if (self.path.split("?")[0].rstrip("/") or "/") != "/api/login":
            return self._fail(404, "no such page")
        self._login()

    def _cookie(self, value: str, age: int) -> str:
        bits = [f"{COOKIE}={value}", "Path=/", f"Max-Age={age}",
                "HttpOnly", "SameSite=Strict"]
        if self._secure():
            bits.append("Secure")
        return "; ".join(bits)

    def _login(self):
        want = password()
        if not want:
            return self._json(200, {"ok": True, "auth": "off"})
        who = self._who()
        if LOGINS.count(who, LOGIN_LOCKOUT) >= LOGIN_TRIES:
            return self._fail(429, "too many wrong passwords - wait 15 minutes")
        body = self._body()
        if body is None:
            return
        given = ""
        try:
            given = str(json.loads(body).get("password") or "")
        except (ValueError, AttributeError, UnicodeDecodeError):
            pass
        if not hmac.compare_digest(given, want):
            LOGINS.hit(who, LOGIN_LOCKOUT)
            time.sleep(0.5)
            return self._fail(401, "wrong password")
        LOGINS.clear(who)
        self._json(200, {"ok": True, "auth": "ok"},
                   [("Set-Cookie", self._cookie(make_token(), SESSION_DAYS * 86400))])

    def _body(self):
        """Exactly Content-Length bytes, or None having already answered."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length <= 0:
            self._fail(400, "no body")
            return None
        if length > MAX_BODY:
            self.close_connection = True
            self._fail(413, "body too large")
            return None
        self._read_body = True
        chunks, left = [], length
        while left > 0:
            piece = self.rfile.read(min(left, 1 << 20))
            if not piece:
                break
            chunks.append(piece)
            left -= len(piece)
        data = b"".join(chunks)
        if len(data) != length:
            self.close_connection = True
            self._fail(400, "the upload stopped early")
            return None
        return data

    def do_PUT(self):
        if (self.path.split("?")[0].rstrip("/") or "/") != "/api/state":
            return self._fail(404, "no such page")
        if not self._logged_in():
            return self._fail(401, "log in before saving")
        if WRITES.hit(self._who(), 60) > WRITES_PER_MINUTE:
            return self._fail(429, "saving too often - try again shortly")

        body = self._body()
        if body is None:
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._fail(400, "not valid JSON")
        if not valid_state(payload):
            return self._fail(400, "that is not a War Room state")

        with LOCK:
            current = read_state()
            rev = int(current.get("_rev", 0))
            sent = (self.headers.get("If-Match") or "").strip('" ')
            if sent.isdigit() and int(sent) != rev:
                return self._json(409, {"error": "someone else saved first",
                                        "rev": rev})
            held = sync_uploads(payload, current)
            new_rev = write_state(payload)
        self._json(200, {"ok": True, "rev": new_rev,
                         "weeks": len(payload.get("weeks", [])),
                         "sheets": len(held), "files": held},
                   [("X-WarRoom-Rev", str(new_rev))])


class Server(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._open = {}
        self._owner = {}
        self._books = threading.Lock()

    def process_request(self, request, client_address):
        who = client_address[0] if client_address else "?"
        with self._books:
            if (self._open.get(who, 0) >= PER_VISITOR
                    or sum(self._open.values()) >= MAX_CONNECTIONS):
                self.close_request(request)
                return
            self._open[who] = self._open.get(who, 0) + 1
            self._owner[request] = who
        try:
            super().process_request(request, client_address)
        except Exception:
            self._release(request)
            raise

    def _release(self, request) -> None:
        with self._books:
            who = self._owner.pop(request, None)
            if who is None:
                return
            if self._open.get(who, 1) > 1:
                self._open[who] -= 1
            else:
                self._open.pop(who, None)

    def shutdown_request(self, request):
        try:
            super().shutdown_request(request)
        finally:
            self._release(request)

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError, ssl.SSLError)):
            return
        super().handle_error(request, client_address)


class TLSServer(Server):
    """Wraps each connection as it arrives rather than the listening socket
    once, so a certificate renewal is picked up without a restart."""

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
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
                ctx.load_cert_chain(str(self.cert), str(self.key))
                self._ctx, self._stamp = ctx, stamp
            return self._ctx

    def get_request(self):
        sock, addr = self.socket.accept()
        try:
            sock.settimeout(IDLE_TIMEOUT)
            return self._context().wrap_socket(sock, server_side=True), addr
        except (ssl.SSLError, OSError):
            sock.close()
            raise BlockingIOError


class RedirectHandler(Handler):
    """Port 80 once https is confirmed working: renewals stay on http,
    everything else is bounced across."""

    def do_GET(self):
        if self.path.startswith("/.well-known/acme-challenge/"):
            return self._acme()
        host = (self.headers.get("Host") or "").split(":")[0]
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host or ""):
            return self._fail(400, "bad host")
        self._send(301, b"", "text/plain", [("Location", f"https://{host}{self.path}")])

    do_HEAD = do_GET
    do_PUT = do_POST = do_GET


def find_cert():
    """cert.pem/key.pem, or win-acme's own naming so renewals are picked up."""
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


def bind(cls, port, *args, fatal=True):
    try:
        return cls(("0.0.0.0", port), *args)
    except OSError:
        if not fatal:
            return None
        print(f"\n  Port {port} is already being used on this machine.\n")
        print("  Either the War Room is already running (check for another")
        print("  black window), or something else - often IIS on port 80 -")
        print("  has it. Pick a different port, for example:\n")
        print("      start.bat 8000\n")
        sys.exit(1)


def start(cert, key, ports):
    """Which ports to listen on, as (scheme, port, server).

    Port 80 always means the plain site, given or defaulted, so asking for it
    never puts https where browsers expect http.
    """
    port = int(ports[0]) if ports else 80
    if port != 80:
        if cert:
            return [("https", port, bind(TLSServer, port, Handler, cert, key))]
        return [("http", port, bind(Server, port, Handler))]
    if not cert:
        return [("http", 80, bind(Server, 80, Handler))]

    running = []
    tls = bind(TLSServer, 443, Handler, cert, key, fatal=False)
    if tls:
        running.append(("https", 443, tls))
    else:
        print("  (port 443 is busy - carrying on without encryption)")
    redirect = tls and (HERE / "redirect-to-https.txt").is_file()
    plain = bind(Server, 80, RedirectHandler if redirect else Handler, fatal=not tls)
    if plain:
        running.append(("http", 80, plain))
    elif tls:
        print("  (port 80 is busy - certificate renewal may fail)")
    return running


def announce(servers, cert):
    scheme, port, _ = servers[0]
    def shown(p):
        return "" if p in (80, 443) else f":{p}"
    print(f"Kingdom War Room  ->  {scheme}://localhost{shown(port)}")
    print(f"  serving   {INDEX}")
    print(f"  state     {STATE}")
    print(f"  uploads   {UPLOADS}")
    print(f"  backups   {BACKUPS}")
    for other_scheme, other_port, _ in servers[1:]:
        print(f"  also on   {other_scheme}://localhost{shown(other_port)}")
    if cert:
        print(f"  encrypted using {cert.name}")
    else:
        print("  plain http (not encrypted) - this is the normal setup")
    if password():
        where = "WARROOM_PASSWORD" if os.environ.get("WARROOM_PASSWORD") else "password.txt"
        print(f"  password  needed before anything can be changed (from {where})")
        if PRIVATE_FILE.is_file():
            print("            and needed to view the data at all")
    else:
        print("  password  NOT SET - anyone who can open the page can change")
        print("            the rankings. Put one in password.txt if this")
        print("            machine is reachable from the internet.")
    print("  Ctrl+C to stop")


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    args = list(sys.argv[1:])
    force_http = any(a.lower() in ("http", "--http", "-http") for a in args)
    cert, key = (None, None) if force_http else find_cert()

    servers = [s for s in start(cert, key, [a for a in args if a.isdigit()]) if s[2]]
    if not servers:
        sys.exit("  nothing could be started - every port was busy")
    for _, _, srv in servers[1:]:
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    announce(servers, cert)
    try:
        servers[0][2].serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
