"""Wave 4: one OpenRouter call per new inbox survivor. Never per board."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from job_radar.filters import load_profile
from job_radar.rank import rank_store
from job_radar.store import ROOT, Store, utcnow

BRIEFS_PATH = ROOT / "data" / "briefs.jsonl"
SUMMARY_PATH = ROOT / "data" / "enrich_summary.json"
ENV_PATH = ROOT / ".env"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"
FALLBACK_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
TIMEOUT = 35
SLEEP_S = 0.4
DEFAULT_LIMIT = 0
DEFAULT_WORKERS = 4
TARGET_FAMILIES = ("ai_automation", "voice_ai", "python_backend", "itom_servicenow")

JSON_BLOCK = re.compile(r"\{.*\}", re.S)
KEY_RE = re.compile(r"sk-or-[A-Za-z0-9_-]+")
RESET_RE = re.compile(r'X-RateLimit-Reset":"(\d+)"')

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "skills",
        "implied_yoe",
        "india_eligible",
        "us_only_trap",
        "salary_guess_lpa",
        "salary_note",
        "fit",
        "brief",
        "concerns",
    ],
    "properties": {
        "skills": {"type": "array", "items": {"type": "string"}},
        "implied_yoe": {"type": "string"},
        "india_eligible": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "us_only_trap": {"type": "boolean"},
        "salary_guess_lpa": {"type": ["number", "null"]},
        "salary_note": {"type": "string"},
        "fit": {"type": "string", "enum": ["strong", "possible", "stretch", "poor"]},
        "brief": {"type": "string"},
        "concerns": {"type": "array", "items": {"type": "string"}},
    },
}

Completer = Callable[[str, list[dict[str, str]]], dict[str, Any]]


def scrub(msg: object) -> str:
    return KEY_RE.sub("sk-or-***", str(msg))[:240]


def _env_file_value(path: Path, name: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def load_openrouter_key() -> str:
    raw = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not raw:
        raw = _env_file_value(ENV_PATH, "OPENROUTER_API_KEY")
    if not raw:
        raise SystemExit("OPENROUTER_API_KEY missing — add it to job-radar/.env")
    return raw


def parse_json_content(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    match = JSON_BLOCK.search(text)
    if not match:
        raise ValueError("no JSON object in model output")
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("model JSON is not an object")
    return payload


def system_prompt(profile: dict) -> str:
    points = profile.get("proof_points") or []
    proof = "\n".join(f"- {item}" for item in points)
    name = profile.get("name") or "the candidate"
    yoe = profile.get("yoe") or "several"
    location = profile.get("location") or "the target location"
    return (
        f"You write job briefs for {name}, a {yoe}-YOE Python / AI-automation "
        f"engineer in {location}. Service companies are fine. Do not invent employers "
        "or salary numbers that are not implied by the listing text.\n"
        "Ground the brief in the candidate's work, not generic full-stack bullets:\n"
        f"{proof}\n"
        "Return only JSON. india_eligible=yes if the target location, India, India-remote, "
        "or hybrid is plausible. us_only_trap=true if the candidate likely cannot apply "
        "(US work auth, US-only onsite, visa block). "
        "fit=strong only if the stack and YOE are a real callback chance."
    )


def user_prompt(job: dict[str, Any]) -> str:
    locs = job.get("locations") or []
    if isinstance(locs, list):
        loc_text = "; ".join(str(item) for item in locs)
    else:
        loc_text = str(locs)
    return (
        f"Company: {job.get('company_name') or job.get('company_id')}\n"
        f"Title: {job.get('title')}\n"
        f"Family: {job.get('family')}\n"
        f"Locations: {loc_text}\n"
        f"Remote flag: {job.get('is_remote')}\n"
        f"Salary text: {job.get('salary_text') or 'unknown'}\n"
        f"Heuristic score: {job.get('score')}\n"
        f"Heuristic why: {job.get('why')}\n"
        f"Heuristic concerns: {job.get('concerns')}\n"
        f"Apply URL: {job.get('apply_url')}\n"
        "Extract skills, implied YOE, India eligibility, US-only trap, salary guess in LPA, "
        "fit, concerns, and a 4-6 sentence brief that maps THIS role to the candidate's "
        "proof points. Skip points that do not apply."
    )


def messages_for(job: dict[str, Any], profile: dict) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt(profile)},
        {"role": "user", "content": user_prompt(job)},
    ]


def openrouter_complete(model: str, messages: list[dict[str, str]], key: str) -> dict[str, Any]:
    body = {
        "model": model,
        "temperature": 0.2,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/job-radar",
            "X-Title": "job-radar",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        err = RuntimeError(scrub(f"http_{exc.code}:{detail}"))
        err.status = exc.code  # type: ignore[attr-defined]
        raise err from exc
    except Exception as exc:
        raise RuntimeError(scrub(f"{type(exc).__name__}:{exc}")) from exc
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    if not str(content).strip():
        raise RuntimeError(f"empty_content from {payload.get('model') or model}")
    parsed = parse_json_content(str(content))
    parsed["_model"] = payload.get("model") or model
    return parsed


def _sleep_daily_cap(err: str) -> bool:
    if "per-day" not in err and "free-models-per-day" not in err:
        return False
    match = RESET_RE.search(err)
    reset_s = int(match.group(1)) / 1000 if match else time.time() + 3600
    wait = max(30.0, reset_s - time.time() + 45)
    print(f"daily free cap — sleeping {wait / 3600:.1f}h until reset", flush=True)
    time.sleep(wait)
    return True


def _complete_with_fallback(messages: list[dict[str, str]], key: str, model: str) -> dict[str, Any]:
    names = (model, FALLBACK_MODEL) if model != FALLBACK_MODEL else (model,)
    last = "unreachable"
    for name in names:
        for attempt in range(3):
            try:
                return openrouter_complete(name, messages, key)
            except Exception as exc:
                last = scrub(exc)
                status = getattr(exc, "status", None)
                if status == 429 or "http_429" in last:
                    if _sleep_daily_cap(last):
                        continue
                    time.sleep(8 * (attempt + 1))
                    continue
                break
    raise RuntimeError(last)


def normalize_fit(raw: object) -> str:
    text = str(raw or "").strip().lower()
    if text.startswith("strong"):
        return "strong"
    if text.startswith("stretch"):
        return "stretch"
    if text.startswith("poor") or text in {"weak"}:
        return "poor"
    if text.startswith("possible") or text in {"moderate", "medium"}:
        return "possible"
    return "possible"


def normalize_india(raw: object) -> str:
    text = str(raw or "").strip().lower()
    if text in {"yes", "true", "1"}:
        return "yes"
    if text in {"no", "false", "0"}:
        return "no"
    return "unclear"


def apply_payload(job: dict[str, Any], payload: dict[str, Any], model: str) -> dict[str, Any]:
    skills = payload.get("skills") or []
    if not isinstance(skills, list):
        skills = [str(skills)]
    concerns = payload.get("concerns") or []
    if not isinstance(concerns, list):
        concerns = [str(concerns)]
    guess = payload.get("salary_guess_lpa")
    job["skills"] = [str(item) for item in skills if item]
    job["implied_yoe"] = str(payload.get("implied_yoe") or "unknown")[:40]
    job["india_eligible"] = normalize_india(payload.get("india_eligible"))
    job["us_only_trap"] = bool(payload.get("us_only_trap"))
    job["salary_guess"] = None if guess in (None, "") else str(guess)
    job["fit"] = normalize_fit(payload.get("fit"))
    job["brief"] = str(payload.get("brief") or "").strip()
    extra = [str(item) for item in concerns if item]
    existing = job.get("concerns") if isinstance(job.get("concerns"), list) else []
    for item in extra:
        if item not in existing:
            existing.append(item)
    job["concerns"] = existing
    job["enriched_at"] = utcnow()
    job["enrich_model"] = str(payload.get("_model") or model)
    job["enrich_error"] = None
    if payload.get("salary_note") and payload["salary_note"] not in existing:
        job.setdefault("salary_note", str(payload["salary_note"]))
    return job


def pending_jobs(
    store: Store,
    *,
    limit: int,
    force: bool,
    min_score: float = 40,
) -> list[dict[str, Any]]:
    store.ensure_rank_columns()
    sample = store.inbox(limit=1)
    if not sample or sample[0].get("score") is None:
        rank_store(store)
    return store.pending_enrich(
        force=force,
        families=list(TARGET_FAMILIES),
        min_score=min_score,
        limit=limit,
    )


def write_briefs(rows: list[dict[str, Any]], path: Path = BRIEFS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return path


def format_briefs(rows: list[dict[str, Any]], limit: int = 20) -> str:
    lines: list[str] = []
    for index, row in enumerate(rows[:limit], start=1):
        lines.append(
            f"{index:2}. {int(row.get('score') or 0):3}  {row.get('fit') or '?'}  "
            f"{row.get('title')} — {row.get('company_name')}"
        )
        lines.append(
            f"    india={row.get('india_eligible')}  us_trap={row.get('us_only_trap')}  "
            f"yoe={row.get('implied_yoe')}  salary={row.get('salary_guess') or row.get('salary_text') or '?'}"
        )
        if row.get("brief"):
            lines.append(f"    {row['brief']}")
        if row.get("apply_url"):
            lines.append(f"    {row['apply_url']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _enrich_one(
    job: dict[str, Any],
    profile: dict,
    model: str,
    secret: str,
    completer: Completer | None,
) -> dict[str, Any]:
    msgs = messages_for(job, profile)
    if completer:
        payload = completer(model, msgs)
    else:
        payload = _complete_with_fallback(msgs, secret, model)
        time.sleep(SLEEP_S)
    apply_payload(job, payload, model)
    return job


def run(
    *,
    limit: int = DEFAULT_LIMIT,
    force: bool = False,
    model: str = DEFAULT_MODEL,
    db_path: Path | None = None,
    completer: Completer | None = None,
    key: str | None = None,
    workers: int = DEFAULT_WORKERS,
    min_score: float = 40,
) -> dict[str, Any]:
    profile = load_profile()
    store = Store(db_path)
    todo: list[dict[str, Any]] = []
    ok = failed = 0
    try:
        todo = pending_jobs(store, limit=limit, force=force, min_score=min_score)
        secret = key if completer else (key or load_openrouter_key())
        if completer and not secret:
            secret = "test"
        workers = 1 if completer else max(1, workers)
        print(
            f"enrich: {len(todo)} jobs · model={model} · workers={workers} · "
            f"skip_cached={not force} · min_score={min_score}",
            flush=True,
        )

        def work(job: dict[str, Any]) -> dict[str, Any]:
            return _enrich_one(job, profile, model, secret or "test", completer)

        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, job): job for job in todo}
            for fut in as_completed(futures):
                job = futures[fut]
                done += 1
                try:
                    job = fut.result()
                    store.save_enrichment(job)
                    ok += 1
                    print(f"  {done}/{len(todo)}  {job.get('fit')}  {(job.get('title') or '')[:70]}", flush=True)
                except Exception as exc:
                    failed += 1
                    job["enrich_error"] = scrub(exc)
                    job["enriched_at"] = None
                    store.save_enrichment(job)
                    print(f"  {done}/{len(todo)}  FAIL  {scrub(exc)}", flush=True)
                if done % 25 == 0:
                    write_briefs(store.briefed_jobs())
        briefs = store.briefed_jobs()
        write_briefs(briefs)
        summary = {
            "wave": 4,
            "model": model,
            "todo": len(todo),
            "ok": ok,
            "failed": failed,
            "workers": workers,
            "briefs": len(briefs),
            "outputs": {"briefs": str(BRIEFS_PATH.relative_to(ROOT))},
        }
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        return {"summary": summary, "jobs": todo, "briefs": briefs}
    finally:
        store.close()
