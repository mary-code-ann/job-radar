"""CSV export for Google Sheets."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from job_radar.hints import remote_hint
from job_radar.store import ROOT, Store

STRONG_CSV = ROOT / "data" / "strong.csv"

_HYBRID = re.compile(r"\bhybrid\b", re.I)


def _list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except json.JSONDecodeError:
            return [value]
    return []


def _join(value: object) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if item)
    return str(value or "")


def remote_label(row: dict[str, Any]) -> str:
    locs = _join(_list(row.get("locations")))
    flag = row.get("is_remote")
    hybrid = bool(_HYBRID.search(locs))
    remote = flag == 1 or flag is True or remote_hint(locs)
    if remote and hybrid:
        return "Remote / hybrid"
    if remote:
        return "Yes"
    if hybrid:
        return "Hybrid"
    if flag == 0 or flag is False:
        return "No"
    return "Unknown"


def sheet_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": row.get("score"),
        "fit": row.get("fit") or "",
        "family": row.get("family") or "",
        "title": row.get("title") or "",
        "company": row.get("company_name") or row.get("company_id") or "",
        "locations": _join(_list(row.get("locations"))),
        "remote": remote_label(row),
        "india_eligible": row.get("india_eligible") or "",
        "us_only_trap": "Yes" if row.get("us_only_trap") else "No",
        "implied_yoe": row.get("implied_yoe") or "",
        "salary_listed": row.get("salary_text") or "",
        "salary_guess_lpa": row.get("salary_guess") or "",
        "skills": _join(_list(row.get("skills"))),
        "why": _join(_list(row.get("why"))),
        "concerns": _join(_list(row.get("concerns"))),
        "ai_brief": (row.get("brief") or "").replace("\n", " ").strip(),
        "apply_url": row.get("apply_url") or "",
        "ats": row.get("ats") or "",
        "posted_at": row.get("posted_at") or "",
    }


def write_fit_csv(rows: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(sheet_row(rows[0] if rows else {"title": ""}).keys())
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(sheet_row(row))
    return path


def run(*, fit: str = "strong", path: Path | None = None, db_path: Path | None = None) -> dict[str, Any]:
    store = Store(db_path)
    try:
        rows = [
            row
            for row in store.briefed_jobs()
            if str(row.get("fit") or "").lower() == fit.lower()
        ]
    finally:
        store.close()
    out = path or (ROOT / "data" / f"{fit}.csv")
    write_fit_csv(rows, out)
    return {"fit": fit, "rows": len(rows), "path": str(out)}
