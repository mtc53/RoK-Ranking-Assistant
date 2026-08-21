#!/usr/bin/env python3
"""Files a new activity export and pushes it to the War Room site.

Drop the spreadsheet the Discord bot sends you into inbox\\ and run this. It
works out which week the scan belongs to, files it under "Alliance Activity"
so the local rank.py sees it too, and updates that week on the website.

    python ingest.py                        # the site named in server.txt
    python ingest.py --url http://1.2.3.4   # somewhere else, just this once
    python ingest.py --dry-run              # say what would happen, do nothing

The site is usually on another machine, so its address lives in server.txt
next to this file. A password, if the site has one, comes from password.txt
or the WARROOM_PASSWORD variable.

A fresher scan of a week already on the site replaces it, so dropping a sheet
in daily keeps the current week's numbers fresh instead of piling up entries.
"""
from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webapp"))

from rok_ranker.parse import ParseError, parse_week      # noqa: E402
from build import PACK_FIELDS                            # noqa: E402

# The game's week turns over at 00:00 UTC on Monday. Timestamps in the export
# are already UTC, so they compare against it directly - nothing shifts when
# the clocks change.
DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6}


def log(message: str = "") -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}" if message else "")


def die(message: str) -> None:
    log(f"STOPPED: {message}")
    sys.exit(1)


# ------------------------------------------------------------------ weeks

def window(moment: datetime, start_day: int):
    """The seven days a scan belongs to, as (first, last) dates."""
    back = (moment.weekday() - start_day) % 7
    first = moment.date() - timedelta(days=back)
    return first, first + timedelta(days=6)


def label_for(first, last) -> str:
    if first.month == last.month:
        return f"{first.day}-{last.day} {first:%B}"
    return f"{first.day} {first:%B} - {last.day} {last:%B}"


def scan_of(week: dict) -> datetime | None:
    raw = str(week.get("scanDate") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def pack(week: dict, label: str, sheet: Path | None, week_id: str) -> dict:
    entry = {
        "id": week_id,
        "label": label,
        "scanDate": week["scan_date"].isoformat() + "Z",
        "summaries": week["summaries"],
        "cols": PACK_FIELDS,
        "rows": [[None if f == "last_login" else m.get(f) for f in PACK_FIELDS]
                 for m in week["members"]],
        "file": None,
    }
    if sheet is not None:
        entry["file"] = {"name": sheet.name,
                         "b64": base64.b64encode(sheet.read_bytes()).decode()}
    return entry


def slim(state: dict, keep_id: str) -> None:
    """Refer to workbooks the server already holds instead of re-sending them."""
    for week in state.get("weeks", []):
        info = week.get("file")
        if week.get("id") != keep_id and isinstance(info, dict) and info.get("sha"):
            week["file"] = {"name": info.get("name"), "sha": info["sha"]}


def merge(state: dict, entry: dict, span, start_day: int) -> dict:
    """Put the week in, replacing whatever already covers the same days."""
    weeks = [w for w in (state.get("weeks") or [])
             if w.get("id") != entry["id"]
             and window(scan_of(w) or datetime.min, start_day) != span]
    weeks.append(entry)
    state["weeks"] = weeks
    state.setdefault("version", 1)
    slim(state, entry["id"])
    return state


# ------------------------------------------------------------ the website

class Site:
    def __init__(self, url: str, password: str | None):
        self.url = url.rstrip("/")
        self.password = password
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.rev = "0"

    def _call(self, path, method="GET", body=None, headers=None, timeout=120):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers=headers or {})
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {}), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw), dict(exc.headers)
            except ValueError:
                return exc.code, {}, dict(exc.headers)
        except urllib.error.URLError as exc:
            die(f"could not reach {self.url} - {exc.reason}. Is the War Room running?")

    def sign_in(self) -> None:
        if not self.password:
            return
        code, out, _ = self._call("/api/login", "POST", {"password": self.password})
        if code == 401:
            die("the site rejected the password. Check password.txt or the "
                "WARROOM_PASSWORD variable.")
        if code != 200:
            die(f"logging in failed: {out.get('error') or code}")

    def read(self) -> dict:
        code, state, head = self._call("/api/state")
        if code == 401:
            die("the site needs a password and none was given.")
        if code != 200:
            die(f"could not read the site's data: {code}")
        self.rev = head.get("X-WarRoom-Rev", "0")
        if head.get("X-WarRoom-Auth") == "required":
            die("not logged in - set WARROOM_PASSWORD or add password.txt "
                "next to this script.")
        return state if isinstance(state, dict) else {}

    def write(self, state: dict) -> dict:
        code, out, _ = self._call("/api/state", "PUT", state, {"If-Match": self.rev})
        if code == 409:
            return {"conflict": True}
        if code == 401:
            die("the site would not accept the save - not logged in.")
        if code != 200:
            die(f"saving failed: {out.get('error') or code}")
        return out


