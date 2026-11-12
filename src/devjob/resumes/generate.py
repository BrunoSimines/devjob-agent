"""Build resume drafts from confirmed profile facts and approve them into the library."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

import yaml

from devjob import taxonomy
from devjob.config.settings import Paths, builtin_template
from devjob.profile.model import Experience, Profile, parse_month
from devjob.matching.resume_fit import lane_key, same_lane
from devjob.prompts.loader import load_flow
from devjob.resumes import library, render
from devjob.resumes.layout_check import check_pdf
from devjob.resumes.theme import Theme, ThemeError, apply_page_format, load_theme
from devjob.resumes.verify import verify_resume
from devjob.storage.db import now_iso
from devjob.textutil import sha256_text, slugify

LABELS = {
    "pt": {"summary_title": "Resumo", "skills_title": "Competências técnicas", "experience_title": "Experiência",
           "projects_title": "Projetos", "education_title": "Formação", "certifications_title": "Certificações",
           "languages_title": "Idiomas", "present": "Atual", "technologies": "Tecnologias"},
    "en": {"summary_title": "Summary", "skills_title": "Technical skills", "experience_title": "Experience",
           "projects_title": "Projects", "education_title": "Education", "certifications_title": "Certifications",
           "languages_title": "Languages", "present": "Present", "technologies": "Technologies"},
}
_MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_LEVEL_LABELS = {
    "pt": {"native": "Nativo", "C2": "Proficiente (C2)", "C1": "Avançado (C1)", "B2": "Intermediário avançado (B2)",
           "B1": "Intermediário (B1)", "A2": "Básico (A2)", "A1": "Básico (A1)"},
    "en": {"native": "Native", "C2": "Proficient (C2)", "C1": "Advanced (C1)", "B2": "Upper intermediate (B2)",
           "B1": "Intermediate (B1)", "A2": "Basic (A2)", "A1": "Basic (A1)"},
}
_LANG_NAMES_EN = {"en": "English", "pt": "Portuguese", "es": "Spanish", "fr": "French", "de": "German",
                  "it": "Italian"}


class VerificationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("O rascunho contém informações não comprovadas no perfil:\n- " + "\n- ".join(errors))
        self.errors = errors


@dataclass
class DraftSpec:
    label: str
    target_roles: list[str] = field(default_factory=list)
    focus_skills: list[str] = field(default_factory=list)
    language: str = "pt"
    job_id: str | None = None
    template: str = "ats-classic"


def _fmt_month(value: str | None, language: str) -> str:
    if value in (None, "present"):
        return LABELS[language]["present"] if value == "present" else "?"
    index = parse_month(value)
    if index is None:
        return value
    year, month = divmod(index, 12)
    if len(value) == 4:
        return str(year)
    return f"{_MONTHS_EN[month]} {year}" if language == "en" else f"{month + 1:02d}/{year}"


def _relevance(exp: Experience, focus: set[str]) -> int:
    return len(exp.skills() & focus)


def _experience_block(exp: Experience, focus: set[str], language: str, detailed: bool) -> str:
    lines = [f"### {exp.title} — {exp.company}"]
    period = f"{_fmt_month(exp.start, language)} – {_fmt_month(exp.end, language)}"
    lines.append(period + (f" · {exp.location}" if exp.location else ""))
    highlights = [h for h in exp.highlights if h.confirmed]
    highlights.sort(key=lambda h: -len(set(taxonomy.find_skills(h.value)) & focus))
    if not detailed:
        highlights = highlights[:2]
    lines += [f"- {h.value}" for h in highlights]
    techs = sorted(exp.technologies, key=lambda t: (t not in focus, exp.technologies.index(t)))
    if techs:
        lines.append(f"{LABELS[language]['technologies']}: {', '.join(techs)}")
    return "\n".join(lines)


def generation_provenance(config: dict | None = None) -> tuple[dict, Theme]:
    """Identity of the prompts and the theme used for a resume. The instruction text stays in the files."""
    loaded = load_flow("resume-generation")
    theme = apply_page_format(loaded.theme if loaded.theme is not None else load_theme(), config)
    return {"prompts": [prompt.identity() for prompt in loaded.prompts], "theme": theme.identity()}, theme


def _template(paths: Paths, name: str) -> str:
    custom = paths.templates / f"{name}.md"
    return custom.read_text(encoding="utf-8") if custom.exists() else builtin_template(f"{name}.md")


def build_markdown(profile: Profile, spec: DraftSpec, template_text: str, max_skills: int) -> tuple[str, list[str], list[str]]:
    """Return (markdown, experience_ids used, highlighted skills)."""
    language = spec.language if spec.language in LABELS else "pt"
    labels = LABELS[language]
    focus = set(spec.focus_skills)

    contact_keys = ("email", "phone", "location", "linkedin", "github", "website")
    contact = " · ".join(profile.contact[k].value for k in contact_keys
                         if k in profile.contact and profile.contact[k].confirmed)

    confirmed_skills = [f.value for f in profile.hard_skills if f.confirmed]
    for exp in profile.confirmed_experiences():
        confirmed_skills += [s for s in exp.skills() if s not in confirmed_skills]
    ordered = [s for s in spec.focus_skills if s in confirmed_skills]
    ordered += [s for s in confirmed_skills if s not in ordered]
    ordered = list(dict.fromkeys(ordered))[:max_skills]
    category_labels = taxonomy.CATEGORY_LABELS_EN if language == "en" else taxonomy.CATEGORY_LABELS
    groups: dict[str, list[str]] = {}
    for skill in ordered:
        groups.setdefault(category_labels[taxonomy.category_of(skill)], []).append(skill)
    skills_md = "\n".join(f"- {cat}: {', '.join(items)}" for cat, items in groups.items())

    experiences = sorted(profile.confirmed_experiences(),
                         key=lambda e: (parse_month(e.start) or 0), reverse=True)
    blocks, used = [], []
    for exp in experiences:
        detailed = not focus or _relevance(exp, focus) > 0
        blocks.append(_experience_block(exp, focus, language, detailed))
        used.append(exp.id)

    projects = [f for f in profile.projects if f.confirmed]
    projects.sort(key=lambda f: -len(set(taxonomy.find_skills(f.value)) & focus))
    level_labels = _LEVEL_LABELS[language]
    languages = []
    for lang in profile.languages:
        if not lang.confirmed:
            continue
        name = _LANG_NAMES_EN.get(lang.code, lang.code) if language == "en" else taxonomy.LANGUAGE_LABELS.get(lang.code, lang.code)
        languages.append(f"- {name}: {level_labels.get(str(lang.level), lang.level or '')}".rstrip(": "))

    values = {
        **labels,
        "name": profile.name or "",
        "contact_line": contact,
        "summary": profile.summary.value if profile.summary and profile.summary.confirmed else "",
        "skills": skills_md,
        "experience": "\n\n".join(blocks),
        "projects": "\n".join(f"- {f.value}" for f in projects[:4]),
        "education": "\n".join(f"- {f.value}" for f in profile.education if f.confirmed),
        "certifications": "\n".join(f"- {f.value}" for f in profile.certifications if f.confirmed),
        "languages": "\n".join(languages),
    }
    rendered = Template(template_text).safe_substitute(values)
    markdown = _drop_empty_sections(rendered)
    highlighted = [s for s in ordered if s in focus] or ordered[:8]
    return markdown, used, highlighted


def _drop_empty_sections(markdown: str) -> str:
    out: list[str] = []
    sections = markdown.split("\n## ")
    out.append(sections[0].rstrip())
    for section in sections[1:]:
        title, _, body = section.partition("\n")
        if body.strip():
            out.append(f"## {title}\n{body.strip()}")
    return "\n\n".join(out).strip() + "\n"


def create_draft(paths: Paths, config: dict, profile: Profile, profile_version: int, profile_hash: str | None,
                 spec: DraftSpec) -> Path:
    provenance, _theme = generation_provenance(config)
    template_text = _template(paths, spec.template)
    markdown, used, highlighted = build_markdown(profile, spec, template_text, config["resumes"]["max_skills_listed"])
    draft_id = f"draft-{slugify(spec.label, 30)}-{spec.language}-{now_iso()[:19].replace(':', '').replace('-', '')}"
    folder = paths.drafts / draft_id
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "resume.md").write_text(markdown, encoding="utf-8")
    notes = []
    if profile.summary and spec.language not in ("pt",) and profile.summary.value:
        notes.append("O conteúdo vem do perfil no idioma original. Traduções devem ser fiéis: sem novos fatos, "
                     "números ou tecnologias.")
    meta = {"label": spec.label, "target_roles": spec.target_roles, "focus_skills": spec.focus_skills,
            "language": spec.language, "job_id": spec.job_id, "template": spec.template,
            "experience_ids": used, "highlighted_skills": highlighted, "profile_version": profile_version,
            "profile_hash": profile_hash, "created_at": now_iso(), "notes": notes,
            "provenance": provenance}
    (folder / "draft.yaml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return folder


def list_drafts(paths: Paths) -> list[dict]:
    drafts = []
    for folder in sorted(paths.drafts.glob("draft-*")):
        meta_file = folder / "draft.yaml"
        if meta_file.exists():
            meta = yaml.safe_load(meta_file.read_text(encoding="utf-8")) or {}
            drafts.append({"draft_id": folder.name, "path": str(folder / "resume.md"), **meta})
    return drafts


def _draft_folder(paths: Paths, draft_id: str) -> Path:
    folder = paths.drafts / draft_id
    if not (folder / "resume.md").exists():
        raise library.ResumeError(f"Rascunho não encontrado: {draft_id}")
    return folder


def check_draft(paths: Paths, profile: Profile, draft_id: str) -> tuple[list[str], list[str]]:
    folder = _draft_folder(paths, draft_id)
    return verify_resume((folder / "resume.md").read_text(encoding="utf-8"), profile)


def approve_draft(conn: sqlite3.Connection, paths: Paths, config: dict, profile: Profile, draft_id: str,
                  force_similar: bool = False, export_docx: bool | None = None) -> tuple[library.ResumeRecord, list[str]]:
    """Verify, deduplicate, render and store a draft. Returns (record, warnings)."""
    folder = _draft_folder(paths, draft_id)
    markdown = (folder / "resume.md").read_text(encoding="utf-8")
    meta = yaml.safe_load((folder / "draft.yaml").read_text(encoding="utf-8")) or {}
    errors, warnings = verify_resume(markdown, profile)
    if errors:
        raise VerificationError(errors)
    skills = set(taxonomy.find_skills(markdown))
    similar, score = library.most_similar(conn, markdown, skills)
    new_lane = lane_key(meta.get("label") or "", list(meta.get("target_roles") or []), meta.get("language"), profile)
    if similar and score >= config["resumes"]["duplicate_similarity"] and not force_similar:
        old_lane = lane_key(similar.label, similar.target_roles, similar.language, profile)
        if same_lane(new_lane, old_lane):
            raise library.DuplicateResumeError(similar.id, score)
        warnings.append(f"texto parecido com '{similar.id}', mantido porque a ênfase ou a senioridade é outra")

    provenance, theme = generation_provenance(config)
    resume_id = library.next_id(conn, meta.get("label") or "geral", meta.get("language"))
    target = paths.resumes / resume_id
    target.mkdir(parents=True, exist_ok=False)
    md_path = target / "resume.md"
    md_path.write_text(markdown, encoding="utf-8")
    try:
        pdf_path = render.render_pdf(markdown, target / "resume.pdf", theme)
        docx_path = None
        if export_docx if export_docx is not None else config["resumes"]["export_docx"]:
            docx_path = render.render_docx(markdown, target / "resume.docx", theme)
        (target / "provenance.yaml").write_text(
            yaml.safe_dump(provenance, sort_keys=False, allow_unicode=True), encoding="utf-8")
        report = check_pdf(pdf_path, markdown, theme, preview_dir=target)
        (target / "layout-report.yaml").write_text(
            yaml.safe_dump(report.to_dict(), sort_keys=False, allow_unicode=True), encoding="utf-8")
        if report.errors:
            raise ThemeError(
                "O currículo não passou na validação de layout:\n- " + "\n- ".join(report.errors)
                + "\nA validação não afirma compatibilidade universal com sistemas ATS.")
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    now = now_iso()
    record = library.ResumeRecord(
        id=resume_id, label=meta.get("label") or "geral", origin="generated", language=meta.get("language"),
        target_roles=meta.get("target_roles") or [], highlighted_skills=meta.get("highlighted_skills") or [],
        experience_ids=meta.get("experience_ids") or [], content_hash=sha256_text(markdown), dir=str(target),
        source_profile_version=meta.get("profile_version"), source_profile_hash=meta.get("profile_hash"),
        facts_fingerprint=library.facts_fingerprint(profile, meta.get("experience_ids") or [],
                                                    meta.get("highlighted_skills") or []),
        md_path=str(md_path), pdf_path=str(pdf_path), docx_path=str(docx_path) if docx_path else None,
        created_at=now, updated_at=now,
    )
    library.insert(conn, record)
    shutil.rmtree(folder)
    return record, warnings


def discard_draft(paths: Paths, draft_id: str) -> None:
    shutil.rmtree(_draft_folder(paths, draft_id))
