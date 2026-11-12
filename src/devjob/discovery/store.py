"""Job persistence with deduplication."""

from __future__ import annotations

import sqlite3

from devjob.discovery.classify import classify_url
from devjob.discovery.models import VERIFICATION_RANK, Job
from devjob.discovery.normalize import location_tokens
from devjob.storage.db import dumps, loads, now_iso

_DATA_FIELDS = ("source", "company_slug", "external_id", "company", "title", "description", "location",
                "work_model", "contract_type", "seniority", "salary_min", "salary_max", "salary_currency",
                "salary_period", "posted_at", "url", "canonical_url", "apply_url", "language", "fingerprint",
                "content_hash", "verification", "last_verified_at")


def _row_to_job(row: sqlite3.Row) -> Job:
    data = dict(row)
    job = Job(**{k: data[k] for k in ("source", "external_id", "title", "company", "url")})
    for key in _DATA_FIELDS:
        setattr(job, key, data[key])
    job.field_sources = loads(data["field_sources_json"], {})
    job.requirements = loads(data["requirements_json"], {})
    job.suspicious = loads(data["suspicious_json"], [])
    job.status, job.ignored, job.first_seen_at = data["status"], bool(data["ignored"]), data["first_seen_at"]
    job._stored_id = data["id"]  # the primary id may differ from the computed one after a merge
    return job


def stored_id(job: Job) -> str:
    return getattr(job, "_stored_id", None) or job.id


def get_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        rows = conn.execute("SELECT * FROM jobs WHERE id LIKE ?", (f"%{job_id}%",)).fetchall()
        row = rows[0] if len(rows) == 1 else None
    if row is None:
        alias = conn.execute("SELECT job_id FROM job_aliases WHERE canonical_url = ?", (job_id,)).fetchone()
        if alias:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (alias["job_id"],)).fetchone()
    return _row_to_job(row) if row else None


def _locations_compatible(a: str | None, b: str | None) -> bool:
    ta, tb = location_tokens(a), location_tokens(b)
    return not ta or not tb or bool(ta & tb)


def find_existing(conn: sqlite3.Connection, job: Job) -> tuple[sqlite3.Row | None, str]:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job.id,)).fetchone()
    if row:
        return row, "same_id"
    for url in [job.canonical_url, *job.aliases]:
        if not url:
            continue
        row = conn.execute("SELECT * FROM jobs WHERE canonical_url = ?", (url,)).fetchone()
        if row is None:
            alias = conn.execute("SELECT job_id FROM job_aliases WHERE canonical_url = ?", (url,)).fetchone()
            if alias:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (alias["job_id"],)).fetchone()
        if row:
            return row, "same_url"
    for row in conn.execute("SELECT * FROM jobs WHERE fingerprint = ? AND source != ?", (job.fingerprint, job.source)):
        if _locations_compatible(row["location"], job.location):
            return row, "same_company_title"
    return None, ""


def _add_aliases(conn: sqlite3.Connection, job_id: str, job: Job, now: str) -> None:
    for url in {job.canonical_url, *job.aliases} - {""}:
        conn.execute("INSERT OR IGNORE INTO job_aliases (canonical_url, job_id, source, url, seen_at) "
                     "VALUES (?, ?, ?, ?, ?)", (url, job_id, job.source, job.url, now))


def _values(job: Job) -> dict:
    data = {key: getattr(job, key) for key in _DATA_FIELDS}
    data["field_sources_json"] = dumps(job.field_sources)
    data["requirements_json"] = dumps(job.requirements)
    data["suspicious_json"] = dumps(job.suspicious)
    return data


