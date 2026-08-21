"""Writes the CSV, history and HTML outputs for a scored week."""
from __future__ import annotations

import csv
import html
import json
import re
from datetime import datetime
from pathlib import Path

from .score import METRIC_LABELS, TIER_ORDER, departures

from .parse import ACTIVITY_FIELDS

# Identity and result columns, before the per-metric numbers are appended.
CSV_FIELDS = [
    "rank_overall", "rank_in_alliance", "alliance_tag", "name", "governor_id",
    "rank", "title", "score", "tier", "score_change", "rank_change",
    "power", "power_growth", "city_hall", "days_inactive", "days_in_alliance",
    "flags",
]


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower() or "week"


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}" if value % 1 else str(int(value))
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)


def _metric_columns(result):
    """(header, key) pairs for the metric numbers, labelled by how they scored.

    When a stat accumulates, the scored column is the week's increase and the
    running total is kept alongside it so the two are never confused.
    """
    cols = []
    for name in result.metrics:
        label = METRIC_LABELS.get(name, name)
        if result.metric_modes.get(name) == "delta":
            cols.append((f"{label} (this week)", f"eff_{name}"))
            cols.append((f"{label} (running total)", f"total_{name}"))
        else:
            cols.append((label, f"eff_{name}"))
    return cols


def write_week_csv(result, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metric_cols = _metric_columns(result)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow([f.replace("_", " ").title() for f in CSV_FIELDS]
                        + [h for h, _ in metric_cols])
        for m in result.members:
            writer.writerow([_fmt(m.get(f)) for f in CSV_FIELDS]
                            + [_fmt(m.get(k)) for _, k in metric_cols])


def write_history_csv(results, path: Path) -> None:
    """One row per member per week - the longitudinal store.

    Both the weekly increase and the running total are written for every stat,
    so the columns stay identical no matter which mode a week scored in.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    head = ["Week Label", "Scan Date"] + [f.replace("_", " ").title() for f in CSV_FIELDS]
    for name in ACTIVITY_FIELDS:
        label = METRIC_LABELS.get(name, name)
        head += [f"{label} (this week)", f"{label} (running total)"]
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(head)
        for result in results:
            for m in result.members:
                row = [result.label, result.scan_date.strftime("%Y-%m-%d")]
                row += [_fmt(m.get(f)) for f in CSV_FIELDS]
                for name in ACTIVITY_FIELDS:
                    row += [_fmt(m.get(f"eff_{name}")), _fmt(m.get(f"total_{name}"))]
                writer.writerow(row)


def build_trends(results) -> dict:
    """Per-member history across every scored week, keyed by governor id."""
    trend: dict[int, dict] = {}
    for result in results:
        for m in result.members:
            entry = trend.setdefault(m["governor_id"], {
                "name": m["name"], "weeks": [],
            })
            entry["name"] = m["name"]
            entry["weeks"].append({
                "label": result.label,
                "score": m["score"],
                "rank": m["rank_overall"],
                "tier": m["tier"],
                "alliance": m["alliance_tag"],
            })
    return trend


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def write_html(result, previous, results, path: Path, cfg: dict,
               artifact: bool = False) -> str:
    """Interactive HTML report. `artifact=True` emits page content only, ready
    to publish; otherwise a complete standalone file is written."""
    trends = build_trends(results)
    left = departures(result, previous)

    metric_cols = [m for m in result.metrics]
    members_payload = []
    for m in result.members:
        history = trends.get(m["governor_id"], {}).get("weeks", [])
        members_payload.append({
            "r": m["rank_overall"],
            "ra": m["rank_in_alliance"],
            "n": m["name"],
            "id": m["governor_id"],
            "a": m["alliance_tag"],
            "gr": m.get("rank") or "",
            "ti": m.get("title") or "",
            "s": m["score"],
            "t": m["tier"],
            "sc": m.get("score_change"),
            "rc": m.get("rank_change"),
            "p": _num(m.get("power")),
            "pg": _num(m.get("power_growth")),
            "ch": _num(m.get("city_hall")),
            "di": _num(m.get("days_inactive")),
            "da": _num(m.get("days_in_alliance")),
            "f": m.get("flags", []),
            "c": m.get("categories", {}),
            "ms": {k: round(m.get(f"score_{k}", 0), 1) for k in metric_cols},
            "mv": {k: _num(m.get(f"eff_{k}")) for k in metric_cols},
            "mt": {k: _num(m.get(f"total_{k}")) for k in metric_cols
                   if result.metric_modes.get(k) == "delta"},
            "h": history,
        })

    tier_counts = {t: sum(1 for m in result.members if m["tier"] == t) for t in TIER_ORDER}
    payload = {
        "week": result.label,
        "scan": result.scan_date.strftime("%Y-%m-%d %H:%M UTC"),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "hasPrev": result.has_previous,
        "prevLabel": result.previous_label,
        "weekList": [r.label for r in results],
        "metrics": metric_cols,
        "metricLabels": {k: METRIC_LABELS.get(k, k) for k in metric_cols},
        "metricModes": result.metric_modes,
        "usesDelta": any(v == "delta" for v in result.metric_modes.values()),
        "weights": {k: float(cfg.get("weights", {}).get(k, 0)) for k in metric_cols},
        "members": members_payload,
        "alliances": result.alliances,
        "tierCounts": tier_counts,
        "departures": left,
        "tierCuts": cfg.get("tiers", {}),
        "curve": cfg.get("scoring", {}).get("curve", "hybrid"),
        "pool": cfg.get("scoring", {}).get("pool", "global"),
    }

    data_json = json.dumps(payload, ensure_ascii=False, default=str)
    template = (Path(__file__).parent / "template.html").read_text(encoding="utf-8")
    body = template.replace("/*__DATA__*/null", data_json)
    # A folder named "1" should read as "Week 1", not as a bare digit.
    label = result.label.strip()
    title = f"Week {label} Rankings" if label.isdigit() else f"{label} Rankings"
    body = body.replace("__TITLE__", html.escape(title))

    if artifact:
        # Published artifacts are wrapped in their own document skeleton, so
        # the page content is handed over exactly as-is.
        out = body
    else:
        # A standalone local file needs the full document around it, with the
        # title lifted out of the content and into the head where it belongs.
        head_title = re.search(r"<title>.*?</title>", body, re.S)
        if head_title:
            body = body.replace(head_title.group(0), "", 1)
        out = (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"{head_title.group(0) if head_title else ''}\n"
            "</head>\n<body>\n" + body + "\n</body>\n</html>\n"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out, encoding="utf-8")
    return title
