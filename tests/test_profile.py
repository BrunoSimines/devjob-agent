import json

import pytest
from fixtures import INCOMPLETE_RESUME_LINES, RESUME_LINES, write_docx, write_pdf

from devjob.profile import markdown, service
from devjob.profile.model import Experience, Fact, Profile
from devjob.profile.parser import parse_resume


def test_heuristic_parser_extracts_core_sections():
    profile, notes = parse_resume("\n".join(RESUME_LINES))
    assert profile.name == "Joana Exemplo"
    assert profile.contact["email"].value == "joana.exemplo@example.com"
    assert [(e.title, e.company) for e in profile.experiences] == [
        ("Engenheira de Software Sênior", "Acme Pagamentos"), ("Desenvolvedora Backend", "Beta Sistemas")]
    acme = profile.experiences[0]
    assert acme.start == "2021-01" and acme.end == "present"
    assert profile.experiences[1].start == "2017-03" and profile.experiences[1].end == "2020-12"
    assert {"Java", "Spring Boot", "Kafka", "EKS"} <= set(acme.technologies)
    assert {"Java", "Kafka", "Redis", "OAuth 2.0", "Keycloak"} <= {f.value for f in profile.hard_skills}
    languages = {lang.code: lang.level for lang in profile.languages}
    assert languages == {"pt": "native", "en": "C1"}


def test_soft_skills_inferred_are_not_facts():
    profile, _ = parse_resume("\n".join(RESUME_LINES))
    soft = {f.value: f.source for f in profile.soft_skills}
    assert soft["Comunicação"] == "resume"          # listed explicitly in "Habilidades"
    assert soft["Liderança"] == "inferred"          # "Liderei ..." is evidence, not a declaration
    assert soft["Mentoria"] == "inferred"
    assert "Liderança" not in profile.confirmed_soft_skills()


def test_markdown_roundtrip_preserves_provenance():
    profile, _ = parse_resume("\n".join(RESUME_LINES))
    text = markdown.render(profile)
    parsed, warnings = markdown.parse(text)
    assert warnings == []
    assert markdown.render(parsed) == text
    assert parsed.inferred_soft_skills() == profile.inferred_soft_skills()


def test_hand_written_lines_count_as_user_declared():
    text = ("## Hard skills\n- Rust\n- Go [inferred] — evidência: \"side project\"\n"
            "## Experiência\n### Dev @ Empresa X\n- período: 2019-01 – 2020-06\n- Fiz algo útil\n")
    profile, warnings = markdown.parse(text)
    skills = {f.value: f.source for f in profile.hard_skills}
    assert skills == {"Rust": "user", "Go": "inferred"}
    assert profile.experiences[0].source == "user"
    assert profile.experiences[0].highlights[0].source == "user"
    assert "Go" not in profile.confirmed_hard_skills()


@pytest.mark.parametrize("writer,suffix", [(write_docx, "docx"), (write_pdf, "pdf")])
def test_import_creates_draft_and_requires_acceptance(ctx, tmp_path, writer, suffix):
    file = writer(tmp_path / f"cv.{suffix}", RESUME_LINES)
    result = service.import_resume(ctx.conn, ctx.paths, file)
    assert result.draft_path.exists()
    assert not ctx.paths.profile.exists(), "nada é consolidado sem revisão"
    assert any("Acme Pagamentos" in c for c in result.changes)
    assert result.pending_inferences
    version = service.accept_draft(ctx.conn, ctx.paths)
    assert version == 1 and ctx.paths.profile.exists() and not ctx.paths.profile_draft.exists()
    assert service.load_profile(ctx.paths).name == "Joana Exemplo"


def test_profile_is_reused_and_same_file_not_reprocessed(profiled_ctx, resume_docx):
    result = service.import_resume(profiled_ctx.conn, profiled_ctx.paths, resume_docx)
    assert result.already_accepted
    assert not profiled_ctx.paths.profile_draft.exists()


def test_incremental_update_only_adds_new_facts(profiled_ctx, tmp_path):
    ctx = profiled_ctx
    service.confirm_fact(ctx.conn, ctx.paths, "Liderança")
    updated = RESUME_LINES + ["", "Certificações", "AWS Certified Developer - Associate (2024)"]
    updated[24] = updated[24] + ", Terraform"
    result = service.import_resume(ctx.conn, ctx.paths, write_docx(tmp_path / "v2.docx", updated))
    assert any("Terraform" in c for c in result.changes)
    assert any("AWS Certified Developer" in c for c in result.changes)
    assert not any("Acme Pagamentos" in c for c in result.changes), "experiências existentes não são duplicadas"
    service.accept_draft(ctx.conn, ctx.paths)
    profile = service.load_profile(ctx.paths)
    assert "Terraform" in profile.confirmed_hard_skills()
    assert "Liderança" in profile.confirmed_soft_skills(), "confirmações anteriores são preservadas"


