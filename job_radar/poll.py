"""Wave 2: poll every harvested board via Geonode + Scrapling."""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from job_radar.ats import ashby, greenhouse, lever
from job_radar.ats.successfactors import (
    csb_body,
    csrf_from_html,
    origin_from_url,
    parse_csb,
    parse_rmk_tiles,
)
from job_radar.ats.workday import jobs_url, parse_list as parse_workday, parse_workday_url, search_body
from job_radar.enterprise import board_slug as enterprise_slug, load_seed
from job_radar.fetch_async import CONCURRENCY, FetchResult, fetch_url, load_geonode, scrub
from job_radar.filters import apply_gate, load_profile
from job_radar.jobs import Job
from job_radar.models import Candidate
from job_radar.store import Store, load_candidates

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / "data" / "candidates.jsonl"
MATCHES_PATH = ROOT / "data" / "matches.jsonl"
SUMMARY_PATH = ROOT / "data" / "poll_summary.json"
FLUSH_EVERY = 50
WORKDAY_CAP = 2000
WORKDAY_FALLBACK_CAP = 200
RMK_CAP = 400
CSB_PAGE = 10
SIMPLE_ATS = {"greenhouse", "lever", "ashby"}
ENTERPRISE_ATS = {"workday", "successfactors"}
POLLABLE = SIMPLE_ATS | ENTERPRISE_ATS

Fetcher = Callable[..., Awaitable[FetchResult]]


@dataclass
class BoardOutcome:
    candidate: Candidate
    status: str
    http_status: int = 0
    error: str | None = None
    jobs: list[Job] = field(default_factory=list)
    matches: list[Job] = field(default_factory=list)
    variant: str | None = None


def _log(msg: str) -> None:
    print(scrub(msg), flush=True)


