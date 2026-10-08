"""Acceptance-weighted ranker. Top of inbox = roles the profile is likely to get."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_radar.filters import load_profile, min_lpa
from job_radar.hints import blob, chennai_hint, india_hint, remote_hint
from job_radar.jobs import Job
from job_radar.store import ROOT, Store

INBOX_PATH = ROOT / "data" / "inbox.jsonl"
MATCHES_PATH = ROOT / "data" / "matches.jsonl"
INBOX_CSV_PATH = ROOT / "data" / "inbox.csv"
SUMMARY_PATH = ROOT / "data" / "rank_summary.json"

FAMILY_POINTS = {
    "voice_ai": 40,
    "itom_servicenow": 30,
    "ai_automation": 28,
    "python_backend": 26,
    "software_engineer": 8,
}
_PROOF = re.compile(r"\b(servicenow|cmdb|itsm|itom|voice ai|ivr|ivp|stt|tts)\b", re.I)
_STRONG = re.compile(
    r"\b(python|fastapi|webhook|mongodb|llm|agentic|genai|gen ai|"
    r"infinity|dify|servicenow|cmdb|itom|voice|ivp|ivr|rest)\b",
    re.I,
)
_SECONDARY = re.compile(r"\b(ionic|angular|typescript|react native|react-native|capacitor)\b", re.I)
_YOE_RANGE = re.compile(r"\b(\d+)\s*[-–]\s*(\d+)\s*\+?\s*(?:years|yrs)\b", re.I)
_YOE_PLUS = re.compile(r"\b(\d+)\s*\+\s*(?:years|yrs)\b", re.I)
_YOE_ONE = re.compile(r"\b(\d+)\s*(?:years|yrs)\b", re.I)
_JUNIOR = re.compile(r"\b(junior|associate|jr\.?|sde[- ]?i\b|sde[- ]?1|swe[- ]?i\b|engineer i\b)\b", re.I)
_SDE2 = re.compile(r"\b(sde[- ]?ii\b|sde[- ]?2|swe[- ]?ii\b|engineer ii\b)\b", re.I)
_SENIOR = re.compile(r"\b(senior|sr\.?)\b", re.I)
_LEAD = re.compile(r"\b(lead|staff|principal)\b", re.I)
_RESEARCHER = re.compile(r"\bresearcher\b", re.I)
_FRONTEND = re.compile(r"\b(frontend|front-end|front end|ui developer|ui engineer)\b", re.I)
_JUNKISH = re.compile(
    r"\b(customer service|professionals|screen recording|feedback on|"
    r"qa analyst|system administrator|business system analyst|"
    r"platform support|evaluation specialist|"
    r"security cleared|security clearance)\b",
    re.I,
)
_US_GEO = re.compile(
    r"\b(united states|u\.s\.|usa|san francisco|new york|seattle|denver|"
    r"austin|boston|chicago|los angeles|mountain view|remote us)\b",
    re.I,
)
_EPOCH_MS = re.compile(r"^\d{12,13}$")
_EPOCH_S = re.compile(r"^\d{9,10}$")


@dataclass
class RankResult:
    score: int
    why: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    geo: str = "other"


def _text(title: str, locations: list[str], *extra: object) -> str:
    return blob(title, locations, *extra)


def _locations(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except json.JSONDecodeError:
            pass
        return [value]
    return []


def _parse_posted(raw: object) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if _EPOCH_MS.match(text):
        return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
    if _EPOCH_S.match(text):
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _yoe_band(title: str) -> tuple[int | None, int | None]:
    match = _YOE_RANGE.search(title)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = _YOE_PLUS.search(title)
    if match:
        return int(match.group(1)), None
    match = _YOE_ONE.search(title)
    if match:
        years = int(match.group(1))
        return years, years
    return None, None


def _geo(title: str, locations: list[str], is_remote: bool | None) -> tuple[str, int, list[str], list[str]]:
    text = _text(title, locations)
    why: list[str] = []
    concerns: list[str] = []
    india = india_hint(text)
    chennai = chennai_hint(text)
    remote = bool(is_remote) or remote_hint(text)
    hybrid = bool(re.search(r"\bhybrid\b", text, re.I))
    us = bool(_US_GEO.search(text))
    if chennai:
        why.append("Chennai location")
        return "chennai", 22, why, concerns
    if india and remote:
        why.append("India remote")
        return "india_remote", 18, why, concerns
    if india and hybrid:
        why.append("India hybrid")
        return "india_hybrid", 16, why, concerns
    if india:
        why.append("India onsite")
        return "india", 12, why, concerns
    if remote and not us:
        why.append("worldwide remote")
        return "remote", 3, why, concerns
    if remote and us:
        concerns.append("US timezone")
        return "us_remote", 1, why, concerns
    if us:
        concerns.append("no India mention")
        return "us", 0, why, concerns
    return "other", 1, why, concerns


def score_text(
    *,
    title: str,
    locations: list[str],
    family: str | None,
    salary_text: str | None,
    salary_bucket: str | None,
    posted_at: object = None,
    is_remote: bool | None = None,
    india_company: bool = False,
    profile: dict | None = None,
) -> RankResult:
    profile = profile or {}
    min_want = float(profile.get("min_lpa") or 12)
    yoe = int(profile.get("yoe") or 3)
    title = title or ""
    locations = _locations(locations)
    text = _text(title, locations, salary_text)
    score = 0
    why: list[str] = []
    concerns: list[str] = []

    family_pts = FAMILY_POINTS.get(family or "", 4)
    score += family_pts
    if family == "voice_ai":
        why.append("voice AI — resume proof, thin applicant pool")
    elif family == "itom_servicenow" and re.search(r"\bservicenow\b", title, re.I):
        score += 10
        why.append("ServiceNow title — direct profile overlap")
    elif family == "itom_servicenow":
        why.append("ITOM / platform / automation family")
    elif family == "ai_automation":
        why.append("AI automation / GenAI family")
    elif family == "python_backend":
        why.append("Python / backend family")
    else:
        why.append("generic software engineer (low callback odds)")

    if _PROOF.search(title) and family not in {"voice_ai", "itom_servicenow"}:
        score += 8
        why.append("ServiceNow / voice signal in title")

    strong_hits = {m.group(0).lower() for m in _STRONG.finditer(text)}
    if strong_hits:
        stack_pts = min(15, 5 * len(strong_hits))
        score += stack_pts
        why.append("stack overlap: " + ", ".join(sorted(strong_hits)[:5]))
    elif _SECONDARY.search(title):
        score += 1
        concerns.append("older mobile/frontend stack")

    lo, hi = _yoe_band(title)
    if lo is not None:
        if lo <= 4 and (hi is None or hi <= 6):
            score += 10
            why.append(f"YOE band fits {yoe} years")
        elif lo <= 6:
            score -= 6
            concerns.append("asks 5–6 years")
        else:
            score -= 12
            concerns.append("YOE above her apply band")
    elif _JUNIOR.search(title):
        score += 8
        why.append("junior / associate / SDE I")
    elif _SDE2.search(title):
        score += 6
        why.append("SDE II / Engineer II — reachable at 3 YOE")

    if _LEAD.search(title):
        score -= 6
        concerns.append("title says Lead")
    elif _SENIOR.search(title):
        score -= 4
        concerns.append("title says Senior")
    if _RESEARCHER.search(title):
        score -= 10
        concerns.append("researcher title — low interview odds")
    if _FRONTEND.search(title):
        score -= 12
        concerns.append("frontend / UI title")
    if _JUNKISH.search(title):
        score -= 20
        concerns.append("support / survey / clearance role")

    geo, geo_pts, geo_why, geo_concerns = _geo(title, locations, is_remote)
    score += geo_pts
    why.extend(geo_why)
    concerns.extend(geo_concerns)

    if india_company and geo in {"us_remote", "us", "remote", "other"}:
        score += 3
        why.append("company has an India hint")

    bucket = salary_bucket or "unknown"
    stated = min_lpa(salary_text)
    if stated is not None and stated >= min_want:
        bucket = "confirmed"
    if bucket == "confirmed":
        score += 10
        why.append(f"salary confirmed ≥ {int(min_want)} LPA")
    elif bucket == "below_floor":
        concerns.append("salary below 12 LPA")

    posted = _parse_posted(posted_at)
    if posted:
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - posted.astimezone(timezone.utc)).days
        if age <= 14:
            score += 8
            why.append("posted in last 2 weeks")
        elif age <= 45:
            score += 4
            why.append("posted in last 6 weeks")
        elif age > 180:
            score -= 2
            concerns.append("stale listing")

    return RankResult(score=score, why=why, concerns=concerns, geo=geo)


def score_job(job: Job, profile: dict | None = None, *, india_company: bool = False) -> RankResult:
    profile = profile or load_profile()
    return score_text(
        title=job.title,
        locations=job.locations,
        family=job.family,
        salary_text=job.salary_text,
        salary_bucket=job.salary_bucket,
        posted_at=job.posted_at,
        is_remote=job.is_remote,
        india_company=india_company,
        profile=profile,
    )


def score_row(row: dict[str, Any], profile: dict | None = None) -> RankResult:
    profile = profile or load_profile()
    return score_text(
        title=str(row.get("title") or ""),
        locations=_locations(row.get("locations")),
        family=row.get("family"),
        salary_text=row.get("salary_text"),
        salary_bucket=row.get("salary_bucket"),
        posted_at=row.get("posted_at"),
        is_remote=bool(row.get("is_remote")) if row.get("is_remote") is not None else None,
        india_company=bool(row.get("india_hint") or row.get("company_india_hint")),
        profile=profile,
    )


def rank_store(store: Store, profile: dict | None = None) -> list[dict[str, Any]]:
    profile = profile or load_profile()
    store.ensure_rank_columns()
    rows = store.open_matches()
    ranked: list[dict[str, Any]] = []
    for row in rows:
        result = score_row(row, profile)
        item = dict(row)
        item["locations"] = _locations(item.get("locations"))
        item["score"] = result.score
        item["why"] = result.why
        item["concerns"] = result.concerns
        item["geo"] = result.geo
        ranked.append(item)
    ranked.sort(key=lambda row: (-int(row["score"] or 0), str(row.get("title") or "")))
    store.save_ranks(ranked)
    return ranked


def write_inbox(rows: list[dict[str, Any]], path: Path = INBOX_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return path


def write_inbox_csv(rows: list[dict[str, Any]], path: Path = INBOX_CSV_PATH, limit: int = 50) -> Path:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "score",
        "family",
        "title",
        "company_name",
        "locations",
        "why",
        "concerns",
        "salary_text",
        "apply_url",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in dedupe_inbox(rows)[:limit]:
            writer.writerow(
                {
                    "score": row.get("score"),
                    "family": row.get("family"),
                    "title": row.get("title"),
                    "company_name": row.get("company_name"),
                    "locations": "; ".join(_locations(row.get("locations"))),
                    "why": " | ".join(row.get("why") or []),
                    "concerns": " | ".join(row.get("concerns") or []),
                    "salary_text": row.get("salary_text") or "",
                    "apply_url": row.get("apply_url") or "",
                }
            )
    return path


def dedupe_inbox(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (
            str(row.get("company_name") or row.get("company_id") or "").lower(),
            str(row.get("title") or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def format_inbox(rows: list[dict[str, Any]], limit: int = 20) -> str:
    lines: list[str] = []
    for index, row in enumerate(dedupe_inbox(rows)[:limit], start=1):
        locs = "; ".join(_locations(row.get("locations"))) or "location unknown"
        lines.append(
            f"{index:2}. {int(row.get('score') or 0):3}  {row.get('title')}"
            f" — {row.get('company_name') or row.get('company_id')}"
        )
        lines.append(f"    {row.get('family')} · {locs}")
        if row.get("why"):
            lines.append("    why: " + "; ".join(row["why"][:4]))
        if row.get("concerns"):
            lines.append("    concern: " + "; ".join(row["concerns"]))
        if row.get("fit") or row.get("brief"):
            lines.append(
                f"    fit={row.get('fit') or '?'}  india={row.get('india_eligible') or '?'}  "
                f"us_trap={row.get('us_only_trap')}"
            )
        if row.get("brief"):
            lines.append(f"    {row['brief']}")
        if row.get("apply_url"):
            lines.append(f"    {row['apply_url']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run(
    *,
    db_path: Path | None = None,
    limit: int = 20,
    matches_path: Path = MATCHES_PATH,
) -> dict[str, Any]:
    profile = load_profile()
    store = Store(db_path)
    try:
        ranked = rank_store(store, profile)
    finally:
        store.close()
    write_inbox(ranked)
    write_inbox_csv(ranked)
    write_inbox(ranked, matches_path)
    families: dict[str, int] = {}
    geos: dict[str, int] = {}
    for row in ranked:
        families[str(row.get("family") or "none")] = families.get(str(row.get("family") or "none"), 0) + 1
        geos[str(row.get("geo") or "other")] = geos.get(str(row.get("geo") or "other"), 0) + 1
    top = ranked[:limit]
    summary = {
        "wave": 3,
        "ranked": len(ranked),
        "inbox_limit": limit,
        "top_score": top[0]["score"] if top else None,
        "top_title": top[0].get("title") if top else None,
        "families": families,
        "geo": geos,
        "outputs": {
            "inbox_jsonl": str(INBOX_PATH.relative_to(ROOT)),
            "inbox_csv": str(INBOX_CSV_PATH.relative_to(ROOT)),
        },
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return {"summary": summary, "ranked": ranked}
