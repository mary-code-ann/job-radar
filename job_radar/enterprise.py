"""Enterprise Workday / SuccessFactors boards: seed, harvest merge, live probe."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_radar.ats.successfactors import board_slug_from_url, list_jobs as sf_list
from job_radar.ats.workday import list_jobs as workday_list, parse_workday_url
from job_radar.hints import india_hint
from job_radar.jobs import Job
from job_radar.models import Candidate
from job_radar.names import normalize_name

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "data" / "enterprise_boards.json"


def load_seed(path: Path | None = None) -> list[dict[str, Any]]:
    payload = json.loads((path or SEED_PATH).read_text(encoding="utf-8"))
    boards = payload.get("boards") if isinstance(payload, dict) else payload
    if not isinstance(boards, list):
        raise ValueError("enterprise_boards.json missing boards[]")
    return boards


def board_slug(entry: dict[str, Any]) -> str:
    ats = str(entry.get("ats") or "").lower()
    url = str(entry.get("board_url") or "")
    if ats == "workday":
        return parse_workday_url(url)["board_slug"]
    if ats == "successfactors":
        return board_slug_from_url(url)
    raise ValueError(f"unsupported enterprise ATS: {ats}")


def seed_candidates(entries: list[dict[str, Any]] | None = None) -> list[Candidate]:
    rows: list[Candidate] = []
    for entry in entries or load_seed():
        name = str(entry.get("name") or "").strip()
        ats = str(entry.get("ats") or "").strip().lower()
        url = str(entry.get("board_url") or "").strip()
        if not name or not ats or not url:
            continue
        slug = board_slug(entry)
        rows.append(
            Candidate(
                name=name,
                normalized_name=normalize_name(name),
                ats=ats,
                board_slug=slug,
                board_url=url,
                website=entry.get("website") or url,
                india_hint=bool(entry.get("india_hint")),
                remote_hint=bool(entry.get("remote_hint")),
                chennai_hint=bool(entry.get("chennai_hint")),
                sources=["enterprise_seed"],
            )
        )
    return rows


def apply_enterprise(candidates: list[Candidate], entries: list[dict[str, Any]] | None = None) -> None:
    existing = {(row.ats, row.board_slug) for row in candidates}
    for row in seed_candidates(entries):
        key = (row.ats, row.board_slug)
        if key in existing:
            continue
        candidates.append(row)
        existing.add(key)


def _india_jobs(jobs: list[Job]) -> list[Job]:
    matched: list[Job] = []
    for job in jobs:
        blob = " ".join([job.title, *job.locations, job.apply_url])
        if india_hint(blob):
            matched.append(job)
    return matched


def probe_board(entry: dict[str, Any]) -> dict[str, Any]:
    ats = str(entry.get("ats") or "").lower()
    url = str(entry["board_url"])
    variant = ats
    if ats == "workday":
        jobs, total = workday_list(url, search_text="India", max_pages=1)
    elif ats == "successfactors":
        try:
            jobs, total, variant = sf_list(url, keywords="India", max_pages=1)
        except Exception:
            jobs, total, variant = sf_list(url, max_pages=1)
    else:
        raise ValueError(f"unsupported ATS {ats}")
    india = _india_jobs(jobs)
    return {
        "name": entry.get("name"),
        "ats": ats,
        "variant": variant,
        "board_slug": board_slug(entry),
        "board_url": url,
        "ok": True,
        "total": total,
        "page_jobs": len(jobs),
        "india_on_page": len(india),
        "samples": [job.to_json() for job in (india or jobs)[:5]],
    }


def probe_all(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for entry in entries or load_seed():
        try:
            results.append(probe_board(entry))
        except Exception as exc:
            results.append(
                {
                    "name": entry.get("name"),
                    "ats": entry.get("ats"),
                    "board_url": entry.get("board_url"),
                    "ok": False,
                    "error": str(exc),
                }
            )
    summary = {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "ok": sum(1 for row in results if row.get("ok")),
        "failed": sum(1 for row in results if not row.get("ok")),
        "boards": results,
    }
    return summary


def write_probe(summary: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "probe_enterprise.json"
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return path
