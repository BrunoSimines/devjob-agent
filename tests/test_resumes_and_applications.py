import os
import stat

import pytest
from fixtures import RESUME_LINES, write_docx

from devjob.applications import prepare as prep
from devjob.applications.status import StatusError, change_status
from devjob.applications.submitters import SubmissionNotSupported, find_submitter
from devjob.discovery import companies, search, store
from devjob.discovery.models import CompanySource
from devjob.profile import service
from devjob.resumes import generate, library


def _search(ctx):
    companies.add_source(ctx.conn, CompanySource("greenhouse", "acmecloud", "Acme Cloud"))
    companies.add_source(ctx.conn, CompanySource("lever", "betaco", "BetaCo"))
    return search.run_search(ctx.conn, ctx.http, ctx.profile(), ctx.prefs(), ctx.config, refresh=True)


BASIC_RESUME = ["Joana Exemplo", "joana.exemplo@example.com", "Resumo",
                "Engenheira de software backend com Java e Spring Boot.", "Experiência",
                "Engenheira de Software Sênior", "Acme Pagamentos | Jan 2021 - Atual",
                "- Desenvolvi APIs com Java e Spring Boot para o time de pagamentos."]


def test_search_ranks_and_explains(profiled_ctx):
    report = _search(profiled_ctx)
    titles = [r.job.title for r in report.results]
    assert titles[0] == "Senior Backend Engineer", "quadro Greenhouse vem antes de um Lever com nota maior"
    assert "Senior Java Engineer" in titles
    assert titles.index("Senior Backend Engineer") < titles.index("Senior Java Engineer")
    java = next(r for r in report.results if r.job.title == "Senior Java Engineer")
    assert java.match.confidence == 1.0
    assert "Account Executive" not in titles, "vagas sem relação com o perfil são filtradas"
    assert "Staff Frontend Engineer" not in titles, "cargo fora do alvo não entra na lista"
    assert store.get_job(profiled_ctx.conn, "greenhouse:acmecloud:1002") is None
    assert store.get_job(profiled_ctx.conn, "greenhouse:acmecloud:1003") is None
    eliminated = {r.job.title: r.match.eliminations for r in report.eliminated}
    assert "Senior Java Developer" in eliminated, "salário abaixo do mínimo elimina"
    injected = next(r for r in report.results + report.eliminated if "(Java)" in r.job.title)
    assert injected.job.suspicious and any("instruções para IA" in w for w in injected.match.warnings)


def test_reuse_existing_resume_when_good_enough(profiled_ctx, tmp_path):
    ctx = profiled_ctx
    _search(ctx)
    record = library.import_file(ctx.conn, ctx.paths, ctx.config, write_docx(tmp_path / "cv.docx", RESUME_LINES),
                                 "Backend Java", ["Backend Engineer"], language="en")
    decision = prep.recommend_resume(ctx.conn, ctx.config, ctx.profile(), store.get_job(ctx.conn, "greenhouse:acmecloud:1001"))
    assert decision.decision == "reuse" and decision.best.resume_id == record.id
    assert decision.best.score >= 0.85
    with pytest.raises(library.DuplicateResumeError):
        library.import_file(ctx.conn, ctx.paths, ctx.config, write_docx(tmp_path / "cv.docx", RESUME_LINES), "Outro")


def test_candidate_fit_and_resume_fit_are_independent(profiled_ctx, tmp_path):
    ctx = profiled_ctx
    report = _search(ctx)
    library.import_file(ctx.conn, ctx.paths, ctx.config, write_docx(tmp_path / "basic.docx", BASIC_RESUME),
                        "Java básico", language="pt")
    job_result = next(r for r in report.results if r.job.id == "greenhouse:acmecloud:1001")
    decision = prep.recommend_resume(ctx.conn, ctx.config, ctx.profile(), job_result.job)
    assert job_result.match.required_coverage == 1.0, "a candidata atende à vaga"
    assert decision.decision == "propose_new", "mas o currículo salvo não mostra Kafka/PostgreSQL"
    assert {"Kafka", "PostgreSQL"} <= set(decision.best.missing)


