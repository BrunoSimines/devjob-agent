"""Extract structured requirements from a (sanitized) job description."""

from __future__ import annotations

import re

from devjob import taxonomy
from devjob.textutil import detect_language, norm

_REQUIRED_HEADINGS = (
    "requirements", "requisitos", "required", "must have", "must haves", "what you'll need", "what you will need",
    "what we're looking for", "what we are looking for", "qualifications", "minimum qualifications",
    "basic qualifications", "o que esperamos", "o que buscamos", "o que procuramos", "pre requisitos",
    "prerequisites", "you have", "you should have", "about you", "voce tem", "voce precisa ter",
    "requisitos obrigatorios", "requisitos e qualificacoes", "qualificacoes", "experiencia necessaria",
    "habilidades necessarias", "skill set", "skills", "who you are", "requirements and qualifications",
)
_PREFERRED_HEADINGS = (
    "nice to have", "nice to haves", "bonus", "bonus points", "preferred", "preferred qualifications",
    "diferenciais", "diferencial", "desejavel", "desejaveis", "requisitos desejaveis", "plus", "it's a plus",
    "seria um diferencial", "sera um diferencial", "extra points", "pontos extras", "experiencia desejavel",
)
_OTHER_HEADINGS = (
    "responsibilities", "responsabilidades", "what you'll do", "what you will do", "o que voce vai fazer",
    "atividades", "atribuicoes", "benefits", "beneficios", "about us", "sobre nos", "sobre a empresa",
    "quem somos", "perks", "o que oferecemos", "our team", "about the role", "sobre a vaga", "the role",
    "about the team", "compensation", "remuneracao", "how to apply", "processo seletivo", "etapas",
    "modelo de contratacao", "local", "location",
)
_PREF_CUE = re.compile(r"\b(nice to have|nice-to-have|bonus|a plus|is a plus|diferencia(?:l|is)|desej[aá]ve(?:l|is)|"
                       r"preferred|preferably|preferencialmente|ideally|idealmente)\b", re.IGNORECASE)
_REQ_CUE = re.compile(r"\b(required|must|mandatory|obrigat[oó]ri[oa]s?|essencial|indispens[aá]vel|"
                      r"necess[aá]ri[oa])\b", re.IGNORECASE)
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:or more\s+|ou mais\s+)?(?:years?|anos)", re.IGNORECASE)
_LANG_REQ_CUE = re.compile(r"\b(fluent|fluency|fluente|flu[eê]ncia|advanced|avan[cç]ado|proficien\w*|"
                           r"required|obrigat[oó]rio|business|conversa\w*|intermedi\w*|native|nativo|[ABC][12])\b",
                           re.IGNORECASE)


def _heading_mode(line: str) -> str | None:
    raw = line.lstrip("#").strip()
    is_marked = line.startswith("##") or raw.endswith(":")
    head = raw.split(":", 1)[0] if ":" in raw else raw
    key = norm(head)
    if not key or len(key) > 60:
        return None
    if not is_marked and len(key.split()) > 6:
        return None

    def hit(options):
        if is_marked:
            return any(key == norm(o) or key.startswith(norm(o) + " ") for o in options)
        return any(key == norm(o) for o in options)

    if hit(_PREFERRED_HEADINGS):
        return "preferred"
    if hit(_REQUIRED_HEADINGS):
        return "required"
    if hit(_OTHER_HEADINGS):
        return "other"
    return "other" if line.startswith("##") else None


def extract_requirements(text: str) -> dict:
    buckets: dict[str, dict[str, str]] = {"required": {}, "preferred": {}, "mentioned": {}}
    soft: dict[str, dict[str, str]] = {"required": {}, "preferred": {}, "mentioned": {}}
    required_lines: list[str] = []
    structured = False
    mode = "mentioned"
    languages: dict[str, dict] = {}

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        head = _heading_mode(line) if not line.startswith(("- ", "* ")) else None
        if head:
            mode = head if head != "other" else "mentioned"
            structured = structured or head in ("required", "preferred")
            rest = line.split(":", 1)[1].strip() if ":" in line else ""
            if not rest:
                continue
            line = rest
        line_mode = mode
        if _PREF_CUE.search(line):
            line_mode = "preferred"
        elif mode == "mentioned" and _REQ_CUE.search(line):
            line_mode = "required"
        if line_mode == "required":
            required_lines.append(line)
        for name, snippet in taxonomy.find_skills(line).items():
            buckets[line_mode].setdefault(name, snippet)
        for name, snippet in taxonomy.find_soft_skills(line).items():
            soft[line_mode].setdefault(name, snippet)
        for code, level, snippet in taxonomy.find_languages(line):
            if level or _LANG_REQ_CUE.search(line):
                entry = {"code": code, "level": level or "B2", "explicit": True,
                         "required": line_mode != "preferred", "evidence": snippet[:120]}
                if code not in languages or (entry["required"] and not languages[code]["required"]):
                    languages[code] = entry

    for name in list(buckets["preferred"]):
        if name in buckets["required"]:
            del buckets["preferred"][name]
    for name in list(buckets["mentioned"]):
        if name in buckets["required"] or name in buckets["preferred"]:
            del buckets["mentioned"][name]
    for name in list(soft["mentioned"]):
        if name in soft["required"] or name in soft["preferred"]:
            del soft["mentioned"][name]

    years = [int(m.group(1)) for line in required_lines for m in _YEARS_RE.finditer(line)]
    if not years:
        years = [int(m.group(1)) for m in _YEARS_RE.finditer(text or "")]
    years = [y for y in years if 0 < y <= 20]

    description_language = detect_language(text or "")
    if description_language and description_language not in languages:
        languages[description_language] = {
            "code": description_language, "level": "B2", "explicit": False, "required": True,
            "evidence": "idioma em que a vaga foi escrita (inferido)",
        }
    return {
        "structured": structured,
        "required": sorted(buckets["required"]),
        "preferred": sorted(buckets["preferred"]),
        "mentioned": sorted(buckets["mentioned"]),
        "soft_required": sorted(soft["required"]),
        "soft_preferred": sorted(set(soft["preferred"]) | set(soft["mentioned"])),
        "min_years": max(years) if years else None,
        "languages": list(languages.values()),
        "description_language": description_language,
        "evidence": {name: snippet for bucket in buckets.values() for name, snippet in bucket.items()},
        "source": "heuristic",
    }