def test_incomplete_resume_is_imported_with_notes(ctx, tmp_path):
    result = service.import_resume(ctx.conn, ctx.paths, write_docx(tmp_path / "x.docx", INCOMPLETE_RESUME_LINES))
    assert any("nenhuma experiência" in n for n in result.notes)
    assert any("e-mail" in n for n in result.notes)
    draft, _ = markdown.parse(result.draft_path.read_text(encoding="utf-8"))
    assert {"Python", "Django", "PostgreSQL"} <= {f.value for f in draft.hard_skills}


def test_confirm_and_reject_inferences(profiled_ctx):
    ctx = profiled_ctx
    service.confirm_fact(ctx.conn, ctx.paths, "Mentoria")
    service.reject_fact(ctx.conn, ctx.paths, "Liderança")
    profile = service.load_profile(ctx.paths)
    assert "Mentoria" in profile.confirmed_soft_skills()
    assert "Liderança" not in {f.value for f in profile.soft_skills}
    with pytest.raises(service.ProfileError):
        service.confirm_fact(ctx.conn, ctx.paths, "Java")  # já é fato, não inferência


def test_manual_edit_creates_new_version(profiled_ctx):
    ctx = profiled_ctx
    before = service.status(ctx.conn, ctx.paths)["version"]
    text = ctx.paths.profile.read_text(encoding="utf-8")
    ctx.paths.profile.write_text(text.replace("## Soft skills", "## Soft skills\n- Autonomia"), encoding="utf-8")
    after = service.status(ctx.conn, ctx.paths)
    assert after["version"] == before + 1 and after["changed_since_last_check"]
    assert "Autonomia" in service.load_profile(ctx.paths).confirmed_soft_skills()


def test_structured_import_downgrades_claims_not_in_resume(ctx, resume_docx, tmp_path):
    structured = {
        "contact": {"name": {"value": "Joana Exemplo", "source": "resume"}},
        "experiences": [
            {"title": "Engenheira de Software Sênior", "company": "Acme Pagamentos", "start": "2021-01",
             "end": "present", "technologies": ["Java"],
             "highlights": [{"value": "Reduzi a latência de APIs REST em 35% com cache Redis.", "source": "resume"},
                            {"value": "Aumentei a receita em 300%", "source": "resume"}]},
            {"title": "CTO", "company": "Empresa Inventada", "start": "2015-01", "end": "2016-01"},
        ],
        "hard_skills": [{"value": "Java", "source": "resume"}, {"value": "Haskell", "source": "resume"}],
        "soft_skills": [{"value": "Leadership", "source": "inferred", "evidence": "Liderei a migração"}],
        "languages": [{"language": "Inglês", "level": "C1", "source": "resume"}],
    }
    json_file = tmp_path / "s.json"
    json_file.write_text(json.dumps(structured), encoding="utf-8")
    result = service.import_resume(ctx.conn, ctx.paths, resume_docx, service.structured_from_file(json_file))
    draft, _ = markdown.parse(result.draft_path.read_text(encoding="utf-8"))
    skills = {f.value: f.source for f in draft.hard_skills}
    assert skills["Java"] == "resume" and skills["Haskell"] == "inferred"
    exps = {e.company: e for e in draft.experiences}
    assert exps["Empresa Inventada"].source == "inferred"
    highlights = {h.value: h.source for h in exps["Acme Pagamentos"].highlights}
    assert highlights["Aumentei a receita em 300%"] == "inferred"
    assert {f.value for f in draft.soft_skills} == {"Liderança"}
    assert any("Haskell" in n for n in result.notes)


def test_experience_years_merge_overlaps():
    profile = Profile(experiences=[
        Experience("A", "X", start="2020-01", end="2020-12"),
        Experience("B", "Y", start="2020-07", end="2021-06"),
        Experience("C", "Z", start="2023-01", end="2023-12", source="inferred"),
    ])
    assert profile.months_of(profile.experiences[:2]) == 18
    assert profile.total_months() == 18, "experiências inferidas não contam"
    profile.hard_skills.append(Fact("Scala", "inferred"))
    assert "Scala" in profile.inferred_hard_skills()
