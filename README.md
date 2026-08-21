# RoK Kingdom Weekly Activity Rankings

Ranks every member of the kingdom - all four alliances - from the weekly
activity export, and keeps building history as you drop in a new spreadsheet
each week.

## Running it

Double-click **`rank.bat`**, or from a terminal:

```bash
python rank.py
```

It reads every week folder, scores the newest one, writes the reports into
`output\`, and opens the HTML report in your browser.

## Adding next week

Make a new folder inside `Alliance Activity` and drop the export in:

```
Alliance Activity\
    16-22 August\      <- week 1
        2kingdoms_DeV_A98P_DevA_AK98_alliances.xlsx
    23-29 August\      <- just add this
        2kingdoms_DeV_A98P_DevA_AK98_alliances.xlsx
```

Then run it again. The folder name is only a label - weeks are ordered by the
scan date found inside the file, so you can name folders however you like. A
folder may hold **several** spreadsheets (one per kingdom or per alliance) and
they are merged automatically.

From the second week onward you also get: power growth, score change, rank
movement, per-member history, and a list of who left.

## What comes out

| File | What it is |
|---|---|
| `output\<week>_report.html` | The main report - sortable, searchable, filterable. Works offline; send it to your officers. |
| `output\<week>_rankings.csv` | Same rankings as a spreadsheet. |
| `output\history.csv` | Every member, every week, one row each - the long-term record. |
| `output\<week>_artifact.html` | Only with `--artifact`: the same report, ready to publish as a shareable link. |

The report has: summary cards, alliance standings, the full member table
(click any row for a scorecard and week-by-week history), an **action list** of
inactive/low-activity members, and who left since last week.

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

## The web app (shareable, uploads in the browser)

As well as the local reports there is a browser version your R5s can use.
It parses the .xlsx itself, so nobody needs Python installed.

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

- **Put a password in `password.txt`** next to `server.py`. Without one,
  anyone who can open the page can change the rankings. With one, everybody
  can still read the page and only the password lets them change anything.
- **Saves cannot overwrite each other.** If two officers have the page open
  and both save, the second one is told and reloaded rather than silently
  wiping the first.
- **The server keeps its own backups** - the previous save as
  `state.json.bak` and the last ten in `backups\`. They are on the same
  machine, so keep using Download backup for anything you would hate to lose.

Sources live in `webapp/`:

- `app.js` - the Excel reader and scoring engine (mirrors `rok_ranker/`)
- `page.html` - markup, styling and the app shell
- `server.py` - the optional self-hosting server
- `build.py` - stitches them together

**If you change `config.toml`, re-run `python webapp/build.py` and republish**,
or the page keeps the old weights while the local tool uses the new ones.

## Uploading a new scan without touching the website

`ingest.py` takes the spreadsheet the Discord bot gives you and does the rest:
works out which week it belongs to, files it under `Alliance Activity` so the
local tool sees it too, and updates that week on the self-hosted site.

```bash
python ingest.py
```

Or double-click **`ingest.bat`**.

The routine is: run the bot's command, drag the file it sends you into
`inbox\`, and double-click `ingest.bat`. The file disappearing from `inbox\`
is how you know it went up.

**Why not fully automatic?** The bot sends the sheet by direct message. Reading
your DMs would mean a script logging in as you, which Discord forbids and bans
accounts for, and a bot account cannot read your DMs either. If whoever runs
that bot can post the export to a channel instead - or hand you a download
link - the rest of this becomes unattended, and nothing here would need to
change except where the file comes from.

### Running it every day

Dropping a sheet in daily **refreshes the current week in place** rather than
piling up a new entry each day, so a season stays ~52 weeks and the scoring
keeps its weekly meaning.

The game's week turns over at **00:00 UTC on Monday**, and that is the line
`ingest.py` uses. A scan taken before it refreshes the week in progress; the
first scan after it starts a new week and the old one is left frozen exactly as
it stood. The timestamps inside the export are already UTC - the column is
literally called "last login (utc)" - so this does not drift when the clocks
change. Use `--week-start` if the reset ever moves.

A week already on the site keeps whatever name you gave it. Superseded
spreadsheets are moved to `ingest-archive\`, never deleted, and nothing leaves
`inbox\` until the site has actually accepted it - so a failed upload can just
be run again.

If the site has a password, `ingest.py` needs it too: `password.txt` next to it,
or the `WARROOM_PASSWORD` variable.

```bash
python ingest.py --dry-run
```

says which week it would land in and changes nothing.

## Commands

```bash
python rank.py                  # score the newest week
python rank.py run --all-weeks  # rebuild reports for every week
python rank.py run --artifact   # also write a publish-ready copy for sharing
python rank.py weeks            # list detected week folders
python rank.py run --no-open    # do not launch the browser
```

Options: `-i` input folder, `-o` output folder, `-c` config file.

## Requirements

Python 3.11+ and `openpyxl`:

```bash
pip install -r requirements.txt
```
