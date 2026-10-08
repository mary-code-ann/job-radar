"""SQLite store for poll runs, companies, and matching jobs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_radar.jobs import Job
from job_radar.models import Candidate

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "radar.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS poll_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    counts TEXT
);

CREATE TABLE IF NOT EXISTS companies (
    id TEXT PRIMARY KEY,
    name TEXT,
    ats TEXT,
    board_slug TEXT,
    board_url TEXT,
    status TEXT,
    content_hash TEXT,
    last_ok_at TEXT,
    last_error TEXT,
    last_run_id INTEGER,
    last_http INTEGER,
    job_count INTEGER,
    match_count INTEGER,
    india_hint INTEGER,
    sources TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    ats TEXT NOT NULL,
    board_slug TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    title TEXT,
    locations TEXT,
    apply_url TEXT,
    is_remote INTEGER,
    posted_at TEXT,
    salary_text TEXT,
    salary_bucket TEXT,
    family TEXT,
    first_seen TEXT,
    last_seen TEXT,
    closed_at TEXT,
    score REAL,
    why TEXT,
    concerns TEXT,
    brief TEXT,
    skills TEXT,
    india_eligible TEXT,
    us_only_trap INTEGER,
    implied_yoe TEXT,
    salary_guess TEXT,
    fit TEXT,
    enriched_at TEXT,
    enrich_model TEXT,
    enrich_error TEXT,
    PRIMARY KEY (ats, board_slug, source_job_id)
);

CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS jobs_open ON jobs(closed_at);
CREATE INDEX IF NOT EXISTS companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS companies_run ON companies(last_run_id);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(jobs: list[Job]) -> str:
    ids = sorted(job.source_job_id for job in jobs if job.source_job_id)
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def candidate_from_json(data: dict[str, Any]) -> Candidate:
    fields = set(Candidate.__dataclass_fields__)
    kwargs = {key: data[key] for key in fields if key in data}
    return Candidate(**kwargs)


def load_candidates(path: Path) -> list[Candidate]:
    rows: list[Candidate] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(candidate_from_json(json.loads(line)))
    return rows


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.path), timeout=60, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def ensure_rank_columns(self) -> None:
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(jobs)")}
        extras = (
            ("score", "REAL"),
            ("why", "TEXT"),
            ("concerns", "TEXT"),
            ("brief", "TEXT"),
            ("skills", "TEXT"),
            ("india_eligible", "TEXT"),
            ("us_only_trap", "INTEGER"),
            ("implied_yoe", "TEXT"),
            ("salary_guess", "TEXT"),
            ("fit", "TEXT"),
            ("enriched_at", "TEXT"),
            ("enrich_model", "TEXT"),
            ("enrich_error", "TEXT"),
        )
        for name, decl in extras:
            if name not in cols:
                self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {decl}")
        self.conn.commit()

    def _decode_job_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        loc = item.get("locations")
        if isinstance(loc, str):
            try:
                item["locations"] = json.loads(loc)
            except json.JSONDecodeError:
                item["locations"] = [loc] if loc else []
        for key in ("why", "concerns", "skills"):
            raw = item.get(key)
            if isinstance(raw, str) and raw:
                try:
                    item[key] = json.loads(raw)
                except json.JSONDecodeError:
                    item[key] = [raw]
        return item

    def save_enrichment(self, row: dict[str, Any]) -> None:
        self.ensure_rank_columns()
        with self._lock:
            self.conn.execute(
            """
            UPDATE jobs SET
                brief = ?, skills = ?, india_eligible = ?, us_only_trap = ?,
                implied_yoe = ?, salary_guess = ?, fit = ?, enriched_at = ?,
                enrich_model = ?, enrich_error = ?, concerns = ?
            WHERE ats = ? AND board_slug = ? AND source_job_id = ?
            """,
            (
                row.get("brief"),
                json.dumps(row.get("skills") or [], ensure_ascii=False),
                row.get("india_eligible"),
                None if row.get("us_only_trap") is None else int(bool(row.get("us_only_trap"))),
                row.get("implied_yoe"),
                row.get("salary_guess"),
                row.get("fit"),
                row.get("enriched_at"),
                row.get("enrich_model"),
                row.get("enrich_error"),
                json.dumps(row.get("concerns") or [], ensure_ascii=False),
                row.get("ats"),
                row.get("board_slug"),
                row.get("source_job_id"),
            ),
            )
            self.conn.commit()

    def save_ranks(self, rows: list[dict[str, Any]]) -> None:
        self.ensure_rank_columns()
        self.conn.executemany(
            """
            UPDATE jobs SET score = ?, why = ?, concerns = ?
            WHERE ats = ? AND board_slug = ? AND source_job_id = ?
            """,
            [
                (
                    row.get("score"),
                    json.dumps(row.get("why") or [], ensure_ascii=False),
                    json.dumps(row.get("concerns") or [], ensure_ascii=False),
                    row.get("ats"),
                    row.get("board_slug"),
                    row.get("source_job_id"),
                )
                for row in rows
            ],
        )
        self.conn.commit()

    def inbox(self, limit: int = 20) -> list[dict[str, Any]]:
        self.ensure_rank_columns()
        rows = self.conn.execute(
            """
            SELECT jobs.*, companies.name AS company_name, companies.india_hint AS company_india_hint
            FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            WHERE jobs.closed_at IS NULL
            ORDER BY jobs.score DESC, jobs.last_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._decode_job_row(row) for row in rows]

    def pending_enrich(
        self,
        *,
        force: bool = False,
        families: list[str] | None = None,
        min_score: float | None = 40,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        """Unbriefed open jobs: target families, or score at/above min_score."""
        self.ensure_rank_columns()
        sql = """
            SELECT jobs.*, companies.name AS company_name, companies.india_hint AS india_hint
            FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            WHERE jobs.closed_at IS NULL
        """
        args: list[Any] = []
        if not force:
            sql += " AND (jobs.brief IS NULL OR jobs.brief = '')"
        if families:
            placeholders = ",".join("?" * len(families))
            sql += f" AND (jobs.family IN ({placeholders}) OR jobs.score >= ?)"
            args.extend(families)
            args.append(min_score if min_score is not None else 0)
        elif min_score is not None:
            sql += " AND jobs.score >= ?"
            args.append(min_score)
        sql += " ORDER BY jobs.score DESC, jobs.title"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        return [self._decode_job_row(row) for row in self.conn.execute(sql, args).fetchall()]

    def briefed_jobs(self) -> list[dict[str, Any]]:
        self.ensure_rank_columns()
        rows = self.conn.execute(
            """
            SELECT jobs.*, companies.name AS company_name
            FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            WHERE jobs.closed_at IS NULL AND jobs.brief IS NOT NULL AND jobs.brief != ''
            ORDER BY jobs.score DESC
            """
        ).fetchall()
        return [self._decode_job_row(row) for row in rows]

    def create_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO poll_runs (started_at, status) VALUES (?, ?)",
            (utcnow(), "running"),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def latest_run(self, status: str | None = None) -> dict[str, Any] | None:
        if status:
            row = self.conn.execute(
                "SELECT * FROM poll_runs WHERE status = ? ORDER BY id DESC LIMIT 1",
                (status,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM poll_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def finish_run(self, run_id: int, counts: dict[str, Any]) -> None:
        self.conn.execute(
            "UPDATE poll_runs SET finished_at = ?, status = ?, counts = ? WHERE id = ?",
            (utcnow(), "done", json.dumps(counts), run_id),
        )
        self.conn.commit()

    def done_ids(self, run_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT id FROM companies WHERE last_run_id = ?",
            (run_id,),
        ).fetchall()
        return {row["id"] for row in rows}

    def get_company(self, company_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM companies WHERE id = ?", (company_id,)
        ).fetchone()
        return dict(row) if row else None

    def apply_board(
        self,
        candidate: Candidate,
        *,
        run_id: int,
        all_jobs: list[Job],
        matches: list[Job],
        status: str,
        http_status: int,
        error: str | None,
    ) -> bool:
        """Upsert company + matching jobs. Returns True if listing hash changed."""
        now = utcnow()
        company_id = candidate.candidate_id
        prev = self.get_company(company_id)
        if status == "error":
            self.conn.execute(
                """
                INSERT INTO companies (
                    id, name, ats, board_slug, board_url, status, content_hash,
                    last_ok_at, last_error, last_run_id, last_http, job_count,
                    match_count, india_hint, sources
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    last_error = excluded.last_error,
                    last_run_id = excluded.last_run_id,
                    last_http = excluded.last_http,
                    status = COALESCE(companies.status, excluded.status)
                """,
                (
                    company_id,
                    candidate.name,
                    candidate.ats,
                    candidate.board_slug,
                    candidate.board_url,
                    status,
                    prev.get("content_hash") if prev else None,
                    prev.get("last_ok_at") if prev else None,
                    error,
                    run_id,
                    http_status,
                    prev.get("job_count") if prev else 0,
                    prev.get("match_count") if prev else 0,
                    1 if candidate.india_hint else 0,
                    json.dumps(candidate.sources),
                ),
            )
            return False
        new_hash = content_hash(all_jobs)
        unchanged = bool(prev and prev.get("content_hash") == new_hash and all_jobs)
        self.conn.execute(
            """
            INSERT INTO companies (
                id, name, ats, board_slug, board_url, status, content_hash,
                last_ok_at, last_error, last_run_id, last_http, job_count,
                match_count, india_hint, sources
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                ats = excluded.ats,
                board_slug = excluded.board_slug,
                board_url = excluded.board_url,
                status = excluded.status,
                content_hash = excluded.content_hash,
                last_ok_at = excluded.last_ok_at,
                last_error = excluded.last_error,
                last_run_id = excluded.last_run_id,
                last_http = excluded.last_http,
                job_count = excluded.job_count,
                match_count = excluded.match_count,
                india_hint = excluded.india_hint,
                sources = excluded.sources
            """,
            (
                company_id,
                candidate.name,
                candidate.ats,
                candidate.board_slug,
                candidate.board_url,
                status,
                new_hash,
                now,
                error,
                run_id,
                http_status,
                len(all_jobs),
                len(matches),
                1 if candidate.india_hint else 0,
                json.dumps(candidate.sources),
            ),
        )
        if status == "dead" or (not unchanged and not matches):
            self._close_missing(company_id, set(), now)
        elif unchanged:
            self.conn.execute(
                "UPDATE jobs SET last_seen = ? WHERE company_id = ? AND closed_at IS NULL",
                (now, company_id),
            )
        else:
            for job in matches:
                self._upsert_job(company_id, job, now)
            self._close_missing(company_id, {job.source_job_id for job in matches}, now)
        return not unchanged

    def _upsert_job(self, company_id: str, job: Job, now: str) -> None:
        existing = self.conn.execute(
            """
            SELECT first_seen FROM jobs
            WHERE ats = ? AND board_slug = ? AND source_job_id = ?
            """,
            (job.ats, job.board_slug, job.source_job_id),
        ).fetchone()
        first = existing["first_seen"] if existing else now
        self.conn.execute(
            """
            INSERT INTO jobs (
                ats, board_slug, source_job_id, company_id, title, locations,
                apply_url, is_remote, posted_at, salary_text, salary_bucket,
                family, first_seen, last_seen, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(ats, board_slug, source_job_id) DO UPDATE SET
                title = excluded.title,
                locations = excluded.locations,
                apply_url = excluded.apply_url,
                is_remote = excluded.is_remote,
                posted_at = excluded.posted_at,
                salary_text = excluded.salary_text,
                salary_bucket = excluded.salary_bucket,
                family = excluded.family,
                last_seen = excluded.last_seen,
                closed_at = NULL
            """,
            (
                job.ats,
                job.board_slug,
                job.source_job_id,
                company_id,
                job.title,
                json.dumps(job.locations),
                job.apply_url,
                None if job.is_remote is None else int(job.is_remote),
                job.posted_at,
                job.salary_text,
                job.salary_bucket,
                job.family,
                first,
                now,
            ),
        )

    def _close_missing(self, company_id: str, keep_ids: set[str], now: str) -> None:
        if keep_ids:
            placeholders = ",".join("?" * len(keep_ids))
            self.conn.execute(
                f"""
                UPDATE jobs SET closed_at = ?
                WHERE company_id = ? AND closed_at IS NULL
                  AND source_job_id NOT IN ({placeholders})
                """,
                (now, company_id, *keep_ids),
            )
            return
        self.conn.execute(
            "UPDATE jobs SET closed_at = ? WHERE company_id = ? AND closed_at IS NULL",
            (now, company_id),
        )

    def commit(self) -> None:
        self.conn.commit()

    def open_matches(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT jobs.*, companies.name AS company_name, companies.status AS company_status,
                   companies.india_hint AS india_hint
            FROM jobs
            JOIN companies ON companies.id = jobs.company_id
            WHERE jobs.closed_at IS NULL
            ORDER BY COALESCE(jobs.score, -1) DESC, jobs.family, jobs.title
            """
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            loc = item.get("locations")
            if isinstance(loc, str):
                try:
                    item["locations"] = json.loads(loc)
                except json.JSONDecodeError:
                    item["locations"] = [loc] if loc else []
            out.append(item)
        return out

    def status_map(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT id, status FROM companies").fetchall()
        return {row["id"]: row["status"] for row in rows if row["status"]}