# ----------------------------------------------------------------- filing

def file_away(sheets: list[Path], activity: Path, label: str) -> None:
    """Move this run's spreadsheets into Alliance Activity\\<week>, keeping
    whatever a previous run left there rather than deleting it."""
    target = activity / label
    target.mkdir(parents=True, exist_ok=True)

    old = [p for p in target.glob("*.xlsx") if not p.name.startswith("~$")]
    if old:
        kept = (activity.parent / "ingest-archive" / label /
                datetime.now().strftime("%Y%m%d-%H%M%S"))
        kept.mkdir(parents=True, exist_ok=True)
        for path in old:
            shutil.move(str(path), str(kept / path.name))
        log(f"  previous scan of this week moved to {kept}")

    for path in sheets:
        dest = target / path.name
        if dest.exists():
            dest.unlink()
        shutil.move(str(path), str(dest))
    log(f"  filed under Alliance Activity\\{label}")


# ----------------------------------------------------------------- config

def first_line(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except (OSError, AttributeError):
        return None
    return lines[0].strip() if lines and lines[0].strip() else None


def find_password(explicit: Path | None) -> str | None:
    env = os.environ.get("WARROOM_PASSWORD")
    if env and env.strip():
        return env.strip()
    for path in ([explicit] if explicit else []) + [ROOT / "password.txt"]:
        found = first_line(path)
        if found:
            return found
    return None


def find_server(explicit: str | None) -> str:
    address = (explicit or os.environ.get("WARROOM_URL")
               or first_line(ROOT / "server.txt") or "").strip()
    if not address:
        die("no address for the War Room. Put it in server.txt next to this "
            "script - one line, for example:  http://203.0.113.9\n"
            "         (or pass --url). It is only http://localhost if the "
            "site runs on THIS machine.")
    return address if "://" in address else "http://" + address


# ------------------------------------------------------------------- main

def parse_args():
    ap = argparse.ArgumentParser(description="Upload a new activity export.")
    ap.add_argument("--inbox", type=Path, default=ROOT / "inbox",
                    help="where dropped spreadsheets are picked up")
    ap.add_argument("--activity", type=Path, default=ROOT / "Alliance Activity",
                    help="where weeks are filed for the local tool")
    ap.add_argument("--url", default=None,
                    help="the War Room site (default: read from server.txt)")
    ap.add_argument("--password-file", type=Path, default=None)
    ap.add_argument("--week-start", default="monday", choices=sorted(DAYS),
                    help="the day the game's week turns over (default monday)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would happen and change nothing")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    start_day = DAYS[args.week_start]

    args.inbox.mkdir(parents=True, exist_ok=True)
    sheets = sorted(p for p in args.inbox.glob("*.xlsx")
                    if not p.name.startswith("~$"))
    if not sheets:
        log("nothing in the inbox - nothing to do")
        return

    log(f"found {len(sheets)} spreadsheet(s) in {args.inbox}")
    try:
        week = parse_week(args.inbox)
    except ParseError as exc:
        die(f"that file could not be read as an activity export - {exc}")

    span = window(week["scan_date"], start_day)
    first, last = span
    label = label_for(first, last)
    ends = datetime.combine(last, datetime.min.time()) + timedelta(days=1)
    log(f"  scanned {week['scan_date']:%d %b %Y %H:%M} UTC - "
        f"{len(week['members'])} members")
    log(f"  that is the week of {label} (ends {ends:%a %d %b %H:%M} UTC)")

    site = Site(find_server(args.url), find_password(args.password_file))
    site.sign_in()
    state = site.read()

    replacing = next((w for w in (state.get("weeks") or [])
                      if scan_of(w) and window(scan_of(w), start_day) == span), None)
    if replacing:
        log(f"  the site already has this week (\"{replacing.get('label')}\")"
            f" - refreshing it")
    else:
        log("  this is a new week for the site")

    if args.dry_run:
        log("dry run - stopping before anything is moved or uploaded")
        return

    # A week already on the site keeps the name it was given.
    if replacing:
        label = replacing.get("label") or label
    week_id = replacing.get("id") if replacing else f"ingest-{first:%Y%m%d}"
    # Read the workbook where it still sits: nothing moves until the site has
    # taken it, so a failure leaves the sheet in the inbox to retry.
    entry = pack(week, label, sheets[0] if len(sheets) == 1 else None, week_id)

    out = site.write(merge(state, entry, span, start_day))
    if out.get("conflict"):
        log("  somebody else saved while this was running - reapplying")
        out = site.write(merge(site.read(), entry, span, start_day))
        if out.get("conflict"):
            die("the site kept changing underneath this. Try again in a moment.")

    log(f"uploaded - the site now has {out.get('weeks')} week(s), "
        f"revision {out.get('rev')}")
    file_away(sheets, args.activity, label)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("cancelled")
        sys.exit(1)
