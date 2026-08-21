"""Turns parsed weekly stats into member scores, ranks and tiers.

Scoring model
-------------
Each weighted stat is converted to a 0-100 metric score, then combined into a
weighted average and multiplied by an inactivity factor.

Raw stats cannot be summed directly: kill score is power-law (one member can
have 300x the median) while tech donations and armory points are compressed
just under a weekly cap. Adding them would make the ranking a kill-score
leaderboard. So each stat is converted with one of three curves:
  percentile - standing versus everyone else, ties take the lowest rank so a
               member who did nothing scores 0 rather than a middling tie.
  normalized - size relative to the cap_percentile performer, capped at 100,
               so absolute effort still counts and outliers cannot run away.
  hybrid     - the mean of the two (default, and the recommended setting).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .parse import ACTIVITY_FIELDS

METRIC_LABELS = {
    "kill_score": "Kills +",
    "kills": "Kills",
    "tech_donations": "Tech Donations",
    "building_time_s": "Building Time",
    "times_helped": "Helps",
    "resources_donated": "Resources Donated",
    "forts_destroyed": "Forts Destroyed",
    "armory_points": "Armory Points",
    "power_growth": "Power Growth",
}

TIER_ORDER = ["S", "A", "B", "C", "D", "F"]


@dataclass
class WeekResult:
    label: str
    scan_date: object
    members: list = field(default_factory=list)
    alliances: list = field(default_factory=list)
    metrics: list = field(default_factory=list)
    has_previous: bool = False
    previous_label: str | None = None
    metric_modes: dict = field(default_factory=dict)


def _percentile_of(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * (q / 100.0)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[int(pos)]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _rank_scores(values: list[float], curve: str, cap_pct: float) -> list[float]:
    """Convert raw values to 0-100 metric scores using the configured curve."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [100.0 if values[0] > 0 else 0.0]

    order = sorted(range(n), key=lambda i: values[i])
    lowest_rank: dict[float, int] = {}
    for position, idx in enumerate(order):
        lowest_rank.setdefault(values[idx], position)
    pct = [lowest_rank[v] / (n - 1) * 100.0 for v in values]

    ordered_values = [values[i] for i in order]
    cap = _percentile_of(ordered_values, cap_pct)
    if cap <= 0:
        cap = max(ordered_values) or 1.0
    norm = [min(v / cap, 1.0) * 100.0 for v in values]

    if curve == "percentile":
        return pct
    if curve == "normalized":
        return norm
    return [(p + q) / 2.0 for p, q in zip(pct, norm)]


def _inactivity_factor(days: float, penalties: list) -> float:
    """Highest penalty threshold the member's inactivity reaches."""
    factor = 1.0
    for threshold, mult in sorted(penalties, key=lambda p: p[0]):
        if days >= threshold:
            factor = float(mult)
    return factor


def _tier_for(score_pct: float, cuts: dict) -> str:
    for tier in TIER_ORDER[:-1]:
        if score_pct >= float(cuts.get(tier, 0)):
            return tier
    return "F"


def detect_metric_modes(weeks: list[dict], cfg: dict):
    """Work out whether each stat accumulates across weeks or resets weekly.

    A scanner that diffs against a fixed baseline scan keeps counting up, so
    almost nobody's number ever goes down between exports. A scanner that
    resets every week produces numbers that bounce up and down freely. The
    fraction of members whose value *fell* separates the two cleanly.

    Cumulative stats are scored on the week-over-week increase, so a member who
    adds 20M this week outranks one sitting on a huge total who added 10M.
    """
    configured = cfg.get("metric_mode", {})
    threshold = float(cfg.get("scoring", {}).get("cumulative_max_decrease", 0.15))
    modes, why = {}, {}

    for name in ACTIVITY_FIELDS:
        want = str(configured.get(name, "auto")).lower()
        if want in ("delta", "raw"):
            modes[name], why[name] = want, "set in config.toml"
            continue

        up = down = 0
        for prev, cur in zip(weeks, weeks[1:]):
            prior = {m["governor_id"]: m for m in prev["members"]}
            for m in cur["members"]:
                p = prior.get(m["governor_id"])
                if p is None:
                    continue
                a, b = float(p.get(name) or 0), float(m.get(name) or 0)
                if b > a:
                    up += 1
                elif b < a:
                    down += 1

        total = up + down
        if total < 20:
            modes[name], why[name] = "raw", "only one week of data so far"
        elif down / total <= threshold:
            modes[name] = "delta"
            why[name] = f"accumulates ({down / total:.0%} of members fell)"
        else:
            modes[name] = "raw"
            why[name] = f"resets each week ({down / total:.0%} of members fell)"
    return modes, why


