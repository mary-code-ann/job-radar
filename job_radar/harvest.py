"""Wave 1: harvest structured ATS/YC lists into an unproven candidate registry."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from job_radar.enterprise import apply_enterprise
from job_radar.fetch import download_sources
from job_radar.hints import blob, chennai_hint, india_hint, remote_hint
from job_radar.models import Candidate
from job_radar.names import join_keys, normalize_name, slugs_related

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data"


def parse_lastround(path: Path) -> list[Candidate]:
    rows: list[Candidate] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("company_name") or "").strip()
            ats = (raw.get("ats_vendor") or "").strip().lower()
            slug = (raw.get("board_slug") or "").strip()
            if not name or not ats or not slug:
                continue
            normalized = normalize_name(name)
            rows.append(
                Candidate(
                    name=name,
                    normalized_name=normalized,
                    ats=ats,
                    board_slug=slug,
                    lastround_crawled=(raw.get("last_crawled") or "").strip() or None,
                    sources=["lastround"],
                )
            )
    return rows


def parse_mcp(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    boards = payload.get("boards") if isinstance(payload, dict) else payload
    if not isinstance(boards, list):
        raise ValueError("ats-jobs-mcp directory.json missing boards[]")
    return boards


def parse_yc(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path.name} is not a JSON array")
    return payload


def apply_mcp(candidates: list[Candidate], boards: list[dict]) -> None:
    by_key = {(row.ats, row.board_slug): row for row in candidates if row.ats and row.board_slug}
    for board in boards:
        ats = str(board.get("ats") or "").strip().lower()
        slug = str(board.get("board") or "").strip()
        if not ats or not slug:
            continue
        jobs = board.get("jobs")
        job_count = int(jobs) if isinstance(jobs, int) else None
        checked = str(board.get("checked") or "").strip() or None
        existing = by_key.get((ats, slug))
        if existing:
            existing.recent_job_count = job_count
            existing.mcp_checked = checked
            existing.add_source("ats_mcp")
            continue
        if not job_count:
            continue
        company = (board.get("company") or "").strip() or slug
        normalized = normalize_name(company)
        added = Candidate(
            name=company,
            normalized_name=normalized,
            ats=ats,
            board_slug=slug,
            recent_job_count=job_count,
            mcp_checked=checked,
            sources=["ats_mcp"],
        )
        candidates.append(added)
        by_key[(ats, slug)] = added


def _yc_text(company: dict) -> str:
    return blob(
        company.get("name"),
        company.get("all_locations"),
        company.get("regions"),
        company.get("tags"),
        company.get("one_liner"),
    )


def _yc_signals(company: dict) -> tuple[bool, bool, bool]:
    text = _yc_text(company)
    return india_hint(text), remote_hint(text), chennai_hint(text)


def _attach_yc(row: Candidate, company: dict, source: str) -> None:
    india, remote, chennai = _yc_signals(company)
    row.add_source(source)
    row.yc_slug = company.get("slug") or row.yc_slug
    row.website = company.get("website") or row.website
    row.yc_locations = company.get("all_locations") or row.yc_locations
    row.yc_regions = list(company.get("regions") or row.yc_regions)
    row.yc_one_liner = company.get("one_liner") or row.yc_one_liner
    row.yc_industry = company.get("industry") or row.yc_industry
    if company.get("isHiring") is not None:
        row.yc_hiring = bool(company.get("isHiring"))
    row.india_hint = row.india_hint or india
    row.remote_hint = row.remote_hint or remote
    row.chennai_hint = row.chennai_hint or chennai


def _index_for_yc(candidates: list[Candidate]) -> tuple[dict[str, list[Candidate]], list[Candidate]]:
    by_name: dict[str, list[Candidate]] = {}
    with_slug: list[Candidate] = []
    for row in candidates:
        for key in join_keys(row.name) | {row.normalized_name}:
            bucket = by_name.setdefault(key, [])
            if row not in bucket:
                bucket.append(row)
        if row.board_slug:
            with_slug.append(row)
    return by_name, with_slug


def apply_yc(
    candidates: list[Candidate],
    companies: list[dict],
    *,
    source: str,
    add_unmatched_if_india: bool,
) -> None:
    by_name, with_slug = _index_for_yc(candidates)
    seen_yc: set[str] = set()
    for company in companies:
        name = (company.get("name") or "").strip()
        yc_slug = (company.get("slug") or "").strip()
        if not name:
            continue
        key = yc_slug or normalize_name(name)
        if key in seen_yc:
            continue
        seen_yc.add(key)
        normalized = normalize_name(name)
        matches: list[Candidate] = []
        for name_key in join_keys(name) | {normalized}:
            for extra in by_name.get(name_key, []):
                if extra not in matches:
                    matches.append(extra)
        if yc_slug:
            for extra in with_slug:
                if extra not in matches and slugs_related(extra.board_slug or "", yc_slug):
                    matches.append(extra)
        if matches:
            for row in matches:
                _attach_yc(row, company, source)
            continue
        india, remote, chennai = _yc_signals(company)
        if not add_unmatched_if_india or not india:
            continue
        candidates.append(
            Candidate(
                name=name,
                normalized_name=normalized,
                ats=None,
                board_slug=None,
                website=company.get("website"),
                yc_slug=yc_slug or None,
                yc_hiring=bool(company.get("isHiring")),
                yc_locations=company.get("all_locations"),
                yc_regions=list(company.get("regions") or []),
                yc_one_liner=company.get("one_liner"),
                yc_industry=company.get("industry"),
                india_hint=india,
                remote_hint=remote,
                chennai_hint=chennai,
                sources=[source],
            )
        )


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def is_priority(row: Candidate) -> bool:
    """YC/location India signal. Remote-only US companies stay in the full file."""
    return row.india_hint or row.chennai_hint


def write_outputs(candidates: list[Candidate], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = sorted(
        candidates,
        key=lambda row: (
            not is_priority(row),
            not row.india_hint,
            not (row.yc_hiring or False),
            -(row.recent_job_count or -1),
            row.name.lower(),
        ),
    )
    priority = [row for row in candidates if is_priority(row)]

    jsonl_path = out_dir / "candidates.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in candidates:
            handle.write(json.dumps(row.to_json(), ensure_ascii=False) + "\n")

    priority_path = out_dir / "priority.jsonl"
    with priority_path.open("w", encoding="utf-8") as handle:
        for row in priority:
            handle.write(json.dumps(row.to_json(), ensure_ascii=False) + "\n")

    csv_path = out_dir / "priority.csv"
    fieldnames = [
        "id",
        "name",
        "ats",
        "board_slug",
        "board_url",
        "yc_hiring",
        "india_hint",
        "remote_hint",
        "chennai_hint",
        "recent_job_count",
        "yc_locations",
        "website",
        "sources",
        "yc_one_liner",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in priority:
            payload = row.to_json()
            writer.writerow(
                {
                    **{key: payload.get(key) for key in fieldnames if key != "sources"},
                    "sources": "|".join(row.sources),
                }
            )

    source_counts = Counter()
    for row in candidates:
        for source in row.sources:
            source_counts[source] += 1

    summary = {
        "harvested_at": datetime.now(timezone.utc).isoformat(),
        "wave": 1,
        "status": "unproven",
        "counts": {
            "candidates": len(candidates),
            "with_ats_slug": sum(1 for row in candidates if row.ats and row.board_slug),
            "yc_only_no_slug": sum(1 for row in candidates if not row.board_slug),
            "priority_india_hint": len(priority),
            "priority_chennai": sum(1 for row in priority if row.chennai_hint),
            "priority_remote": sum(1 for row in priority if row.remote_hint),
            "priority_yc_hiring": sum(1 for row in priority if row.yc_hiring),
            "mcp_jobs_known": sum(1 for row in candidates if row.recent_job_count is not None),
        },
        "by_ats": dict(Counter(row.ats or "none" for row in candidates)),
        "by_source_touch": dict(source_counts),
        "outputs": {
            "candidates": _rel(jsonl_path),
            "priority_jsonl": _rel(priority_path),
            "priority_csv": _rel(csv_path),
        },
        "notes": [
            "Wave 1 only harvests directories. Remote/India on a live job is Wave 2.",
            "priority.* is the YC/location India-hinted subset, not the validated seed.",
            "LastRound ATS directory is CC BY 4.0 (fyrosofttech/lastroundai-hiring-data).",
            "Workday/SuccessFactors services boards come from data/enterprise_boards.json.",
        ],
    }
    summary_path = out_dir / "harvest_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def run(*, refresh: bool = False) -> dict:
    paths = download_sources(RAW_DIR, refresh=refresh)
    candidates = parse_lastround(paths["lastround.csv"])
    apply_mcp(candidates, parse_mcp(paths["ats_mcp.json"]))
    apply_yc(
        candidates,
        parse_yc(paths["yc_india.json"]),
        source="yc_india",
        add_unmatched_if_india=True,
    )
    apply_yc(
        candidates,
        parse_yc(paths["yc_hiring.json"]),
        source="yc_hiring",
        add_unmatched_if_india=True,
    )
    apply_enterprise(candidates)
    return write_outputs(candidates, OUT_DIR)
