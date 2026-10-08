"""Ashby public job-board list."""

from __future__ import annotations

from typing import Any

from job_radar.jobs import Job


def list_url(slug: str) -> str:
    return f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"


def _salary_text(row: dict[str, Any]) -> str | None:
    comp = row.get("compensation") or row.get("compensationTierSummary")
    if isinstance(comp, dict):
        parts = [
            comp.get("compensationTierSummary"),
            comp.get("summary"),
            comp.get("minValue"),
            comp.get("maxValue"),
            comp.get("currencyCode"),
        ]
        text = " ".join(str(part) for part in parts if part not in (None, ""))
        return text or None
    if isinstance(comp, str) and comp.strip():
        return comp.strip()
    return None


def _locations(row: dict[str, Any]) -> list[str]:
    found: list[str] = []
    loc = row.get("location")
    if isinstance(loc, str) and loc.strip():
        found.append(loc.strip())
    elif isinstance(loc, dict) and loc.get("name"):
        found.append(str(loc["name"]))
    secondary = row.get("secondaryLocations") or []
    if isinstance(secondary, list):
        for item in secondary:
            if isinstance(item, str) and item.strip():
                found.append(item.strip())
            elif isinstance(item, dict) and item.get("location"):
                found.append(str(item["location"]))
            elif isinstance(item, dict) and item.get("name"):
                found.append(str(item["name"]))
    return found


def parse_list(payload: Any, slug: str) -> list[Job]:
    rows = payload.get("jobs") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    jobs: list[Job] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        remote = row.get("isRemote")
        jobs.append(
            Job(
                ats="ashby",
                board_slug=slug,
                source_job_id=str(row.get("id") or ""),
                title=str(row.get("title") or "").strip(),
                locations=_locations(row),
                apply_url=str(row.get("jobUrl") or row.get("applyUrl") or ""),
                is_remote=bool(remote) if remote is not None else None,
                posted_at=str(row.get("publishedAt") or "") or None,
                salary_text=_salary_text(row),
                raw=row,
            )
        )
    return jobs