def score_week(week: dict, previous: dict | None, cfg: dict,
               modes: dict | None = None) -> WeekResult:
    """Score every member of one week. `previous` supplies deltas and growth."""
    s_cfg = cfg.get("scoring", {})
    weights_cfg = cfg.get("weights", {})
    curve = s_cfg.get("curve", "hybrid")
    cap_pct = float(s_cfg.get("cap_percentile", 95))
    pool_mode = s_cfg.get("pool", "global")
    penalties = cfg.get("inactivity", {}).get("penalties", [[0, 1.0]])
    tier_cuts = cfg.get("tiers", {})
    flags_cfg = cfg.get("flags", {})

    members = [dict(m) for m in week["members"]]
    prev_by_id = {m["governor_id"]: m for m in (previous or {}).get("members", [])}

    for m in members:
        prior = prev_by_id.get(m["governor_id"])
        if prior is not None:
            m["power_growth"] = max(0.0, m["power"] - prior["power"])
            m["power_prev"] = prior["power"]
            m["seen_before"] = True
        else:
            m["power_growth"] = 0.0
            m["power_prev"] = None
            m["seen_before"] = False

    has_previous = previous is not None
    modes = modes or {}
    new_delta = str(s_cfg.get("new_member_delta", "median")).lower()

    effective_modes = {}
    for name in ACTIVITY_FIELDS:
        effective_modes[name] = "delta" if modes.get(name) == "delta" else "raw"

    for m in members:
        prior = prev_by_id.get(m["governor_id"])
        m["has_baseline"] = prior is not None
        for name in ACTIVITY_FIELDS:
            raw = float(m.get(name) or 0)
            m[f"total_{name}"] = raw
            if effective_modes[name] != "delta":
                m[f"eff_{name}"] = raw
            elif not has_previous:
                m[f"eff_{name}"] = 0.0
            elif prior is not None:
                m[f"eff_{name}"] = max(0.0, raw - float(prior.get(name) or 0))
            else:
                m[f"eff_{name}"] = None
    for m in members:
        m["eff_power_growth"] = m["power_growth"]

    uses_delta = any(v == "delta" for v in effective_modes.values())

    for name in ACTIVITY_FIELDS:
        if effective_modes[name] != "delta":
            continue
        known = sorted(m[f"eff_{name}"] for m in members if m[f"eff_{name}"] is not None)
        if new_delta == "raw":
            fill = None
        elif new_delta == "zero" or not known:
            fill = 0.0
        else:
            fill = known[len(known) // 2]
        for m in members:
            if m[f"eff_{name}"] is None:
                m[f"eff_{name}"] = m[f"total_{name}"] if fill is None else fill

    metrics = []
    for name, weight in weights_cfg.items():
        weight = float(weight)
        if weight <= 0:
            continue
        if name not in ACTIVITY_FIELDS and name != "power_growth":
            continue
        if name == "power_growth" and not has_previous:
            continue
        if all(float(m.get(f"eff_{name}") or 0) == 0 for m in members):
            continue
        metrics.append((name, weight))
    metrics.sort(key=lambda kv: -kv[1])
    total_weight = sum(w for _, w in metrics) or 1.0

    for m in members:
        for name, _ in metrics:
            m[f"adj_{name}"] = float(m.get(f"eff_{name}") or 0)

    if pool_mode == "alliance":
        pools: dict[str, list] = {}
        for m in members:
            pools.setdefault(m["alliance_tag"], []).append(m)
    else:
        pools = {"__global__": members}

    for pool in pools.values():
        for name, _ in metrics:
            values = [float(m[f"adj_{name}"]) for m in pool]
            for m, s in zip(pool, _rank_scores(values, curve, cap_pct)):
                m[f"score_{name}"] = s

        for m in pool:
            base = sum(m[f"score_{n}"] * w for n, w in metrics) / total_weight
            m["base_score"] = base
            m["inactivity_factor"] = _inactivity_factor(
                float(m.get("days_inactive") or 0), penalties
            )
            m["score"] = round(base * m["inactivity_factor"], 2)

        scores = sorted(m["score"] for m in pool)
        n = len(scores)
        for m in pool:
            below = sum(1 for s in scores if s < m["score"])
            m["score_percentile"] = (below / (n - 1) * 100.0) if n > 1 else 100.0
            m["tier"] = _tier_for(m["score_percentile"], tier_cuts)

    cat_map = cfg.get("categories", {})
    cat_weights: dict[str, float] = {}
    for name, weight in metrics:
        cat_weights[cat_map.get(name, "Other")] = cat_weights.get(
            cat_map.get(name, "Other"), 0.0
        ) + weight
    for m in members:
        totals: dict[str, float] = {}
        for name, weight in metrics:
            cat = cat_map.get(name, "Other")
            totals[cat] = totals.get(cat, 0.0) + m[f"score_{name}"] * weight
        m["categories"] = {
            cat: round(total / cat_weights[cat], 1) for cat, total in totals.items()
        }

    members.sort(key=lambda m: -m["score"])
    for i, m in enumerate(members, 1):
        m["rank_overall"] = i
    by_alliance: dict[str, list] = {}
    for m in members:
        by_alliance.setdefault(m["alliance_tag"], []).append(m)
    for group in by_alliance.values():
        for i, m in enumerate(sorted(group, key=lambda m: -m["score"]), 1):
            m["rank_in_alliance"] = i

    prev_rank = {
        m["governor_id"]: m.get("rank_overall") for m in (previous or {}).get("members", [])
    }
    prev_score = {
        m["governor_id"]: m.get("score") for m in (previous or {}).get("members", [])
    }
    for m in members:
        gid = m["governor_id"]
        pr, ps = prev_rank.get(gid), prev_score.get(gid)
        m["prev_rank"] = pr
        m["rank_change"] = (pr - m["rank_overall"]) if pr else None
        m["prev_score"] = ps
        m["score_change"] = round(m["score"] - ps, 2) if ps is not None else None

    inactive_days = float(flags_cfg.get("inactive_days", 7))
    dead_days = float(flags_cfg.get("dead_days", 14))
    low_score = float(flags_cfg.get("low_score", 25))
    for m in members:
        tags = []
        days = float(m.get("days_inactive") or 0)
        if days >= dead_days:
            tags.append("DEAD")
        elif days >= inactive_days:
            tags.append("INACTIVE")
        if m["score"] < low_score and "DEAD" not in tags:
            tags.append("LOW")
        if all(float(m.get(f"eff_{f}") or 0) == 0 for f in
               ("tech_donations", "times_helped", "building_time_s")):
            tags.append("NO SUPPORT")
        if uses_delta and has_previous and not m["has_baseline"]:
            tags.append("NO BASELINE")
        m["flags"] = tags

    summary_meta = {s["tag"]: s for s in week.get("summaries", [])}
    prev_alliance_avg = {}
    if previous:
        tmp: dict[str, list] = {}
        for m in previous["members"]:
            tmp.setdefault(m["alliance_tag"], []).append(m.get("score", 0))
        prev_alliance_avg = {
            t: sum(v) / len(v) for t, v in tmp.items() if v
        }

    alliances = []
    for tag, group in by_alliance.items():
        meta = summary_meta.get(tag, {})
        avg = sum(m["score"] for m in group) / len(group)
        prev_avg = prev_alliance_avg.get(tag)
        alliances.append({
            "tag": tag,
            "name": meta.get("alliance_name") or tag,
            "kingdom": meta.get("kingdom", ""),
            "leader": meta.get("leader", ""),
            "members": len(group),
            "avg_score": round(avg, 2),
            "median_score": round(sorted(m["score"] for m in group)[len(group) // 2], 2),
            "avg_change": round(avg - prev_avg, 2) if prev_avg is not None else None,
            "total_power": sum(m["power"] for m in group),
            "inactive": sum(1 for m in group if "INACTIVE" in m["flags"] or "DEAD" in m["flags"]),
            "top_tier": sum(1 for m in group if m["tier"] in ("S", "A")),
            "totals": {
                name: sum(float(m.get(f"eff_{name}") or 0) for m in group)
                for name, _ in metrics
            },
        })
    alliances.sort(key=lambda a: -a["avg_score"])
    for i, a in enumerate(alliances, 1):
        a["rank"] = i

    return WeekResult(
        label=week["label"],
        scan_date=week["scan_date"],
        members=members,
        alliances=alliances,
        metrics=[name for name, _ in metrics],
        has_previous=has_previous,
        previous_label=(previous or {}).get("label"),
        metric_modes={n: effective_modes.get(n, "raw") for n, _ in metrics},
    )


def score_all(weeks: list[dict], cfg: dict) -> list[WeekResult]:
    """Score every week in order, feeding each week the one before it."""
    modes, _ = detect_metric_modes(weeks, cfg)
    results = []
    scored_prev = None
    for week in weeks:
        result = score_week(week, scored_prev, cfg, modes)
        results.append(result)
        scored_prev = {"label": week["label"], "members": result.members}
    return results


def departures(current: WeekResult, previous: WeekResult | None) -> list[dict]:
    """Members present last week but missing this week."""
    if previous is None:
        return []
    now = {m["governor_id"] for m in current.members}
    gone = []
    for m in previous.members:
        if m["governor_id"] not in now:
            gone.append({
                "governor_id": m["governor_id"],
                "name": m["name"],
                "alliance_tag": m["alliance_tag"],
                "power": m["power"],
                "last_score": m.get("score"),
                "last_tier": m.get("tier"),
            })
    gone.sort(key=lambda m: -m["power"])
    return gone
