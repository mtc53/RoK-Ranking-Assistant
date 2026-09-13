# Kingdom War Room

Ranks every member of the kingdom from the activity export, and keeps
building history as you add a new spreadsheet.

It runs as a website. You open it, drag the `.xlsx` on, and the page reads
the spreadsheet in the browser, scores everyone and saves the result on the
server so everyone sees the same thing.

## Running it

Build the page:

```bash
python webapp/build.py
```

That writes `selfhost/index.html`, which is served with `selfhost/server.py`.
Both are deployed together - see the `myprojects-site` bundle for the
Caddy configuration that puts it on `rok.myprojects.cc` behind a password.

## Adding a week

Open the site, **Weekly spreadsheets**, and drop the export on. Anything
scanned inside the same game week replaces what is already there, so a fresh
scan each day keeps the week up to date rather than piling up entries. The
first scan after the Monday 00:00 UTC reset starts the next week and leaves
the finished one alone.

The **Week / Day** switch beside the week tabs chooses what is compared:
week to week, or each scan against the one before it.

## Which exports it reads

Two shapes, told apart automatically:

- **Alliance activity export** - one sheet per alliance, with last-login
  times, donations, helps, forts and armory points.
- **Kingdom deep scan** - the top-N sheet with power, kill points, helps
  given and resources given. Its numbers are lifetime totals, so they are
  scored on what was added since the previous scan. It has no last-login
  column, so the inactivity flags and the kick list do not apply, and the
  scan time is read from the summary sheet instead.

## How the score works

Each member gets a **0-100 score**, a **tier (S-F)**, an overall rank and a rank
inside their own alliance.

### Weekly increase, not running total

If your export keeps counting up from the Aug 16 baseline scan, members are
ranked on **how much they added this week**, not on the total they are sitting
on. Someone who went 20M -> 40M kill score (+20M) outranks someone who went
100M -> 110M (+10M), even though the second number is bigger.

Columns scored this way are marked **Δ** in the report and show the week's gain
with the running total underneath (`24.7M of 52.3M`), so the two can never be
confused. The CSV splits them into `(this week)` and `(running total)` columns.

The program works out which stats accumulate by itself: if almost nobody's
number ever falls between two exports, the stat is accumulating and gets scored
on the increase. If the numbers bounce up and down, the export already resets
weekly and the value is scored as-is. You can force either behaviour per stat in
the `[metric_mode]` section of `config.toml`.

In the first week there is nothing to compare against, so values are scored as
exported and the report says so. Members who joined after the last export have
no baseline, so for Δ stats they are given the middle of the pack and flagged
`NO BASELINE` rather than being flattered by a running total they built up
elsewhere.

### Turning stats into a score

Raw stats cannot simply be added together. In your data kill score is
power-law - the top member has ~300x the median - while tech donations and
armory points are bunched just under a weekly cap. Summing them would produce a
kill-score leaderboard and nothing else. So each stat is first converted to a
0-100 score using a blend of:

- **relative standing** - how you did versus everyone else, and
- **absolute size** - your share of what a top-5% player did, capped at 100.

Those are combined using the weights in `config.toml`, then multiplied by an
inactivity penalty. Default weighting:

| Metric | Weight |
|---|---|
| Kill score | 21 |
| Tech donations | 19 |
| Helps given | 16 |
| Armory points | 14 |
| Forts destroyed | 13 |
| Power growth (week 2+) | 10 |
| Building time | 7 |

Resources donated and kills are switched off (weight `0`); set a number to
bring either back. Days inactive is not weighted - it multiplies the finished
score, so idling costs a share of everything rather than one metric.

Tiers are cut by percentile: S = top 10%, A = next 15%, B/C = middle 50%,
D = next 15%, F = bottom 10%.

### Flags

- **DEAD** - 14+ days inactive, kick candidate
- **INACTIVE** - 7+ days inactive
- **LOW** - score under 25
- **NO BASELINE** - joined after the last export, so their weekly increase
  cannot be measured yet
- **NO SUPPORT** - zero tech donations, helps and building time for the week

How long someone has been in the alliance is not part of the score at all.

## Tuning it

Everything is in **`config.toml`** - weights, inactivity penalties, tier
cut-offs and flag thresholds. Set any weight to `0` to drop that metric. Save
the file and re-run; no code changes needed.

Two settings worth knowing:

- `pool` - `"global"` ranks everyone together (default, best for comparing
  alliances). `"alliance"` scores each member only against their own alliance.
- `curve` - `"hybrid"` (default), `"percentile"` or `"normalized"`.

## Notes on the data

The activity columns (kill score, donations, helps, forts, armory, building
time) cover the period since the baseline scan, not the player's lifetime.
Whether they keep accumulating across exports or reset each week is worked out
automatically - see "Weekly increase, not running total" above. Power, city hall
and rank are current-state, so power growth is always a week-over-week
comparison.

Verified against week 1: members with 0-1 days in the alliance post the same
donations, helps and armory as 14+ day members, which confirms the export
measures the whole week for the player regardless of when they joined. Join
date is therefore ignored entirely - recent joiners are scored like everyone
else.

If a metric is entirely zero across an export it is dropped from the score
automatically and its weight is redistributed - so an export missing a column,
or week 1 having no power growth, will not skew anyone.

## Building and hosting

The page parses the .xlsx itself, so nobody needs Python installed to use it.

Build it:

```bash
python webapp/build.py
```

That writes two things:

| Output | For |
|---|---|
| `output/warroom.html` | publishing as a claude.ai link |
|  `selfhost/` | hosting on your own server - see the README.txt inside |

Whatever weeks are in `Alliance Activity` are baked in as starting data, so
the page is useful the moment it opens.

In the page, R5s can add weekly spreadsheets, rename or remove weeks, change
every scoring weight and threshold, and download a backup. Uploaded
spreadsheets are archived inside the saved data, so no week is ever reduced
to just its numbers.

If you host it yourself, `selfhost/README.txt` covers the server side.
Three things worth knowing before it faces the internet:

- **The password lives in Caddy**, not here. The server runs with
  `server.py 8081 local`, which listens on this machine only, so the proxy in
  front of it is the only way in and it needs no password of its own.
- **Saves cannot overwrite each other.** If two people have the page open and
  both save, the second is told and reloaded rather than wiping the first.
- **The server keeps its own backups** - the previous save as
  `state.json.bak` and the last ten in `backups\`. They are on the same
  machine, so keep using Download backup for anything you would hate to lose.

## Requirements

Python 3.11+ and `openpyxl`, for building the page:

```bash
pip install -r requirements.txt
```

The server itself needs only the standard library.
