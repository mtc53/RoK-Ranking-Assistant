"""Command line entry point: parse -> score -> report."""
from __future__ import annotations

import argparse
import sys
import tomllib
import webbrowser
from pathlib import Path

from . import __version__
from .parse import ParseError, load_all_weeks, week_folders
from .report import slug, write_history_csv, write_html, write_week_csv
from .score import score_all

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "Alliance Activity"
DEFAULT_OUTPUT = ROOT / "output"
DEFAULT_CONFIG = ROOT / "config.toml"


def load_config(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"Config file not found: {path}")
    with path.open("rb") as fh:
        return tomllib.load(fh)


def cmd_weeks(args) -> int:
    folders = week_folders(Path(args.input))
    if not folders:
        print(f"No week folders with .xlsx files under {args.input}")
        return 1
    print(f"{len(folders)} week folder(s) under {args.input}:\n")
    for f in folders:
        files = [p.name for p in sorted(f.rglob("*.xlsx")) if not p.name.startswith("~$")]
        print(f"  {f.name}")
        for name in files:
            print(f"      {name}")
    return 0


def cmd_run(args) -> int:
    cfg = load_config(Path(args.config))
    in_dir, out_dir = Path(args.input), Path(args.output)

    print(f"Reading week folders from: {in_dir}")
    weeks = load_all_weeks(in_dir)
    if not weeks:
        print("No week folders found - nothing to do.")
        return 1
    for w in weeks:
        print(f"  {w['label']:<28} {len(w['members']):>4} members  "
              f"scan {w['scan_date']:%Y-%m-%d}  ({len(w['files'])} file(s))")

    results = score_all(weeks, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\nScoring:")
    targets = results if args.all_weeks else results[-1:]
    last_html = None
    for i, result in enumerate(results):
        if result not in targets:
            continue
        idx = results.index(result)
        previous = results[idx - 1] if idx > 0 else None
        name = slug(result.label)
        csv_path = out_dir / f"{name}_rankings.csv"
        html_path = out_dir / f"{name}_report.html"
        write_week_csv(result, csv_path)
        write_html(result, previous, results[: idx + 1], html_path, cfg)
        last_html = html_path
        if args.artifact:
            art_path = out_dir / f"{name}_artifact.html"
            write_html(result, previous, results[: idx + 1], art_path, cfg,
                       artifact=True)
        top = result.members[0]
        print(f"  {result.label}: {len(result.members)} ranked, "
              f"top = {top['name']} ({top['score']:.1f})")
        print(f"      {csv_path.name}")
        print(f"      {html_path.name}")
        if args.artifact:
            print(f"      {name}_artifact.html  (publish-ready)")

    history = out_dir / "history.csv"
    write_history_csv(results, history)
    print(f"      {history.name}  ({sum(len(r.members) for r in results)} member-weeks)")

    if last_html and not args.no_open:
        webbrowser.open(last_html.resolve().as_uri())
    print(f"\nDone. Reports in {out_dir}")
    return 0


def main(argv=None) -> int:
    # Shared options live on a parent parser so they work either before or
    # after the sub-command: "rank.py -i X run" and "rank.py run -i X" both go.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-i", "--input", default=argparse.SUPPRESS,
                        help="folder holding one sub-folder per week")
    common.add_argument("-o", "--output", default=argparse.SUPPRESS,
                        help="where reports are written")
    common.add_argument("-c", "--config", default=argparse.SUPPRESS,
                        help="scoring configuration file")

    ap = argparse.ArgumentParser(
        prog="rok-rank", parents=[common],
        description="Rank Rise of Kingdoms alliance members from weekly activity exports.",
    )
    ap.add_argument("--version", action="version", version=f"rok-rank {__version__}")
    sub = ap.add_subparsers(dest="cmd")

    run = sub.add_parser("run", parents=[common],
                         help="score the latest week and build reports (default)")
    run.add_argument("--all-weeks", action="store_true",
                     help="rebuild reports for every week, not just the newest")
    run.add_argument("--no-open", action="store_true",
                     help="do not open the report in a browser afterwards")
    run.add_argument("--artifact", action="store_true",
                     help="also write a publish-ready copy for sharing as a link")
    run.set_defaults(func=cmd_run)

    sub.add_parser("weeks", parents=[common],
                   help="list the week folders that were detected").set_defaults(
        func=cmd_weeks
    )

    args = ap.parse_args(argv)
    if not getattr(args, "cmd", None):
        args = ap.parse_args((argv or []) + ["run"])
    # Options use SUPPRESS so they work on either side of the sub-command;
    # fill in the defaults for whatever was not supplied.
    for dest, fallback in (("input", DEFAULT_INPUT), ("output", DEFAULT_OUTPUT),
                           ("config", DEFAULT_CONFIG)):
        if not getattr(args, dest, None):
            setattr(args, dest, str(fallback))
    try:
        return args.func(args)
    except ParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
