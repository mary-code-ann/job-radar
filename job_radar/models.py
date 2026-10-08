"""Wave 1 candidate row. Status stays unproven until Wave 2 hits ATS APIs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Candidate:
    name: str
    normalized_name: str
    ats: str | None
    board_slug: str | None
    board_url: str | None = None
    status: str = "unproven"
    sources: list[str] = field(default_factory=list)
    recent_job_count: int | None = None
    lastround_crawled: str | None = None
    mcp_checked: str | None = None
    website: str | None = None
    yc_slug: str | None = None
    yc_hiring: bool | None = None
    yc_locations: str | None = None
    yc_regions: list[str] = field(default_factory=list)
    yc_one_liner: str | None = None
    yc_industry: str | None = None
    india_hint: bool = False
    remote_hint: bool = False
    chennai_hint: bool = False

    @property
    def candidate_id(self) -> str:
        if self.ats and self.board_slug:
            return f"{self.ats}:{self.board_slug}"
        if self.yc_slug:
            return f"yc:{self.yc_slug}"
        return f"name:{self.normalized_name}"

    def add_source(self, source: str) -> None:
        if source not in self.sources:
            self.sources.append(source)

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["id"] = self.candidate_id
        return payload