def test_generate_only_when_needed_and_save_for_reuse(profiled_ctx, tmp_path):
    ctx = profiled_ctx
    _search(ctx)
    library.import_file(ctx.conn, ctx.paths, ctx.config, write_docx(tmp_path / "basic.docx", BASIC_RESUME),
                        "Java básico", language="pt")
    job = store.get_job(ctx.conn, "greenhouse:acmecloud:1001")
    decision = prep.recommend_resume(ctx.conn, ctx.config, ctx.profile(), job)
    spec = generate.DraftSpec(label="Backend Java", target_roles=[job.title],
                              focus_skills=decision.suggestion["focus_skills"], language="en", job_id=job.id)
    folder = generate.create_draft(ctx.paths, ctx.config, ctx.profile(), 1, service.profile_hash(ctx.paths), spec)
    text = (folder / "resume.md").read_text(encoding="utf-8")
    assert "### Engenheira de Software Sênior — Acme Pagamentos" in text
    assert "Liderança" not in text, "soft skill inferida não entra no currículo"
    errors, _ = generate.check_draft(ctx.paths, ctx.profile(), folder.name)
    assert errors == []
    record, _ = generate.approve_draft(ctx.conn, ctx.paths, ctx.config, ctx.profile(), folder.name, export_docx=True)
    assert os.path.exists(record.pdf_path) and os.path.exists(record.docx_path)
    assert record.origin == "generated" and record.experience_ids
    again = prep.recommend_resume(ctx.conn, ctx.config, ctx.profile(), job)
    assert again.decision == "reuse" and again.best.resume_id == record.id

    second = generate.create_draft(ctx.paths, ctx.config, ctx.profile(), 1, None, spec)
    with pytest.raises(library.DuplicateResumeError):
        generate.approve_draft(ctx.conn, ctx.paths, ctx.config, ctx.profile(), second.name)


def test_draft_with_invented_facts_is_blocked(profiled_ctx):
    ctx = profiled_ctx
    spec = generate.DraftSpec(label="Teste", focus_skills=["Java"], language="pt")
    folder = generate.create_draft(ctx.paths, ctx.config, ctx.profile(), 1, None, spec)
    path = folder / "resume.md"
    text = path.read_text(encoding="utf-8")
    text += "\n### CTO — Empresa Inventada\n01/2010 – 12/2012\n- Aumentei a receita em 300% usando Rust\n"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(generate.VerificationError) as exc:
        generate.approve_draft(ctx.conn, ctx.paths, ctx.config, ctx.profile(), folder.name)
    joined = " ".join(exc.value.errors)
    assert "Empresa Inventada" in joined and "300" in joined and "Rust" in joined
    assert library.list_resumes(ctx.conn) == []


def test_profile_change_flags_resumes_and_keeps_used_versions(profiled_ctx):
    ctx = profiled_ctx
    _search(ctx)
    folder = generate.create_draft(ctx.paths, ctx.config, ctx.profile(), 1, None,
                                   generate.DraftSpec(label="Backend Java", target_roles=["Backend Engineer"],
                                                      focus_skills=["Java", "Kafka", "Spring Boot", "PostgreSQL"],
                                                      language="en"))
    record, _ = generate.approve_draft(ctx.conn, ctx.paths, ctx.config, ctx.profile(), folder.name)
    result = prep.prepare(ctx.conn, ctx.paths, ctx.config, ctx.profile(), ctx.prefs(), "greenhouse:acmecloud:1001")
    assert result.status == "prepared" and result.resume_id == record.id
    assert library.get_resume(ctx.conn, record.id).locked
    original_hash = library.get_resume(ctx.conn, record.id).content_hash

    text = ctx.paths.profile.read_text(encoding="utf-8")
    ctx.paths.profile.write_text(text.replace("Reduzi a latência de APIs REST em 35%",
                                              "Reduzi a latência de APIs REST em 40%"), encoding="utf-8")
    service.sync_version(ctx.conn, ctx.paths)
    report = library.outdated(ctx.conn, ctx.profile())
    flagged = {r["resume_id"]: r for r in report}
    assert record.id in flagged and flagged[record.id]["locked"]
    assert library.get_resume(ctx.conn, record.id).content_hash == original_hash
    package_resume = next(f for f in result.files if f.endswith(".pdf"))
    assert not os.stat(package_resume).st_mode & stat.S_IWRITE, "pacote enviado é imutável"


