"""Reads the weekly alliance spreadsheets into a normalised member table.

Every folder under "Alliance Activity" is one scoring week. A folder may hold
any number of .xlsx exports (one per kingdom, per alliance, or all four in one
file) - they are merged. Column order and sheet names are not assumed; sheets
are identified by their header row, so a future export with extra or reordered
columns still parses.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

import openpyxl

HEADER_ALIASES = {
    "governor_id": ["governor id", "governorid", "id", "player id", "lord id"],
    "name": ["name", "governor name", "nickname", "player"],
    "rank": ["rank", "alliance rank"],
    "title": ["title"],
    "home_kingdom": ["home kingdom", "kingdom", "home"],
    "city_hall": ["city hall", "ch", "city hall level"],
    "power": ["power"],
    "kill_score": ["kill score", "killscore", "kp", "kill points"],
    "kills": ["kills", "total kills"],
    "tech_donations": ["tech donations", "technology donations", "tech donation"],
    "building_time_s": ["building time (s)", "building time", "build time (s)"],
    "times_helped": ["times helped", "helps", "helps given"],
    "resources_donated": ["resources donated", "resource donated", "resources"],
    "forts_destroyed": ["forts destroyed", "forts", "flags destroyed"],
    "armory_points": ["armory points", "armory", "armoury points"],
    "last_seen": ["last seen"],
    "last_login": ["last login (utc)", "last login"],
    "days_inactive": ["days inactive", "inactive days"],
    "joined": ["joined (utc)", "joined"],
    "days_in_alliance": ["days in alliance", "days in ally"],
}
LOOKUP = {a: f for f, aliases in HEADER_ALIASES.items() for a in aliases}

SUMMARY_ALIASES = {
    "alliance_name": ["alliance", "alliance name"],
    "tag": ["tag", "alliance tag"],
    "kingdom": ["kingdom"],
    "alliance_id": ["alliance id"],
    "member_count": ["members", "member count"],
    "leader": ["leader"],
}
SUMMARY_LOOKUP = {a: f for f, aliases in SUMMARY_ALIASES.items() for a in aliases}

ACTIVITY_FIELDS = [
    "kill_score", "kills", "tech_donations", "building_time_s",
    "times_helped", "resources_donated", "forts_destroyed", "armory_points",
]
STATE_FIELDS = ["power", "city_hall", "days_inactive", "days_in_alliance"]

NUMERIC_FIELDS = set(ACTIVITY_FIELDS) | {
    "power", "city_hall", "days_inactive", "days_in_alliance", "governor_id",
}


class ParseError(Exception):
    pass


def _norm(text) -> str:
    """Squash a header cell down to a comparable key."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).strip().lower()
    return re.sub(r"\s+", " ", s)


def _num(value) -> float:
    """Coerce a cell to a number, tolerating '1,234', '1.2M' and blanks."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace(" ", "")
    mult = 1.0
    if s and s[-1].lower() in "kmb":
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[s[-1].lower()]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return 0.0


def _find_header(rows, required, lookup):
    """Locate the header row within the first rows of a sheet."""
    for r, row in enumerate(rows[:10]):
        mapping = {}
        for i, cell in enumerate(row):
            field = lookup.get(_norm(cell))
            if field and field not in mapping.values():
                mapping[i] = field
        if required.issubset(set(mapping.values())):
            return r, mapping
    return None, None


def parse_workbook(path: Path):
    """Return (members, alliance_summaries) for one .xlsx export."""
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ParseError(
            f"Could not open '{path.name}' in {path.parent.name}.\n"
            f"  It may be damaged, still downloading, or saved in an older .xls "
            f"format - try re-exporting it, or open it in Excel and Save As .xlsx.\n"
            f"  ({type(exc).__name__}: {exc})"
        ) from exc
    members: list[dict] = []
    summaries: list[dict] = []

    try:
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue

            hdr, mmap = _find_header(rows, {"governor_id", "power"}, LOOKUP)
            if hdr is None:
                hdr, smap = _find_header(rows, {"alliance_name", "tag"}, SUMMARY_LOOKUP)
            else:
                smap = None

            if hdr is not None and smap is not None:
                for row in rows[hdr + 1:]:
                    rec = {f: (row[i] if i < len(row) else None) for i, f in smap.items()}
                    if not rec.get("tag"):
                        continue
                    summaries.append({
                        "tag": str(rec["tag"]).strip(),
                        "alliance_name": str(rec.get("alliance_name") or "").strip(),
                        "kingdom": str(rec.get("kingdom") or "").strip(),
                        "alliance_id": str(rec.get("alliance_id") or "").strip(),
                        "leader": str(rec.get("leader") or "").strip(),
                        "member_count": int(_num(rec.get("member_count"))),
                    })
                continue

            if hdr is None:
                continue

            tag = str(ws.title).strip()
            for row in rows[hdr + 1:]:
                rec = {f: (row[i] if i < len(row) else None) for i, f in mmap.items()}
                if rec.get("governor_id") in (None, ""):
                    continue
                member = {"alliance_tag": tag, "source_file": path.name}
                for field in HEADER_ALIASES:
                    value = rec.get(field)
                    if field in NUMERIC_FIELDS:
                        member[field] = _num(value)
                    elif field in ("last_login", "joined"):
                        member[field] = value if isinstance(value, datetime) else None
                    else:
                        member[field] = None if value is None else str(value).strip()
                member["governor_id"] = int(member["governor_id"])
                member["name"] = member.get("name") or f"Governor {member['governor_id']}"
                members.append(member)
    finally:
        wb.close()

    return members, summaries


def week_folders(root: Path) -> list[Path]:
    """Every sub-folder of the activity root holding at least one xlsx."""
    if not root.is_dir():
        raise ParseError(f"Activity folder not found: {root}")
    found = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and any(
            p.suffix.lower() == ".xlsx" and not p.name.startswith("~$")
            for p in child.rglob("*.xlsx")
        ):
            found.append(child)
    return found


def parse_week(folder: Path) -> dict:
    """Parse one week folder into {label, scan_date, members, summaries}."""
    files = sorted(p for p in folder.rglob("*.xlsx") if not p.name.startswith("~$"))
    members: list[dict] = []
    summaries: list[dict] = []
    for path in files:
        m, s = parse_workbook(path)
        members.extend(m)
        summaries.extend(s)

    if not members:
        raise ParseError(f"No member rows found in {folder}")

    best: dict[int, dict] = {}
    for m in members:
        gid = m["governor_id"]
        prior = best.get(gid)
        if prior is None or (m.get("last_login") or datetime.min) > (
            prior.get("last_login") or datetime.min
        ):
            best[gid] = m
    members = list(best.values())

    logins = [m["last_login"] for m in members if m.get("last_login")]
    if logins:
        scan_date = max(logins)
    else:
        scan_date = datetime.fromtimestamp(max(p.stat().st_mtime for p in files))

    for m in members:
        m["week_label"] = folder.name
        m["scan_date"] = scan_date

    by_tag: dict[str, dict] = {}
    for s in summaries:
        by_tag.setdefault(s["tag"], s)

    return {
        "label": folder.name,
        "scan_date": scan_date,
        "folder": str(folder),
        "files": [p.name for p in files],
        "members": members,
        "summaries": list(by_tag.values()),
    }


def load_all_weeks(root: Path) -> list[dict]:
    """Parse every week folder, ordered oldest -> newest by scan date."""
    weeks = [parse_week(f) for f in week_folders(root)]
    weeks.sort(key=lambda w: w["scan_date"])
    return weeks
