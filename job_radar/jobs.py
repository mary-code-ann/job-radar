"""Normalized public job row from any ATS list endpoint."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Job:
    ats: str
    board_slug: str
    source_job_id: str
    title: str
    locations: list[str] = field(default_factory=list)
    apply_url: str = ""
    is_remote: bool | None = None
    posted_at: str | None = None
    salary_text: str | None = None
    salary_bucket: str = "unknown"
    family: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("raw", None)
        return payload
