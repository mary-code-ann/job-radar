from __future__ import annotations

import argparse
import json

from job_radar.enterprise import ROOT, probe_all, write_probe
from job_radar.fetch_async import CONCURRENCY
from job_radar.harvest import run
from job_radar.poll import run as poll_run
from job_radar.enrich import DEFAULT_LIMIT as ENRICH_LIMIT
from job_radar.enrich import DEFAULT_MODEL, DEFAULT_WORKERS, format_briefs, run as enrich_run
from job_radar.export import run as export_run
from job_radar.rank import dedupe_inbox, format_inbox, run as rank_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Job radar CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    harvest = sub.add_parser("harvest", help="Wave 1: pull ATS/YC directories")
    harvest.add_argument(
        "--refresh",
        action="store_true",
        help="Re-download cached files in data/raw",
    )
    probe = sub.add_parser("probe", help="Live first-page check of Workday/SF boards")
    poll = sub.add_parser("poll", help="Wave 2: Geonode poll of every harvested board")
    poll.add_argument("--resume", action="store_true", help="Continue an interrupted run")
    poll.add_argument(
        "--ats",
        action="append",
        help="Restrict ATS (repeatable or comma-separated)",
    )
    poll.add_argument("--limit", type=int, default=0, help="Max boards this process")
    poll.add_argument("--concurrency", type=int, default=CONCURRENCY)
    rank = sub.add_parser("rank", help="Wave 3: score open matches for profile acceptance")
    rank.add_argument("--limit", type=int, default=20)
    inbox = sub.add_parser("inbox", help="Wave 3: print top ranked jobs")
    inbox.add_argument("--limit", type=int, default=20)
    inbox.add_argument("--json", action="store_true")
    enrich = sub.add_parser("enrich", help="Wave 4: OpenRouter briefs on kept survivors")
    enrich.add_argument("--limit", type=int, default=ENRICH_LIMIT, help="0 = all pending survivors")
    enrich.add_argument("--force", action="store_true", help="Re-brief jobs that already have text")
    enrich.add_argument("--model", default=DEFAULT_MODEL)
    enrich.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    enrich.add_argument("--min-score", type=float, default=40)
    export = sub.add_parser("export", help="Write a Google Sheets CSV of briefed jobs")
    export.add_argument("--fit", default="strong", help="strong, possible, or poor")
    args = parser.parse_args()
    if args.command == "harvest":
        summary = run(refresh=args.refresh)
        print(json.dumps(summary["counts"], indent=2))
        print(f"Wrote {summary['outputs']['candidates']}")
        print(f"Wrote {summary['outputs']['priority_csv']}")
        return
    if args.command == "probe":
        summary = probe_all()
        path = write_probe(summary, ROOT / "data")
        print(json.dumps({key: summary[key] for key in ("ok", "failed")}, indent=2))
        for board in summary["boards"]:
            if board.get("ok"):
                print(
                    f"{board['name']}: {board['ats']}/{board.get('variant')} "
                    f"total={board.get('total')} india_on_page={board.get('india_on_page')}"
                )
            else:
                print(f"{board.get('name')}: FAIL {board.get('error')}")
        print(f"Wrote {path}")
        return
    if args.command == "poll":
        summary = poll_run(
            resume=args.resume,
            ats=args.ats,
            limit=args.limit or None,
            concurrency=args.concurrency,
        )
        print(json.dumps(summary["counts"], indent=2))
        print(f"Wrote {ROOT / 'data' / 'matches.jsonl'}")
        print(f"Wrote {ROOT / 'data' / 'poll_summary.json'}")
        return
    if args.command == "rank":
        result = rank_run(limit=args.limit)
        print(json.dumps(result["summary"], indent=2))
        return
    if args.command == "inbox":
        result = rank_run(limit=args.limit)
        if args.json:
            print(json.dumps(dedupe_inbox(result["ranked"])[: args.limit], indent=2, default=str))
            return
        print(format_inbox(result["ranked"], args.limit))
        print(f"Wrote {ROOT / 'data' / 'inbox.jsonl'}")
        print(f"Wrote {ROOT / 'data' / 'inbox.csv'}")
        return
    if args.command == "enrich":
        result = enrich_run(
            limit=args.limit,
            force=args.force,
            model=args.model,
            workers=args.workers,
            min_score=args.min_score,
        )
        print(json.dumps(result["summary"], indent=2))
        if result.get("briefs"):
            print(format_briefs(result["briefs"], 20))
        print(f"Wrote {ROOT / 'data' / 'briefs.jsonl'}")
        return
    if args.command == "export":
        result = export_run(fit=args.fit)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