def parse_ats_flags(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    out: set[str] = set()
    for value in values:
        out.update(part.strip().lower() for part in value.split(",") if part.strip())
    return out or None


def list_url(ats: str, slug: str) -> str:
    if ats == "greenhouse":
        return greenhouse.list_url(slug)
    if ats == "lever":
        return lever.list_url(slug)
    if ats == "ashby":
        return ashby.list_url(slug)
    raise ValueError(f"no list URL for {ats}")


def parse_simple(ats: str, slug: str, payload: Any) -> list[Job]:
    if ats == "greenhouse":
        return greenhouse.parse_list(payload, slug)
    if ats == "lever":
        return lever.parse_list(payload, slug)
    if ats == "ashby":
        return ashby.parse_list(payload, slug)
    return []


def board_url_for(row: Candidate, seeds: list[dict[str, Any]] | None = None) -> str | None:
    if row.board_url:
        return row.board_url
    if row.ats not in ENTERPRISE_ATS:
        return None
    for entry in seeds or load_seed():
        try:
            if enterprise_slug(entry) == row.board_slug:
                return str(entry.get("board_url") or "") or None
        except ValueError:
            continue
    return None


def decide_status(http_status: int, jobs: list[Job], matches: list[Job], error: str | None) -> str:
    if http_status == 404:
        return "dead"
    if error or http_status not in {200, 201}:
        return "error"
    if not jobs:
        return "empty"
    if matches:
        return "active"
    return "watch"


def keep_matches(jobs: list[Job], profile: dict) -> list[Job]:
    kept: list[Job] = []
    for job in jobs:
        if not job.title or not job.source_job_id:
            continue
        result = apply_gate(job, profile)
        if result.keep:
            kept.append(job)
    return kept


def _payload(result: FetchResult) -> Any:
    if not result.body:
        return None
    try:
        return result.json()
    except json.JSONDecodeError:
        return None


async def poll_simple(
    candidate: Candidate,
    proxy: str,
    sem: asyncio.Semaphore,
    profile: dict,
    fetcher: Fetcher,
) -> BoardOutcome:
    ats = candidate.ats or ""
    slug = candidate.board_slug or ""
    result = await fetcher(list_url(ats, slug), proxy, sem)
    if result.status == 404:
        return BoardOutcome(candidate, "dead", http_status=404)
    if result.error or result.status not in {200, 201}:
        return BoardOutcome(
            candidate,
            "error",
            http_status=result.status,
            error=result.error or f"http_{result.status}",
        )
    payload = _payload(result)
    if payload is None:
        return BoardOutcome(candidate, "error", http_status=result.status, error="invalid_json")
    jobs = parse_simple(ats, slug, payload)
    matches = keep_matches(jobs, profile)
    return BoardOutcome(
        candidate,
        decide_status(result.status, jobs, matches, None),
        http_status=result.status,
        jobs=jobs,
        matches=matches,
    )


async def _post_pages(
    url: str,
    bodies: list[dict[str, Any]],
    proxy: str,
    sem: asyncio.Semaphore,
    fetcher: Fetcher,
    extra_headers: dict[str, str] | None = None,
) -> list[FetchResult]:
    if not bodies:
        return []
    return list(
        await asyncio.gather(
            *[
                fetcher(url, proxy, sem, method="POST", json_body=body, extra_headers=extra_headers)
                for body in bodies
            ]
        )
    )


async def poll_workday(
    candidate: Candidate,
    proxy: str,
    sem: asyncio.Semaphore,
    profile: dict,
    fetcher: Fetcher,
    board_url: str,
) -> BoardOutcome:
    board = parse_workday_url(board_url)
    url = jobs_url(board)
    first = await fetcher(url, proxy, sem, method="POST", json_body=search_body(0, "India"))
    if first.status == 404:
        return BoardOutcome(candidate, "dead", http_status=404, variant="cxs")
    if first.error or first.status not in {200, 201}:
        return BoardOutcome(
            candidate,
            "error",
            http_status=first.status,
            error=first.error or f"http_{first.status}",
            variant="cxs",
        )
    jobs, total = parse_workday(_payload(first), board)
    search = "India"
    cap = WORKDAY_CAP
    if total == 0:
        fallback = await fetcher(url, proxy, sem, method="POST", json_body=search_body(0, ""))
        if fallback.status == 404:
            return BoardOutcome(candidate, "dead", http_status=404, variant="cxs")
        if fallback.error or fallback.status not in {200, 201}:
            return BoardOutcome(
                candidate,
                "error",
                http_status=fallback.status,
                error=fallback.error or f"http_{fallback.status}",
                variant="cxs",
            )
        jobs, total = parse_workday(_payload(fallback), board)
        search = ""
        cap = WORKDAY_FALLBACK_CAP
        first = fallback
    want = min(total, cap)
    offsets = list(range(20, want, 20))
    pages = await _post_pages(url, [search_body(offset, search) for offset in offsets], proxy, sem, fetcher)
    for page in pages:
        extra, _total = parse_workday(_payload(page), board)
        jobs.extend(extra)
    seen: set[str] = set()
    unique: list[Job] = []
    for job in jobs:
        if job.source_job_id in seen:
            continue
        seen.add(job.source_job_id)
        unique.append(job)
    matches = keep_matches(unique, profile)
    return BoardOutcome(
        candidate,
        decide_status(first.status, unique, matches, None),
        http_status=first.status,
        jobs=unique,
        matches=matches,
        variant="cxs",
    )


async def poll_successfactors(
    candidate: Candidate,
    proxy: str,
    sem: asyncio.Semaphore,
    profile: dict,
    fetcher: Fetcher,
    board_url: str,
) -> BoardOutcome:
    origin = origin_from_url(board_url)
    seed = await fetcher(origin + "/", proxy, sem)
    headers = {}
    token = csrf_from_html(seed.body.decode("utf-8", "replace")) if seed.body else None
    if token:
        headers["X-CSRF-Token"] = token
    csb_url = f"{origin}/services/recruiting/v1/jobs"
    first = await fetcher(
        csb_url,
        proxy,
        sem,
        method="POST",
        json_body=csb_body(0, "India"),
        extra_headers=headers or None,
    )
    payload = _payload(first)
    if first.status in {200, 201} and isinstance(payload, dict) and not payload.get("error"):
        jobs, total = parse_csb(payload, origin)
        pages = list(range(1, (max(total, 0) + CSB_PAGE - 1) // CSB_PAGE))
        extras = await _post_pages(
            csb_url,
            [csb_body(page, "India") for page in pages],
            proxy,
            sem,
            fetcher,
            extra_headers=headers or None,
        )
        for page in extras:
            more, _total = parse_csb(_payload(page), origin)
            jobs.extend(more)
        matches = keep_matches(jobs, profile)
        return BoardOutcome(
            candidate,
            decide_status(first.status, jobs, matches, None),
            http_status=first.status,
            jobs=jobs,
            matches=matches,
            variant="csb",
        )
    jobs = await _poll_rmk(origin, proxy, sem, fetcher)
    matches = keep_matches(jobs, profile)
    http_status = 200 if jobs else first.status
    error = None if jobs else (first.error or "csb_and_rmk_empty")
    return BoardOutcome(
        candidate,
        decide_status(http_status if jobs else first.status, jobs, matches, error),
        http_status=http_status,
        error=error,
        jobs=jobs,
        matches=matches,
        variant="rmk",
    )


async def _poll_rmk(
    origin: str,
    proxy: str,
    sem: asyncio.Semaphore,
    fetcher: Fetcher,
) -> list[Job]:
    first = await fetcher(f"{origin}/tile-search-results/?startrow=0", proxy, sem)
    html = first.body.decode("utf-8", "replace") if first.body else ""
    jobs = parse_rmk_tiles(html, origin)
    if len(jobs) < 10:
        return jobs
    starts = list(range(10, RMK_CAP, 10))
    pages = await asyncio.gather(
        *[fetcher(f"{origin}/tile-search-results/?startrow={start}", proxy, sem) for start in starts]
    )
    seen = {job.source_job_id for job in jobs}
    for page in pages:
        extra = parse_rmk_tiles(page.body.decode("utf-8", "replace") if page.body else "", origin)
        for job in extra:
            if job.source_job_id in seen:
                continue
            seen.add(job.source_job_id)
            jobs.append(job)
    return jobs[:RMK_CAP]


async def poll_one(
    candidate: Candidate,
    proxy: str,
    sem: asyncio.Semaphore,
    profile: dict,
    fetcher: Fetcher,
    seeds: list[dict[str, Any]],
) -> BoardOutcome:
    ats = (candidate.ats or "").lower()
    try:
        if ats in SIMPLE_ATS:
            return await poll_simple(candidate, proxy, sem, profile, fetcher)
        url = board_url_for(candidate, seeds)
        if not url:
            return BoardOutcome(candidate, "error", error="missing_board_url")
        if ats == "workday":
            return await poll_workday(candidate, proxy, sem, profile, fetcher, url)
        if ats == "successfactors":
            return await poll_successfactors(candidate, proxy, sem, profile, fetcher, url)
        return BoardOutcome(candidate, "error", error=f"unsupported_ats:{ats}")
    except Exception as exc:
        return BoardOutcome(candidate, "error", error=scrub(f"{type(exc).__name__}:{exc}"))


def select_candidates(
    rows: list[Candidate],
    *,
    ats_filter: set[str] | None = None,
    limit: int | None = None,
    skip_ids: set[str] | None = None,
) -> tuple[list[Candidate], int]:
    skip_ids = skip_ids or set()
    todo: list[Candidate] = []
    skipped = 0
    for row in rows:
        ats = (row.ats or "").lower()
        if ats not in POLLABLE or not row.board_slug:
            continue
        if ats_filter and ats not in ats_filter:
            continue
        if row.candidate_id in skip_ids:
            skipped += 1
            continue
        todo.append(row)
        if limit and len(todo) >= limit:
            break
    return todo, skipped


def write_matches(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_candidate_statuses(path: Path, statuses: dict[str, str]) -> int:
    if not path.exists() or not statuses:
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    updated = 0
    out: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        data = json.loads(line)
        key = data.get("id")
        if key in statuses and data.get("status") != statuses[key]:
            data["status"] = statuses[key]
            updated += 1
        out.append(json.dumps(data, ensure_ascii=False))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return updated


async def poll_async(
    *,
    candidates: list[Candidate],
    store: Store,
    proxy: str,
    concurrency: int,
    profile: dict,
    resume: bool = False,
    ats_filter: set[str] | None = None,
    limit: int | None = None,
    fetcher: Fetcher = fetch_url,
    seeds: list[dict[str, Any]] | None = None,
    matches_path: Path = MATCHES_PATH,
    summary_path: Path = SUMMARY_PATH,
    candidates_path: Path | None = CANDIDATES_PATH,
) -> dict[str, Any]:
    seeds = seeds if seeds is not None else load_seed()
    running = store.latest_run("running") if resume else None
    if running:
        run_id = int(running["id"])
        started_at = running.get("started_at")
    else:
        run_id = store.create_run()
        created = store.latest_run()
        started_at = created.get("started_at") if created else None
    skip_ids = store.done_ids(run_id) if running else set()
    todo, skipped = select_candidates(
        candidates, ats_filter=ats_filter, limit=limit, skip_ids=skip_ids
    )
    yc_only = sum(1 for row in candidates if not row.board_slug)
    _log(
        f"poll: {len(todo)} boards · resume_skip={skipped} · "
        f"concurrency={concurrency} · run={run_id} · proxy=geonode"
    )
    counts: Counter[str] = Counter()
    by_ats: Counter[str] = Counter()
    match_total = 0
    t0 = time.time()
    if todo:
        sem = asyncio.Semaphore(concurrency)
        pending = [
            asyncio.create_task(poll_one(row, proxy, sem, profile, fetcher, seeds))
            for row in todo
        ]
        done = 0
        pending_flush = 0
        for coro in asyncio.as_completed(pending):
            outcome = await coro
            store.apply_board(
                outcome.candidate,
                run_id=run_id,
                all_jobs=outcome.jobs,
                matches=outcome.matches,
                status=outcome.status,
                http_status=outcome.http_status,
                error=outcome.error,
            )
            counts[outcome.status] += 1
            by_ats[outcome.candidate.ats or "none"] += 1
            match_total += len(outcome.matches)
            done += 1
            pending_flush += 1
            if pending_flush >= FLUSH_EVERY or done == len(todo):
                store.commit()
                pending_flush = 0
                elapsed = max(time.time() - t0, 1e-6)
                _log(
                    f"  {done}/{len(todo)}  active={counts['active']}  "
                    f"watch={counts['watch']}  empty={counts['empty']}  "
                    f"dead={counts['dead']}  error={counts['error']}  "
                    f"matches={match_total}  {done/elapsed:.1f}/s"
                )
    duration = time.time() - t0
    summary = {
        "wave": 2,
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_s": round(duration, 2),
        "concurrency": concurrency,
        "counts": {
            "polled": len(todo),
            "active": counts["active"],
            "watch": counts["watch"],
            "empty": counts["empty"],
            "dead": counts["dead"],
            "error": counts["error"],
            "matches": match_total,
            "skipped_resume": skipped,
            "yc_only_unpolled": yc_only,
        },
        "by_ats": dict(by_ats),
    }
    store.finish_run(run_id, summary["counts"])
    matches = store.open_matches()
    write_matches(matches_path, matches)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if candidates_path:
        updated = write_candidate_statuses(candidates_path, store.status_map())
        summary["candidates_status_updated"] = updated
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _log(
        f"done polled={len(todo)} active={counts['active']} matches={match_total} "
        f"{duration:.0f}s → {matches_path.name}"
    )
    return summary


def run(
    *,
    resume: bool = False,
    ats: list[str] | None = None,
    limit: int | None = None,
    concurrency: int = CONCURRENCY,
    candidates_path: Path = CANDIDATES_PATH,
    db_path: Path | None = None,
    fetcher: Fetcher = fetch_url,
) -> dict[str, Any]:
    proxy = load_geonode()
    profile = load_profile()
    store = Store(db_path)
    try:
        return asyncio.run(
            poll_async(
                candidates=load_candidates(candidates_path),
                store=store,
                proxy=proxy,
                concurrency=concurrency,
                profile=profile,
                resume=resume,
                ats_filter=parse_ats_flags(ats),
                limit=limit,
                fetcher=fetcher,
                candidates_path=candidates_path,
            )
        )
    finally:
        store.close()
