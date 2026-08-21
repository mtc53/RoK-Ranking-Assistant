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
OUT = ROOT / "output" / "warroom.html"          # for publishing as an Artifact
SELFHOST = ROOT / "selfhost"                     # for hosting anywhere else


# Must match PACK_FIELDS in page.html.
PACK_FIELDS = ["governor_id", "name", "alliance_tag", "rank", "title",
               "home_kingdom", "city_hall", "power", "kill_score", "kills",
               "tech_donations", "building_time_s", "times_helped",
               "resources_donated", "forts_destroyed", "armory_points",
               "last_login", "days_inactive", "days_in_alliance"]


def seed_weeks() -> list:
    """Bake whatever weeks exist locally into the page as starting data."""
    sys.path.insert(0, str(ROOT))
    from rok_ranker.parse import load_all_weeks

    activity = ROOT / "Alliance Activity"
    if not activity.is_dir():
        return []
    weeks = []
    for w in load_all_weeks(activity):
        # Archive the workbook itself when the week came from a single file.
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
            # last_login is only used while parsing, so it is dropped here.
            "rows": [[None if f == "last_login" else m.get(f) for f in PACK_FIELDS]
                     for m in w["members"]],
        })
    return weeks


def build() -> Path:
    page = (WEBAPP / "page.html").read_text(encoding="utf-8")
    app = (WEBAPP / "app.js").read_text(encoding="utf-8")
    cfg = tomllib.load((ROOT / "config.toml").open("rb"))

    # The published page is one file, so the engine is inlined as a classic
    # script rather than imported as a module.
    app = re.sub(r"^export ", "", app, flags=re.M)

    out = page.replace("/*__APP__*/", app)
    out = out.replace("/*__CONFIG__*/", json.dumps(cfg, indent=2))
    out = out.replace("/*__SEED__*/", json.dumps(seed_weeks(), separators=(",", ":")))

    if "/*__APP__*/" in out or "/*__CONFIG__*/" in out or "/*__SEED__*/" in out:
        sys.exit("build failed: a placeholder was not replaced")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(out, encoding="utf-8")

    # Self-host build: the same page wrapped as a complete HTML document.
    title = out.split("</title>")[0].split("<title>")[-1]
    head = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        "</head>",
        "<body>",
    ]
    doc = "\n".join(head) + out.split("</title>", 1)[1] + "\n</body>\n</html>\n"
    SELFHOST.mkdir(parents=True, exist_ok=True)
    (SELFHOST / "index.html").write_text(doc, encoding="utf-8")
    # Only what actually has to sit on the server. The https scripts stay
    # in webapp/ as sources and are not shipped, since the site runs on
    # plain http.
    for extra in ("server.py", "README.txt", "start.bat", "open-firewall.bat",
                  "check.py", "check.bat", "install-autostart.bat"):
        src = WEBAPP / extra
        if src.is_file():
            (SELFHOST / extra).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    # Drop anything left from an earlier build so the folder stays exactly
    # the set of files that belong there - but never touch what the running
    # server writes here itself (state.json, uploads/, its log, a
    # certificate): SELFHOST can be the live, in-place server directory, not
    # just a scratch build target.
    keep = {"index.html", "server.py", "README.txt", "start.bat",
            "open-firewall.bat", "check.py", "check.bat", "install-autostart.bat"}
    runtime = {"state.json", "state.json.bak", "state.json.new", "server.log",
               "password.txt", "private.txt", "redirect-to-https.txt",
               ".secret", "cert.pem", "key.pem"}
    for stale in SELFHOST.iterdir():
        if not stale.is_file() or stale.name in keep or stale.name in runtime:
            continue
        if stale.suffix == ".pem":   # win-acme's own certificate naming
            continue
        stale.unlink()
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"built {path}  ({path.stat().st_size / 1024:.0f} KB)")
    index = SELFHOST / "index.html"
    print(f"built {index}  ({index.stat().st_size / 1024:.0f} KB)")
