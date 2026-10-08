"""Workday public career-site CXS list API.

POST https://{tenant}.{shard}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
limit must stay at 20. Location is often in bulletFields or the path, not locationsText.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from job_radar.http import HttpClient
from job_radar.jobs import Job

WORKDAY_HOST = re.compile(
    r"^(?P<tenant>[^.]+)\.(?P<shard>wd\d+)\.myworkdayjobs\.com$",
    re.IGNORECASE,
)
SKIP_PATH = {"en-us", "en-gb", "en", "fr-fr", "de-de", "es", "ja-jp"}
PAGE_SIZE = 20


def parse_workday_url(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    host = WORKDAY_HOST.match(parsed.netloc)
    if not host:
        raise ValueError(f"not a Workday career host: {url}")
    tenant = host.group("tenant")
    shard = host.group("shard").lower()
    parts = [part for part in parsed.path.split("/") if part]
    parts = [part for part in parts if part.lower() not in SKIP_PATH]
    if not parts:
        raise ValueError(f"Workday URL missing site slug: {url}")
    site = parts[0]
    return {
        "tenant": tenant,
        "shard": shard,
        "site": site,
        "host": f"{tenant}.{shard}.myworkdayjobs.com",
        "board_slug": f"{tenant}/{site}",
    }


def jobs_url(board: dict[str, str]) -> str:
    return (
        f"https://{board['host']}/wday/cxs/{board['tenant']}/{board['site']}/jobs"
    )


def apply_url(board: dict[str, str], external_path: str) -> str:
    path = external_path if external_path.startswith("/") else f"/{external_path}"
    return f"https://{board['host']}/en-US/{board['site']}{path}"


def _locations(posting: dict[str, Any]) -> list[str]:
    found: list[str] = []
    text = posting.get("locationsText")
    if text:
        found.append(str(text))
    bullets = posting.get("bulletFields") or []
    if isinstance(bullets, list) and len(bullets) > 1:
        found.append(str(bullets[1]))
    path = str(posting.get("externalPath") or "")
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0].lower() == "job":
        found.append(parts[1].replace("-", " "))
    # Preserve order, drop empties/dupes.
    seen: set[str] = set()
    out: list[str] = []
    for item in found:
        cleaned = item.strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def _job_id(posting: dict[str, Any]) -> str:
    bullets = posting.get("bulletFields") or []
    if isinstance(bullets, list) and bullets:
        return str(bullets[0])
    path = str(posting.get("externalPath") or "")
    return path.rsplit("_", 1)[-1] or path


def search_body(offset: int = 0, search_text: str = "India") -> dict[str, Any]:
    return {
        "appliedFacets": {},
        "limit": PAGE_SIZE,
        "offset": offset,
        "searchText": search_text,
    }


def parse_list(payload: Any, board: dict[str, str]) -> tuple[list[Job], int]:
    if not isinstance(payload, dict):
        return [], 0
    total = int(payload.get("total") or 0)
    postings = payload.get("jobPostings") or []
    if not isinstance(postings, list):
        return [], total
    jobs = [posting_to_job(item, board) for item in postings if isinstance(item, dict)]
    return jobs, total


def posting_to_job(posting: dict[str, Any], board: dict[str, str]) -> Job:
    path = str(posting.get("externalPath") or "")
    return Job(
        ats="workday",
        board_slug=board["board_slug"],
        source_job_id=_job_id(posting),
        title=str(posting.get("title") or "").strip(),
        locations=_locations(posting),
        apply_url=apply_url(board, path) if path else "",
        raw=posting,
    )


def list_jobs(
    board_url: str,
    *,
    client: HttpClient | None = None,
    search_text: str = "",
    max_pages: int = 1,
) -> tuple[list[Job], int]:
    board = parse_workday_url(board_url)
    http = client or HttpClient()
    jobs: list[Job] = []
    total = 0
    for page in range(max_pages):
        status, payload, _ctype = http.post_json(
            jobs_url(board),
            {
                "appliedFacets": {},
                "limit": PAGE_SIZE,
                "offset": page * PAGE_SIZE,
                "searchText": search_text,
            },
        )
        if status != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"Workday list failed ({status}) for {board['board_slug']}")
        if page == 0:
            total = int(payload.get("total") or 0)
        postings = payload.get("jobPostings") or []
        if not isinstance(postings, list) or not postings:
            break
        jobs.extend(posting_to_job(item, board) for item in postings if isinstance(item, dict))
        if len(postings) < PAGE_SIZE:
            break
    return jobs, total
