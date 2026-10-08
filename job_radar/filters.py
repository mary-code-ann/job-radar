"""Profile-specific keep/reject gates. Highest acceptance, not max coverage."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from job_radar.hints import blob, india_hint, remote_hint
from job_radar.jobs import Job

ROOT = Path(__file__).resolve().parent.parent
PROFILE_PATH = ROOT / "data" / "profile.json"

_JUNK = re.compile(
    r"\b(sales|account executive|account exec|recruiter|recruiting|sourcer|"
    r"designer|product designer|product manager\b|program manager|"
    r"customer success|support engineer|helpdesk|help desk|data entry|"
    r"business development|bdr|sdr)\b",
    re.I,
)
_SENIOR = re.compile(
    r"\b(staff|principal|distinguished|fellow|director|vice president|\bvp\b|"
    r"head of|engineering manager|eng(?:ineering)? mgr)\b",
    re.I,
)
_ARCHITECT = re.compile(r"\barchitect\b", re.I)
_JUNIOR_ARCH = re.compile(r"\b(junior|associate|jr)\b.*\barchitect\b|\barchitect\b.*\b(junior|associate|jr)\b", re.I)
_HIGH_YOE = re.compile(
    r"\b([5-9]|1[0-9])\s*\+\s*years|\b([5-9]|1[0-9])\s*[-–]\s*\d+\s*years|"
    r"\b([5-9]|1[0-9])\+?\s*yrs\b",
    re.I,
)
_INTERN = re.compile(r"\b(intern|internship|student|campus hire|new grad|graduate trainee)\b", re.I)
_MOBILE = re.compile(
    r"\b(ios|android|react native|react-native|flutter|mobile developer|"
    r"mobile engineer|ionic)\b",
    re.I,
)
_JAVA_NET = re.compile(r"\b(java|spring boot|springboot|\.net|c#)\b", re.I)
_PYTHON_AI = re.compile(
    r"\b(python|fastapi|genai|llm|agentic|automation|servicenow|voice)\b",
    re.I,
)
_US_ONLY = re.compile(
    r"authorized to work in the (united states|u\.s|uk|united kingdom)|"
    r"must be (located )?in the (united states|u\.s|uk|united kingdom)|"
    r"\b(us only|u\.s\. only|united states only|uk only|united kingdom only)\b|"
    r"visa sponsorship (is )?(not|unavailable)|no sponsorship",
    re.I,
)
_HYBRID_APAC = re.compile(r"\b(hybrid|apac|asia[-\s]?pacific)\b", re.I)
_FRONTEND_ONLY = re.compile(r"\b(frontend|front-end|front end)\b", re.I)

_FAMILIES: list[tuple[str, re.Pattern[str]]] = [
    (
        "voice_ai",
        re.compile(
            r"\b(voice ai|ivr|ivp|conversational ai|speech|stt|tts|"
            r"contact.?center ai|voice engineer)\b",
            re.I,
        ),
    ),
    (
        "ai_automation",
        re.compile(
            r"\b(ai automation|agentic|genai|gen ai|llm|prompt engineer|"
            r"applied ai|infinity|dify|workflow orchestration|ai engineer|"
            r"machine learning engineer)\b",
            re.I,
        ),
    ),
    (
        "python_backend",
        re.compile(
            r"\b(python (developer|engineer)|fastapi|backend engineer|"
            r"backend developer|python backend)\b",
            re.I,
        ),
    ),
    (
        "itom_servicenow",
        re.compile(
            r"\b(servicenow|cmdb|itsm|itom|integration engineer|"
            r"webhook|automation engineer|sre|platform engineer)\b",
            re.I,
        ),
    ),
]
_SDE = re.compile(r"\b(software engineer|software developer|sde|sde[- ]?[12i]+|swe)\b", re.I)

_LPA = re.compile(r"(\d+(?:\.\d+)?)\s*(?:[-–to]+)?\s*(\d+(?:\.\d+)?)?\s*lpa", re.I)
_LAKH = re.compile(r"(\d+(?:\.\d+)?)\s*(?:[-–to]+)?\s*(\d+(?:\.\d+)?)?\s*lakh", re.I)
_INR = re.compile(r"(?:₹|inr)\s*([\d,]+(?:\.\d+)?)", re.I)


def load_profile(path: Path | None = None) -> dict:
    return json.loads((path or PROFILE_PATH).read_text(encoding="utf-8"))


def job_text(job: Job) -> str:
    return blob(job.title, job.locations, job.salary_text, job.apply_url)


def geo_ok(job: Job) -> bool:
    text = job_text(job)
    if job.is_remote:
        return True
    if _HYBRID_APAC.search(text):
        return True
    return india_hint(text) or remote_hint(text)


def us_only(job: Job) -> bool:
    text = job_text(job)
    if not _US_ONLY.search(text):
        return False
    return not india_hint(text)


def min_lpa(text: str | None) -> float | None:
    if not text:
        return None
    match = _LPA.search(text) or _LAKH.search(text)
    if match:
        return float(match.group(1))
    if re.search(r"₹|inr|\blakh\b|\blpa\b", text, re.I):
        money = _INR.search(text)
        if money:
            raw = money.group(1).replace(",", "")
            value = float(raw)
            if value >= 100000:
                return value / 100000
            if value >= 1000:
                return value / 100000
            return value
    return None


def salary_bucket(job: Job, *, hard_floor: float = 8, min_lpa_want: float = 12) -> str:
    value = min_lpa(job.salary_text)
    if value is None:
        return "unknown"
    if value < hard_floor:
        return "reject_low"
    if value < min_lpa_want:
        return "below_floor"
    return "confirmed"


def family_for(title: str) -> str | None:
    for name, pattern in _FAMILIES:
        if pattern.search(title):
            return name
    return None


@dataclass
class GateResult:
    keep: bool
    reason: str
    family: str | None = None
    salary_bucket: str = "unknown"


def gate(job: Job, profile: dict | None = None) -> GateResult:
    profile = profile or load_profile()
    hard_floor = float(profile.get("hard_floor_lpa") or 8)
    min_want = float(profile.get("min_lpa") or 12)
    title = job.title or ""
    bucket = salary_bucket(job, hard_floor=hard_floor, min_lpa_want=min_want)

    if _JUNK.search(title):
        return GateResult(False, "junk_title", salary_bucket=bucket)
    if _INTERN.search(title):
        return GateResult(False, "intern", salary_bucket=bucket)
    if _SENIOR.search(title):
        return GateResult(False, "seniority", salary_bucket=bucket)
    if _ARCHITECT.search(title) and not _JUNIOR_ARCH.search(title):
        return GateResult(False, "seniority", salary_bucket=bucket)
    if _HIGH_YOE.search(title):
        return GateResult(False, "yoe_too_high", salary_bucket=bucket)
    if _MOBILE.search(title) and not _PYTHON_AI.search(title):
        return GateResult(False, "mobile_only", salary_bucket=bucket)
    if _JAVA_NET.search(title) and not _PYTHON_AI.search(title):
        return GateResult(False, "wrong_stack", salary_bucket=bucket)
    if us_only(job):
        return GateResult(False, "us_only", salary_bucket=bucket)
    if bucket == "reject_low":
        return GateResult(False, "salary_below_hard_floor", salary_bucket=bucket)

    family = family_for(title)
    if family:
        if not geo_ok(job):
            return GateResult(False, "geo", family, bucket)
        return GateResult(True, "family", family, bucket)

    if _SDE.search(title):
        if _FRONTEND_ONLY.search(title) or _MOBILE.search(title) or (
            _JAVA_NET.search(title) and not _PYTHON_AI.search(title)
        ):
            return GateResult(False, "sde_wrong_stack", salary_bucket=bucket)
        if not geo_ok(job):
            return GateResult(False, "geo", "software_engineer", bucket)
        return GateResult(True, "sde_india_or_remote", "software_engineer", bucket)

    return GateResult(False, "no_role_match", salary_bucket=bucket)


def apply_gate(job: Job, profile: dict | None = None) -> GateResult:
    result = gate(job, profile)
    job.family = result.family
    job.salary_bucket = result.salary_bucket
    if job.is_remote is None and remote_hint(job_text(job)):
        job.is_remote = True
    return result
