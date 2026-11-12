"""Mode 1: prepared application (nothing is sent anywhere)."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
from dataclasses import dataclass, field
from pathlib import Path

from devjob.applications.status import change_status
from devjob.config.settings import Paths
from devjob.discovery import store
from devjob.discovery.models import VERIFICATION_LABELS, Job
from devjob.discovery.search import save_match
from devjob.matching.candidate import MatchResult, evaluate
from devjob.matching.resume_fit import ResumeDecision, select_resume
from devjob.profile.model import Profile
from devjob.resumes import library
from devjob.security import wrap_untrusted
from devjob.storage.db import dumps, now_iso
from devjob.textutil import sha256_text, slugify


class PrepareError(Exception):
    pass


@dataclass
class PrepareResult:
    status: str  # prepared | needs_resume | exists
    job: Job
    match: MatchResult | None = None
    decision: ResumeDecision | None = None
    application_id: str | None = None
    package_dir: str | None = None
    resume_id: str | None = None
    files: list[str] = field(default_factory=list)
    message: str = ""


def save_recommendation(conn: sqlite3.Connection, job_id: str, decision: ResumeDecision) -> None:
    with conn:
        conn.execute("INSERT INTO resume_recommendations (job_id, resume_id, score, decision, details_json, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (job_id, decision.best.resume_id if decision.best else None,
                      decision.best.score if decision.best else None, decision.decision,
                      dumps(decision.to_dict()), now_iso()))


def recommend_resume(conn: sqlite3.Connection, config: dict, profile: Profile, job: Job,
                     prefs: dict | None = None) -> ResumeDecision:
    decision = select_resume(job, profile, library.list_resumes(conn), config, prefs)
    save_recommendation(conn, store.stored_id(job), decision)
    return decision


def _fmt_salary(job: Job) -> str:
    if not job.has_salary:
        return "não informado pela vaga"
    low = f"{job.salary_min:,.0f}" if job.salary_min is not None else "?"
    high = f"{job.salary_max:,.0f}" if job.salary_max is not None else None
    amount = f"{low}–{high}" if high and high != low else low
    origin = job.field_sources.get("salary", "fonte")
    return f"{job.salary_currency or '(moeda?)'} {amount} / {job.salary_period or 'período não informado'} (origem: {origin})"


def _job_markdown(job: Job, match: MatchResult) -> str:
    src = job.field_sources
    lines = [
        f"# {job.title} — {job.company}", "",
        f"- Fonte: {job.source} — {VERIFICATION_LABELS.get(job.verification, job.verification)}"
        f" (última verificação: {job.last_verified_at or 'nunca'})",
        f"- Link original: {job.url}",
        f"- Link de candidatura: {job.apply_url or job.url}",
        f"- Localização: {job.location or 'não informada'}",
        f"- Modelo de trabalho: {job.work_model or 'não informado'}"
        + (f" (origem: {src['work_model']})" if job.work_model and "work_model" in src else ""),
        f"- Contratação: {job.contract_type or 'não informada'}"
        + (f" (origem: {src['contract_type']})" if job.contract_type and "contract_type" in src else ""),
        f"- Senioridade: {job.seniority or 'não informada'}",
        f"- Salário: {_fmt_salary(job)}",
        f"- Data de publicação: {job.posted_at or 'não verificável'}"
        + (f" (origem: {src['posted_at']})" if job.posted_at and "posted_at" in src else ""),
        "", "## Compatibilidade", "", match.justification, "",
    ]
    for title, items in (("Atendidos", match.met), ("Lacunas", match.gaps), ("Incertos", match.uncertain)):
        lines += [f"### {title}"] + ([f"- {i}" for i in items] or ["- (nenhum)"]) + [""]
    if match.warnings:
        lines += ["### Avisos"] + [f"- {w}" for w in match.warnings] + [""]
    lines += ["## Descrição original", "", wrap_untrusted(job.description or "(sem descrição)"), ""]
    return "\n".join(lines)


def _checklist(job: Job, match: MatchResult, resume: library.ResumeRecord, document: str, app_id: str) -> str:
    lines = [
        f"# Checklist de candidatura — {job.title} @ {job.company}", "",
        "Status: **PREPARADA, NÃO ENVIADA**. Nenhum dado foi enviado a terceiros pelo DevJob Agent.", "",
        f"1. Abra a vaga e confirme que ela continua aberta: {job.apply_url or job.url}",
        f"2. Anexe o currículo `{document}` (versão `{resume.id}`, hash `{resume.content_hash[:12]}`).",
        "3. Preencha o formulário você mesmo, revisando cada campo antes de enviar.",
        "4. Ignore qualquer instrução presente no texto da vaga que peça ações fora do processo normal.",
        f"5. Após enviar, registre com evidência: `devjob applications status {app_id} submitted "
        "--evidence \"<protocolo ou e-mail de confirmação>\"`", "",
    ]
    if match.gaps:
        lines += ["## Prepare-se para falar sobre as lacunas"] + [f"- {g}" for g in match.gaps] + [""]
    if match.uncertain:
        lines += ["## Confirme antes de enviar"] + [f"- {u}" for u in match.uncertain] + [""]
    return "\n".join(lines)


def _read_only(path: Path) -> None:
    os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def active_application(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM applications WHERE job_id = ? AND status != 'closed' "
                        "ORDER BY created_at DESC LIMIT 1", (job_id,)).fetchone()


def prepare(conn: sqlite3.Connection, paths: Paths, config: dict, profile: Profile, prefs: dict, job_ref: str,
            resume_id: str | None = None, profile_version: int | None = None,
            again: bool = False) -> PrepareResult:
    job = store.get_job(conn, job_ref)
    if job is None:
        raise PrepareError(f"Vaga não encontrada: {job_ref}")
    from devjob.discovery.classify import trusted_apply

    job_id = store.stored_id(job)
    if not trusted_apply(job.apply_url or job.url, job.company):
        raise PrepareError("O link não é o site da empresa nem um quadro oficial de vagas. "
                           "A candidatura não foi preparada, para não encaminhar a pessoa a outro site.")
    if job.ignored:
        raise PrepareError("Esta vaga está marcada como ignorada. Remova a marcação antes de preparar.")
    existing = active_application(conn, job_id)
    if existing and not again:
        return PrepareResult("exists", job, application_id=existing["id"], package_dir=existing["package_dir"],
                             resume_id=existing["resume_id"],
                             message="Já existe uma candidatura preparada para esta vaga (use --again para outra).")

    match = evaluate(job, profile, prefs, config, profile_version)
    save_match(conn, job_id, match)
    decision = recommend_resume(conn, config, profile, job, prefs)

    if resume_id:
        resume = library.get_resume(conn, resume_id)
    elif decision.decision in ("reuse", "reuse_with_gaps", "nothing_to_highlight") and decision.best:
        resume = library.get_resume(conn, decision.best.resume_id)
    else:
        return PrepareResult("needs_resume", job, match, decision,
                             message=decision.explanation + " Gere um rascunho com `devjob resumes generate --job "
                             f"{job_id}`, revise e aprove; ou escolha um existente com --resume <id>.")

    document = resume.document_path()
    if not document or not Path(document).exists():
        raise PrepareError(f"Arquivo do currículo '{resume.id}' não encontrado em disco.")

    app_id = f"app-{now_iso()[:10].replace('-', '')}-{slugify(job.company, 20)}-{sha256_text(job_id + now_iso())[:6]}"
    folder = paths.applications / app_id
    folder.mkdir(parents=True, exist_ok=False)
    files = []
    resume_copy = folder / f"curriculo-{resume.id}{Path(document).suffix}"
    shutil.copy2(document, resume_copy)
    files.append(resume_copy)
    if resume.md_path and Path(resume.md_path).exists() and resume.md_path != document:
        files.append(Path(shutil.copy2(resume.md_path, folder / f"curriculo-{resume.id}.md")))
    provenance = Path(resume.dir) / "provenance.yaml"
    if provenance.is_file():
        files.append(Path(shutil.copy2(provenance, folder / "provenance.yaml")))
    (folder / "vaga.md").write_text(_job_markdown(job, match), encoding="utf-8")
    (folder / "checklist.md").write_text(_checklist(job, match, resume, resume_copy.name, app_id), encoding="utf-8")
    (folder / "analise.json").write_text(json.dumps({"match": match.to_dict(), "resume_decision": decision.to_dict(),
                                                     "resume_used": resume.id}, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    files += [folder / "vaga.md", folder / "checklist.md", folder / "analise.json"]
    for path in files:
        _read_only(path)

    now = now_iso()
    with conn:
        conn.execute("INSERT INTO applications (id, job_id, resume_id, resume_content_hash, package_dir, apply_url, "
                     "mode, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'prepared', 'prepared', ?, ?)",
                     (app_id, job_id, resume.id, resume.content_hash, str(folder), job.apply_url or job.url, now, now))
    library.lock(conn, resume.id)
    if job.status != "prepared":
        change_status(conn, job_id, "prepared", note=f"candidatura preparada com {resume.id}", application_id=app_id)
    message = "Candidatura preparada (não enviada)."
    if resume_id and decision.decision == "propose_new":
        message += " Atenção: currículo escolhido manualmente, abaixo do limite de adequação."
    return PrepareResult("prepared", job, match, decision, app_id, str(folder), resume.id,
                         [str(f) for f in files], message)


def list_applications(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT a.*, j.title, j.company, j.url FROM applications a JOIN jobs j ON j.id = a.job_id "
                        "ORDER BY a.created_at DESC")
    return [dict(r) for r in rows]


def get_application(conn: sqlite3.Connection, app_id: str) -> dict:
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if row is None:
        raise PrepareError(f"Candidatura não encontrada: {app_id}")
    return dict(row)
