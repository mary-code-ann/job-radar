"""Lever public postings list."""

from __future__ import annotations

from typing import Any

from job_radar.jobs import Job


def list_url(slug: str) -> str:
    return f"https://api.lever.co/v0/postings/{slug}?mode=json"


def _salary_text(row: dict[str, Any]) -> str | None:
    salary = row.get("salaryRange") or row.get("salary")
    if isinstance(salary, dict):
        parts = [salary.get("currency"), salary.get("min"), salary.get("max"), salary.get("interval")]
        text = " ".join(str(part) for part in parts if part not in (None, ""))
        return text or None
    if salary:
        return str(salary)
    return None


def parse_list(payload: Any, slug: str) -> list[Job]:
    rows = payload if isinstance(payload, list) else payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    jobs: list[Job] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cats = row.get("categories") or {}
        loc = ""
        if isinstance(cats, dict):
            loc = str(cats.get("location") or cats.get("allLocations") or "").strip()
        workplace = str(row.get("workplaceType") or (cats.get("commitment") if isinstance(cats, dict) else "") or "")
        is_remote = workplace.lower() in {"remote", "fully remote", "hybrid"}
        if is_remote and workplace.lower() == "hybrid":
            is_remote = None
        created = row.get("createdAt")
        posted = str(created) if created else None
        jobs.append(
            Job(
                ats="lever",
                board_slug=slug,
                source_job_id=str(row.get("id") or ""),
                title=str(row.get("text") or row.get("title") or "").strip(),
                locations=[loc] if loc else [],
                apply_url=str(row.get("hostedUrl") or row.get("applyUrl") or ""),
                is_remote=True if workplace.lower() in {"remote", "fully remote"} else is_remote,
                posted_at=posted,
                salary_text=_salary_text(row),
                raw=row,
            )
        )
    return jobs
