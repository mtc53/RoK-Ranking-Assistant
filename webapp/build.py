"""Builds the shareable web app from page.html + app.js + config.toml.

Keeps app.js as the single source of the browser scoring engine, so the
published page and the local Python tool never drift apart by hand-editing.

    python webapp/build.py
"""
from __future__ import annotations

import base64
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBAPP = ROOT / "webapp"
OUT = ROOT / "output" / "warroom.html"           # for publishing as an Artifact
SELFHOST = ROOT / "selfhost"                     # for hosting anywhere else

# Must match PACK_FIELDS in page.html.
PACK_FIELDS = ["governor_id", "name", "alliance_tag", "rank", "title",
               "home_kingdom", "city_hall", "power", "kill_score", "kills",
               "tech_donations", "building_time_s", "times_helped",
               "resources_donated", "forts_destroyed", "armory_points",
               "last_login", "days_inactive", "days_in_alliance"]

# Everything the server needs, and nothing else.
SHIPPED = ("server.py", "README.txt", "start.bat", "open-firewall.bat",
           "check.py", "check.bat")

# What the running server writes next to itself. selfhost/ can be the live
# server directory, so a rebuild must never delete these.
RUNTIME = {"state.json", "state.json.bak", "state.json.new", "server.log",
           "password.txt", "private.txt", "redirect-to-https.txt", ".secret",
           "cert.pem", "key.pem"}


def seed_weeks() -> list:
    """Bake whatever weeks exist locally into the page as starting data."""
    sys.path.insert(0, str(ROOT))
    from rok_ranker.parse import load_all_weeks

    activity = ROOT / "Alliance Activity"
    if not activity.is_dir():
        return []
    weeks = []
    for w in load_all_weeks(activity):
        files = sorted(p for p in Path(w["folder"]).rglob("*.xlsx")
                       if not p.name.startswith("~$"))
        archived = None
        if len(files) == 1:
            archived = {"name": files[0].name,
                        "b64": base64.b64encode(files[0].read_bytes()).decode()}
        weeks.append({
            "file": archived,
            "id": "seed-" + str(len(weeks)),
            "label": w["label"],
            "scanDate": w["scan_date"].isoformat() + "Z",
            "summaries": w["summaries"],
            "cols": PACK_FIELDS,
            "rows": [[None if f == "last_login" else m.get(f) for f in PACK_FIELDS]
                     for m in w["members"]],
        })
    return weeks


def wrap(page: str) -> str:
    """The same page as a complete HTML document, for hosting."""
    title = page.split("</title>")[0].split("<title>")[-1]
    head = "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        "</head>",
        "<body>",
    ])
    return head + page.split("</title>", 1)[1] + "\n</body>\n</html>\n"


def build() -> Path:
    page = (WEBAPP / "page.html").read_text(encoding="utf-8")
    app = (WEBAPP / "app.js").read_text(encoding="utf-8")
    cfg = tomllib.load((ROOT / "config.toml").open("rb"))

    # One file, so the engine is inlined as a classic script, not imported.
    app = re.sub(r"^export ", "", app, flags=re.M)

    out = page.replace("/*__APP__*/", app)
    out = out.replace("/*__CONFIG__*/", json.dumps(cfg, indent=2))
    out = out.replace("/*__SEED__*/", json.dumps(seed_weeks(), separators=(",", ":")))
    for placeholder in ("/*__APP__*/", "/*__CONFIG__*/", "/*__SEED__*/"):
        if placeholder in out:
            sys.exit(f"build failed: {placeholder} was not replaced")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out, encoding="utf-8")

    SELFHOST.mkdir(parents=True, exist_ok=True)
    (SELFHOST / "index.html").write_text(wrap(out), encoding="utf-8")
    for name in SHIPPED:
        src = WEBAPP / name
        if src.is_file():
            (SELFHOST / name).write_text(src.read_text(encoding="utf-8"),
                                         encoding="utf-8")

    keep = {"index.html", *SHIPPED} | RUNTIME
    for stale in SELFHOST.iterdir():
        if stale.is_file() and stale.name not in keep and stale.suffix != ".pem":
            stale.unlink()
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"built {path}  ({path.stat().st_size / 1024:.0f} KB)")
    index = SELFHOST / "index.html"
    print(f"built {index}  ({index.stat().st_size / 1024:.0f} KB)")
