"""Company sources: which public boards to query."""

from __future__ import annotations

import sqlite3

from devjob.discovery.models import CompanySource
from devjob.storage.db import now_iso


def _from_row(row: sqlite3.Row) -> CompanySource:
    return CompanySource(provider=row["provider"], slug=row["slug"], name=row["name"], region=row["region"],
                         careers_url=row["careers_url"], id=row["id"], last_fetched_at=row["last_fetched_at"],
                         last_status=row["last_status"])


def add_source(conn: sqlite3.Connection, source: CompanySource) -> tuple[CompanySource, bool]:
    """Insert (or reactivate) a source. Returns (source, created)."""
    row = conn.execute("SELECT * FROM company_sources WHERE provider = ? AND slug = ? AND region = ?",
                       (source.provider, source.slug, source.region or "")).fetchone()
    with conn:
        if row:
            conn.execute("UPDATE company_sources SET active = 1, name = COALESCE(?, name), "
                         "careers_url = COALESCE(?, careers_url) WHERE id = ?",
                         (source.name, source.careers_url, row["id"]))
            created = False
        else:
            conn.execute("INSERT INTO company_sources (provider, slug, name, region, careers_url, added_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (source.provider, source.slug, source.name, source.region or "", source.careers_url,
                          now_iso()))
            created = True
    row = conn.execute("SELECT * FROM company_sources WHERE provider = ? AND slug = ? AND region = ?",
                       (source.provider, source.slug, source.region or "")).fetchone()
    return _from_row(row), created


def list_sources(conn: sqlite3.Connection, active_only: bool = True) -> list[CompanySource]:
    sql = "SELECT * FROM company_sources" + (" WHERE active = 1" if active_only else "") + " ORDER BY provider, slug"
    return [_from_row(r) for r in conn.execute(sql)]


def remove_source(conn: sqlite3.Connection, provider: str, slug: str) -> bool:
    with conn:
        cur = conn.execute("UPDATE company_sources SET active = 0 WHERE provider = ? AND slug = ?", (provider, slug))
    return cur.rowcount > 0


def record_fetch(conn: sqlite3.Connection, source: CompanySource, status: str, error: str | None = None,
                 name: str | None = None) -> None:
    with conn:
        conn.execute("UPDATE company_sources SET last_fetched_at = ?, last_status = ?, last_error = ?, "
                     "name = COALESCE(name, ?) WHERE id = ?", (now_iso(), status, error, name, source.id))