def upsert_job(conn: sqlite3.Connection, job: Job, search_id: int | None = None) -> tuple[str, str]:
    """Insert or merge a finalized job. Returns (stored job id, outcome)."""
    now = now_iso()
    existing, reason = find_existing(conn, job)
    with conn:
        if existing is None:
            data = _values(job)
            data.update(id=job.id, first_seen_at=now, last_seen_search_id=search_id)
            conn.execute(f"INSERT INTO jobs ({', '.join(data)}) VALUES ({', '.join('?' for _ in data)})",
                         list(data.values()))
            _add_aliases(conn, job.id, job, now)
            job_id, outcome = job.id, "new"
        else:
            job_id = existing["id"]
            incoming_rank = VERIFICATION_RANK.get(job.verification, 0)
            current_rank = VERIFICATION_RANK.get(existing["verification"], 0)
            official_upgrade = (reason != "same_id" and incoming_rank >= current_rank
                                and classify_url(existing["url"]).aggregator
                                and not classify_url(job.url).aggregator)
            if official_upgrade and existing["canonical_url"]:
                job.aliases = sorted(set(job.aliases) | {existing["canonical_url"]} - {job.canonical_url})
            if reason == "same_id" or incoming_rank >= current_rank:
                changed = existing["content_hash"] != job.content_hash
                data = _values(job)
                if (reason != "same_id" and incoming_rank == current_rank and existing["source"] != job.source
                        and not official_upgrade):
                    data = {"last_verified_at": job.last_verified_at} if job.last_verified_at else {}
                if data:
                    assignments = ", ".join(f"{k} = ?" for k in data)
                    conn.execute(f"UPDATE jobs SET {assignments}, last_seen_search_id = ? WHERE id = ?",
                                 [*data.values(), search_id, job_id])
                outcome = "duplicate" if reason != "same_id" else ("updated" if changed else "unchanged")
            else:
                outcome = "duplicate"
            _add_aliases(conn, job_id, job, now)
        if search_id is not None:
            conn.execute("INSERT OR REPLACE INTO search_results (search_id, job_id, outcome) VALUES (?, ?, ?)",
                         (search_id, job_id, outcome))
    return job_id, outcome


def discard_discovered(conn: sqlite3.Connection, job_ids: list[str]) -> int:
    """Delete postings nobody has acted on. Shortlists and applications stay."""
    removed = 0
    for start in range(0, len(job_ids), 400):
        chunk = job_ids[start:start + 400]
        marks = ",".join("?" for _ in chunk)
        protected = {row["id"] for row in conn.execute(
            f"SELECT id FROM jobs WHERE id IN ({marks}) AND (status != 'discovered' OR ignored = 1)", chunk)}
        protected.update(row["job_id"] for row in conn.execute(
            f"SELECT job_id FROM applications WHERE job_id IN ({marks})", chunk))
        drop = [job_id for job_id in chunk if job_id not in protected]
        if not drop:
            continue
        placeholders = ",".join("?" for _ in drop)
        with conn:
            for table, column in (("status_events", "job_id"), ("resume_recommendations", "job_id"),
                                  ("match_results", "job_id"), ("search_results", "job_id"),
                                  ("job_aliases", "job_id"), ("jobs", "id")):
                conn.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", drop)
        removed += len(drop)
    return removed


def mark_not_listed(conn: sqlite3.Connection, source: str, company_slug: str, seen_ids: set[str]) -> int:
    rows = conn.execute("SELECT id FROM jobs WHERE source = ? AND company_slug = ? AND verification = 'listed'",
                        (source, company_slug)).fetchall()
    gone = [r["id"] for r in rows if r["id"] not in seen_ids]
    with conn:
        conn.executemany("UPDATE jobs SET verification = 'not_listed' WHERE id = ?", [(i,) for i in gone])
    return len(gone)


def list_jobs(conn: sqlite3.Connection, status: str | None = None, include_ignored: bool = False,
              source: str | None = None, company_slug: str | None = None) -> list[Job]:
    sql, params = "SELECT * FROM jobs WHERE 1 = 1", []
    if not include_ignored:
        sql += " AND ignored = 0"
    if status:
        sql += " AND status = ?"
        params.append(status)
    if source:
        sql += " AND source = ?"
        params.append(source)
    if company_slug:
        sql += " AND company_slug = ?"
        params.append(company_slug)
    return [_row_to_job(r) for r in conn.execute(sql + " ORDER BY first_seen_at DESC", params)]


def set_ignored(conn: sqlite3.Connection, job_id: str, ignored: bool = True) -> None:
    with conn:
        conn.execute("UPDATE jobs SET ignored = ? WHERE id = ?", (int(ignored), job_id))


def update_requirements(conn: sqlite3.Connection, job_id: str, requirements: dict, fields: dict) -> None:
    allowed = {"seniority", "work_model", "contract_type", "location"}
    job = get_job(conn, job_id)
    sources = dict(job.field_sources)
    updates = {k: v for k, v in fields.items() if k in allowed and v}
    for key in updates:
        sources[key] = "agent_analysis"
    with conn:
        conn.execute("UPDATE jobs SET requirements_json = ?, field_sources_json = ? WHERE id = ?",
                     (dumps(requirements), dumps(sources), job_id))
        for key, value in updates.items():
            conn.execute(f"UPDATE jobs SET {key} = ? WHERE id = ?", (value, job_id))