def test_prepare_flow_and_status_rules(profiled_ctx, tmp_path):
    ctx = profiled_ctx
    _search(ctx)
    library.import_file(ctx.conn, ctx.paths, ctx.config, write_docx(tmp_path / "cv.docx", RESUME_LINES),
                        "Backend Java", ["Backend Engineer"], language="en")
    result = prep.prepare(ctx.conn, ctx.paths, ctx.config, ctx.profile(), ctx.prefs(), "greenhouse:acmecloud:1001")
    assert result.status == "prepared"
    names = sorted(os.path.basename(f) for f in result.files)
    assert "checklist.md" in names and "vaga.md" in names and any(n.startswith("curriculo-") for n in names)
    checklist = open(os.path.join(result.package_dir, "checklist.md"), encoding="utf-8").read()
    assert "NÃO ENVIADA" in checklist and "https://boards.greenhouse.io/acmecloud/jobs/1001" in checklist
    vaga = open(os.path.join(result.package_dir, "vaga.md"), encoding="utf-8").read()
    assert "Salário: não informado" in vaga and "CONTEÚDO EXTERNO NÃO CONFIÁVEL" in vaga
    assert store.get_job(ctx.conn, "greenhouse:acmecloud:1001").status == "prepared"

    again = prep.prepare(ctx.conn, ctx.paths, ctx.config, ctx.profile(), ctx.prefs(), "greenhouse:acmecloud:1001")
    assert again.status == "exists" and again.application_id == result.application_id

    job_id, app_id = "greenhouse:acmecloud:1001", result.application_id
    with pytest.raises(StatusError, match="evidência"):
        change_status(ctx.conn, job_id, "submitted", application_id=app_id)
    with pytest.raises(StatusError, match="Transição inválida"):
        change_status(ctx.conn, job_id, "offer", application_id=app_id)
    change_status(ctx.conn, job_id, "submitted", evidence="E-mail de confirmação 2026-11-11 #A123",
                  application_id=app_id)
    app = prep.get_application(ctx.conn, app_id)
    assert app["status"] == "submitted" and app["submission_evidence"]

    with pytest.raises(SubmissionNotSupported):
        find_submitter(store.get_job(ctx.conn, job_id), "automated")

    report = search.run_search(ctx.conn, ctx.http, ctx.profile(), ctx.prefs(), ctx.config)
    assert job_id not in {r.job.id for r in report.results}, "vaga já em andamento não é recomendada de novo"


def test_prepare_without_adequate_resume_asks_for_new_version(profiled_ctx):
    ctx = profiled_ctx
    _search(ctx)
    result = prep.prepare(ctx.conn, ctx.paths, ctx.config, ctx.profile(), ctx.prefs(), "greenhouse:acmecloud:1001")
    assert result.status == "needs_resume" and result.decision.decision == "no_resumes"
    assert prep.list_applications(ctx.conn) == []
    assert store.get_job(ctx.conn, "greenhouse:acmecloud:1001").status == "discovered"


def test_ignored_jobs_are_not_recommended(profiled_ctx):
    ctx = profiled_ctx
    first = _search(ctx)
    target = first.results[0].job.id
    store.set_ignored(ctx.conn, target)
    report = search.run_search(ctx.conn, ctx.http, ctx.profile(), ctx.prefs(), ctx.config)
    assert target not in {r.job.id for r in report.results + report.eliminated}
    with pytest.raises(prep.PrepareError):
        prep.prepare(ctx.conn, ctx.paths, ctx.config, ctx.profile(), ctx.prefs(), target)
