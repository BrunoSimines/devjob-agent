"""Application/job status transitions and history."""

from __future__ import annotations

import sqlite3

from devjob.storage.db import now_iso

STATUSES = ("discovered", "shortlisted", "prepared", "submitted", "interviewing", "rejected", "offer", "closed")

TRANSITIONS: dict[str, set[str]] = {
    "discovered": {"shortlisted", "prepared", "closed"},
    "shortlisted": {"discovered", "prepared", "closed"},
    "prepared": {"shortlisted", "submitted", "closed"},
    "submitted": {"interviewing", "rejected", "offer", "closed"},
    "interviewing": {"interviewing", "offer", "rejected", "closed"},
    "offer": {"closed"},
    "rejected": {"closed"},
    "closed": set(),
}


class StatusError(Exception):
    pass


def change_status(conn: sqlite3.Connection, job_id: str, new_status: str, *, note: str | None = None,
                  evidence: str | None = None, application_id: str | None = None) -> str:
    """Move a job (and its application) to ``new_status``. Returns the previous status."""
    if new_status not in STATUSES:
        raise StatusError(f"Status inválido: {new_status}. Use: {', '.join(STATUSES)}")
    row = conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise StatusError(f"Vaga não encontrada: {job_id}")
    current = row["status"]
    if new_status != current and new_status not in TRANSITIONS[current]:
        raise StatusError(f"Transição inválida: {current} -> {new_status}")
    if new_status == "submitted":
        if not evidence or len(evidence.strip()) < 8:
            raise StatusError("'submitted' exige evidência verificável da candidatura enviada (ex.: número de "
                              "protocolo, assunto/data do e-mail de confirmação ou caminho de um comprovante).")
        if application_id is None:
            raise StatusError("'submitted' exige uma candidatura preparada (devjob prepare).")
    now = now_iso()
    with conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
        if application_id:
            conn.execute("UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
                         (new_status, now, application_id))
            if new_status == "submitted":
                conn.execute("UPDATE applications SET submitted_at = ?, submission_evidence = ? WHERE id = ?",
                             (now, evidence.strip(), application_id))
        conn.execute("INSERT INTO status_events (job_id, application_id, from_status, to_status, at, note, evidence) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)", (job_id, application_id, current, new_status, now, note, evidence))
    return current


def history(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM status_events WHERE job_id = ? ORDER BY id", (job_id,))]
