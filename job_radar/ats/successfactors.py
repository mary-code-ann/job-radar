"""SAP SuccessFactors public career-site lists.

Two live variants:
- CSB JSON: POST {origin}/services/recruiting/v1/jobs  (Wipro, HCLTech)
- RMK tiles: GET {origin}/tile-search-results/?startrow=N  (Capgemini)
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import unquote, urlparse

from job_radar.http import HttpClient
from job_radar.jobs import Job

CSRF_RE = re.compile(r'X-CSRF-Token"\s*:\s*"([^"]+)"')
TILE_RE = re.compile(
    r'<li class="[^"]*job-tile job-id-(?P<id>\d+)[^"]*" data-url="(?P<url>[^"]+)"',
    re.IGNORECASE,
)
TITLE_RE = re.compile(
    r'<a class="[^"]*jobTitle-link[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>\s*(?P<title>[^<]+?)\s*</a>',
    re.IGNORECASE,
)


def origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"not an http career URL: {url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def board_slug_from_url(url: str) -> str:
    return urlparse(url).netloc.lower()


def _flatten(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten(item))
        return out
    if isinstance(value, dict):
        return _flatten(value.get("value") or value.get("name"))
    text = unescape(re.sub(r"<[^>]+>", " ", str(value)))
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return [text] if text else []


def _csb_job(row: dict[str, Any], origin: str, slug: str) -> Job:
    body = row.get("response") if isinstance(row.get("response"), dict) else row
    job_id = str(body.get("id") or "").strip()
    title = str(body.get("unifiedStandardTitle") or body.get("title") or "").strip()
    url_title = str(body.get("unifiedUrlTitle") or body.get("urlTitle") or "").strip()
    locales = body.get("supportedLocales") or ["en_US"]
    locale = locales[0] if isinstance(locales, list) and locales else "en_US"
    apply = f"{origin}/job/{url_title}/{job_id}-{locale}" if url_title and job_id else origin
    locations = (
        _flatten(body.get("jobLocationShort"))
        or _flatten(body.get("sfstd_jobLocation_obj"))
        or _flatten(body.get("jobLocationCountry"))
        or _flatten(body.get("custCountryRegion"))
        or _flatten(body.get("custprimecity"))
    )
    return Job(
        ats="successfactors",
        board_slug=slug,
        source_job_id=job_id,
        title=title,
        locations=locations,
        apply_url=apply,
        raw=body if isinstance(body, dict) else row,
    )


def csrf_from_html(html: str) -> str | None:
    match = CSRF_RE.search(html)
    return match.group(1) if match else None


def csb_body(page: int = 0, keywords: str = "India", location: str = "") -> dict[str, Any]:
    return {
        "locale": "en_US",
        "pageNumber": page,
        "categoryId": 0,
        "keywords": keywords,
        "location": location,
        "facetFilters": {},
        "brand": "",
        "skills": [],
    }


def parse_csb(payload: Any, origin: str) -> tuple[list[Job], int]:
    if not isinstance(payload, dict) or payload.get("error"):
        return [], 0
    slug = board_slug_from_url(origin)
    total = int(payload.get("totalJobs") or 0)
    rows = payload.get("jobSearchResult") or []
    if not isinstance(rows, list):
        return [], total
    jobs = [_csb_job(row, origin, slug) for row in rows if isinstance(row, dict)]
    return jobs, total


def _seed_csb(http: HttpClient, origin: str) -> dict[str, str]:
    _status, html, _ctype = http.get(origin + "/")
    extra: dict[str, str] = {}
    match = CSRF_RE.search(html)
    if match:
        extra["X-CSRF-Token"] = match.group(1)
    return extra


def list_csb(
    origin: str,
    *,
    client: HttpClient | None = None,
    keywords: str = "",
    location: str = "",
    max_pages: int = 1,
) -> tuple[list[Job], int]:
    http = client or HttpClient()
    slug = board_slug_from_url(origin)
    extra = _seed_csb(http, origin)
    jobs: list[Job] = []
    total = 0
    for page in range(max_pages):
        status, payload, _ctype = http.post_json(
            f"{origin}/services/recruiting/v1/jobs",
            {
                "locale": "en_US",
                "pageNumber": page,
                "categoryId": 0,
                "keywords": keywords,
                "location": location,
                "facetFilters": {},
                "brand": "",
                "skills": [],
            },
            extra_headers=extra,
        )
        if status != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"SuccessFactors CSB failed ({status}) for {origin}")
        if payload.get("error"):
            raise RuntimeError(f"SuccessFactors CSB error for {origin}: {payload['error']}")
        if page == 0:
            total = int(payload.get("totalJobs") or 0)
        rows = payload.get("jobSearchResult") or []
        if not isinstance(rows, list) or not rows:
            break
        jobs.extend(_csb_job(row, origin, slug) for row in rows if isinstance(row, dict))
        if len(rows) < 10:
            break
    return jobs, total


def _location_from_rmk_path(path: str) -> str:
    parts = [part for part in unquote(path).split("/") if part]
    if len(parts) >= 2 and parts[0] == "job":
        city = parts[1].split("-")[0].replace("%2C", "").strip()
        return city
    return ""


def parse_rmk_tiles(html: str, origin: str) -> list[Job]:
    slug = board_slug_from_url(origin)
    titles = {
        unescape(match.group("href")): unescape(match.group("title")).strip()
        for match in TITLE_RE.finditer(html)
    }
    jobs: list[Job] = []
    seen: set[str] = set()
    for match in TILE_RE.finditer(html):
        job_id = match.group("id")
        if job_id in seen:
            continue
        seen.add(job_id)
        path = unescape(match.group("url"))
        title = titles.get(path) or path.rsplit("/", 2)[-2].replace("-", " ")
        city = _location_from_rmk_path(path)
        jobs.append(
            Job(
                ats="successfactors",
                board_slug=slug,
                source_job_id=job_id,
                title=title,
                locations=[city] if city else [],
                apply_url=origin.rstrip("/") + path,
                raw={"path": path},
            )
        )
    return jobs


def list_rmk(
    origin: str,
    *,
    client: HttpClient | None = None,
    max_pages: int = 1,
) -> tuple[list[Job], int]:
    http = client or HttpClient()
    jobs: list[Job] = []
    start = 0
    for _page in range(max_pages):
        _status, html, _ctype = http.get(f"{origin}/tile-search-results/?startrow={start}")
        page_jobs = parse_rmk_tiles(html, origin)
        if not page_jobs:
            break
        jobs.extend(page_jobs)
        start += len(page_jobs)
        if len(page_jobs) < 10:
            break
    return jobs, len(jobs)


def list_jobs(
    board_url: str,
    *,
    client: HttpClient | None = None,
    keywords: str = "",
    location: str = "",
    max_pages: int = 1,
) -> tuple[list[Job], int, str]:
    """Try CSB JSON first, then RMK tiles. Returns jobs, total, variant."""
    origin = origin_from_url(board_url)
    http = client or HttpClient()
    try:
        jobs, total = list_csb(
            origin,
            client=http,
            keywords=keywords,
            location=location,
            max_pages=max_pages,
        )
        return jobs, total, "csb"
    except Exception:
        jobs, total = list_rmk(origin, client=http, max_pages=max_pages)
        if not jobs and not total:
            raise
        return jobs, total, "rmk"
