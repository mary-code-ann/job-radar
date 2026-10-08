"""Greenhouse public job-board list (no descriptions)."""

from __future__ import annotations

from typing import Any

from job_radar.jobs import Job


def list_url(slug: str) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def parse_list(payload: Any, slug: str) -> list[Job]:
    rows = payload.get("jobs") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    jobs: list[Job] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        loc = row.get("location")
        if isinstance(loc, dict):
            loc_name = str(loc.get("name") or "").strip()
        else:
            loc_name = str(loc or "").strip()
        offices = row.get("offices") or []
        extra = []
        if isinstance(offices, list):
            for office in offices:
                if isinstance(office, dict) and office.get("name"):
                    extra.append(str(office["name"]))
        locations = [item for item in [loc_name, *extra] if item]
        jobs.append(
            Job(
                ats="greenhouse",
                board_slug=slug,
                source_job_id=str(row.get("id") or ""),
                title=str(row.get("title") or "").strip(),
                locations=locations,
                apply_url=str(row.get("absolute_url") or ""),
                posted_at=str(row.get("first_published") or row.get("updated_at") or "") or None,
                raw=row,
            )
        )
    return jobs
