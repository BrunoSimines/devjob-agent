"""Import a structured extraction produced by the host agent (Claude Code / Cursor).

The agent reads the extracted resume text and writes JSON following
``references/profile-schema.md``. Nothing is trusted blindly: every fact that
claims ``source: resume`` is checked against the resume text and downgraded to
``inferred`` when it cannot be found there.
"""

from __future__ import annotations

from typing import Any

from devjob import taxonomy
from devjob.profile.model import SOURCES, Experience, Fact, Language, Profile
from devjob.textutil import norm, token_set


class StructuredImportError(ValueError):
    pass


def _present(value: str, text_norm: str, text_tokens: set[str]) -> bool:
    key = norm(value)
    if not key:
        return False
    if key in text_norm:
        return True
    tokens = token_set(value)
    if len(tokens) >= 4:
        return len(tokens & text_tokens) / len(tokens) >= 0.8
    return False


def _fact(raw: Any, default_source: str, text_norm: str, tokens: set[str], downgrades: list[str],
          label: str) -> Fact | None:
    if isinstance(raw, str):
        raw = {"value": raw}
    if not isinstance(raw, dict) or not str(raw.get("value", "")).strip():
        return None
    value = str(raw["value"]).strip()
    source = raw.get("source", default_source)
    if source not in SOURCES:
        source = "inferred"
    evidence = raw.get("evidence")
    if source == "resume" and not _present(value, text_norm, tokens):
        downgrades.append(f"{label}: '{value[:60]}' não foi localizado no texto do currículo -> inferred")
        source = "inferred"
        evidence = evidence or "declarado pelo agente, não localizado literalmente no currículo"
    return Fact(value, source, evidence, raw.get("category"))


def profile_from_structured(data: dict[str, Any], resume_text: str) -> tuple[Profile, list[str]]:
    if not isinstance(data, dict):
        raise StructuredImportError("O JSON estruturado deve ser um objeto.")
    text_norm = norm(resume_text)
    tokens = token_set(resume_text)
    downgrades: list[str] = []
    profile = Profile()

    for key, raw in (data.get("contact") or {}).items():
        fact = _fact(raw, "resume", text_norm, tokens, downgrades, f"contato.{key}")
        if fact:
            profile.contact[key] = fact
    if data.get("summary"):
        profile.summary = _fact(data["summary"], "resume", text_norm, tokens, downgrades, "resumo")

    for raw in data.get("experiences") or []:
        title, company = str(raw.get("title", "")).strip(), str(raw.get("company", "")).strip()
        if not title or not company:
            downgrades.append(f"experiência sem cargo/empresa ignorada: {raw!r:.80}")
            continue
        source = raw.get("source", "resume")
        if source == "resume" and not (_present(title, text_norm, tokens) and _present(company, text_norm, tokens)):
            downgrades.append(f"experiência '{title} @ {company}' não localizada no currículo -> inferred")
            source = "inferred"
        exp = Experience(
            title=title, company=company, start=raw.get("start"), end=raw.get("end"),
            location=raw.get("location"), source=source if source in SOURCES else "inferred",
            technologies=[taxonomy.canonical_skill(t) or t for t in raw.get("technologies") or []],
        )
        for h in raw.get("highlights") or []:
            fact = _fact(h, "resume", text_norm, tokens, downgrades, f"{exp.id}.destaque")
            if fact:
                exp.highlights.append(fact)
        profile.experiences.append(exp)

    for section in Profile.LIST_SECTIONS:
        facts = []
        for raw in data.get(section) or []:
            fact = _fact(raw, "resume", text_norm, tokens, downgrades, section)
            if not fact:
                continue
            if section == "hard_skills":
                fact.value = taxonomy.canonical_skill(fact.value) or fact.value
                fact.category = fact.category or taxonomy.category_of(fact.value)
            elif section == "soft_skills":
                fact.value = taxonomy.canonical_soft_skill(fact.value) or fact.value
            facts.append(fact)
        setattr(profile, section, facts)

    for raw in data.get("languages") or []:
        code = taxonomy.language_code(str(raw.get("language", ""))) if isinstance(raw, dict) else None
        if not code:
            continue
        source = raw.get("source", "resume")
        names = taxonomy.LANGUAGE_NAMES.get(code, ())
        if source == "resume" and not any(norm(n) in text_norm for n in names):
            downgrades.append(f"idioma '{raw.get('language')}' não localizado no currículo -> inferred")
            source = "inferred"
        level = raw.get("level")
        profile.languages.append(Language(code, taxonomy.parse_level(str(level)) if level else None,
                                          source if source in SOURCES else "inferred", raw.get("evidence")))
    return profile, downgrades
