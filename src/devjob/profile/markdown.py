"""Render and parse ``profile.md``.

Format (one fact per line, provenance tag at the end):

    ## Hard skills
    ### Linguagens e frameworks
    - Java [resume]
    - Kotlin [inferred] — evidência: "..."

Lines written by hand without a tag are treated as declared by the user.
"""

from __future__ import annotations

import re

import yaml

from devjob import taxonomy
from devjob.profile.model import Experience, Fact, Language, Profile

SCHEMA = "devjob-profile/1"

SECTION_TITLES = {
    "contact": "Contato",
    "summary": "Resumo",
    "experiences": "Experiência",
    "projects": "Projetos",
    "hard_skills": "Hard skills",
    "soft_skills": "Soft skills",
    "education": "Formação",
    "certifications": "Certificações",
    "languages": "Idiomas",
    "specializations": "Especializações",
}
_SECTION_ALIASES = {
    "contato": "contact", "contact": "contact",
    "resumo": "summary", "summary": "summary", "resumo profissional": "summary",
    "experiencia": "experiences", "experiência": "experiences", "experience": "experiences",
    "experiencias": "experiences", "experiências": "experiences",
    "projetos": "projects", "projects": "projects",
    "hard skills": "hard_skills", "competencias tecnicas": "hard_skills", "competências técnicas": "hard_skills",
    "soft skills": "soft_skills", "competencias comportamentais": "soft_skills",
    "competências comportamentais": "soft_skills",
    "formacao": "education", "formação": "education", "education": "education",
    "certificacoes": "certifications", "certificações": "certifications", "certifications": "certifications",
    "idiomas": "languages", "languages": "languages",
    "especializacoes": "specializations", "especializações": "specializations",
    "specializations": "specializations",
}
CONTACT_LABELS = {"name": "nome", "email": "email", "phone": "telefone", "location": "localização",
                  "linkedin": "linkedin", "github": "github", "website": "site"}
_CONTACT_ALIASES = {**{v: k for k, v in CONTACT_LABELS.items()}, **{k: k for k in CONTACT_LABELS},
                    "localizacao": "location", "telefone": "phone", "site": "website"}
_EXP_KEYS = {"id": "id", "período": "period", "periodo": "period", "period": "period",
             "local": "location", "location": "location", "localização": "location",
             "tecnologias": "technologies", "technologies": "technologies", "stack": "technologies"}

_TAG_RE = re.compile(
    r"^(?P<body>.*?)\s*\[(?P<src>resume|user|inferred)\]"
    r"(?:\s*[—–-]+\s*evid[eê]ncia:\s*\"?(?P<ev>.*?)\"?)?\s*$"
)
_CATEGORY_BY_LABEL = {v.lower(): k for k, v in taxonomy.CATEGORY_LABELS.items()}

LEGEND = (
    "<!-- Legenda: [resume] = encontrado no currículo · [user] = declarado ou confirmado por você · "
    "[inferred] = inferido, precisa de confirmação e NÃO é usado como fato.\n"
    "     Edite livremente. Linhas sem marcação são tratadas como [user]. "
    "Depois de editar, rode `devjob profile status`. -->"
)


def _tag(fact_source: str, evidence: str | None = None) -> str:
    tag = f"[{fact_source}]"
    if evidence:
        clean = evidence.replace('"', "'").replace("\n", " ").strip()
        tag += f' — evidência: "{clean[:160]}"'
    return tag


def _fmt_period(exp: Experience) -> str:
    end = "atual" if exp.end == "present" else (exp.end or "?")
    return f"{exp.start or '?'} – {end}"


def render(profile: Profile) -> str:
    meta = {"schema": SCHEMA, "version": profile.version, "updated_at": profile.updated_at}
    out = ["---", yaml.safe_dump(meta, sort_keys=False).strip(), "---",
           f"# Perfil profissional{': ' + profile.name if profile.name else ''}", "", LEGEND, ""]

    out.append(f"## {SECTION_TITLES['contact']}")
    for key, label in CONTACT_LABELS.items():
        fact = profile.contact.get(key)
        if fact:
            out.append(f"- {label}: {fact.value} {_tag(fact.source, fact.evidence)}")
    out.append("")

    out.append(f"## {SECTION_TITLES['summary']}")
    if profile.summary:
        out.append(f"{profile.summary.value} {_tag(profile.summary.source, profile.summary.evidence)}")
    out.append("")

    out.append(f"## {SECTION_TITLES['experiences']}")
    for exp in profile.experiences:
        out.append(f"### {exp.title} @ {exp.company} [{exp.source}]")
        out.append(f"- id: {exp.id}")
        out.append(f"- período: {_fmt_period(exp)}")
        if exp.location:
            out.append(f"- local: {exp.location}")
        if exp.technologies:
            out.append(f"- tecnologias: {', '.join(exp.technologies)}")
        for h in exp.highlights:
            out.append(f"- {h.value} {_tag(h.source, h.evidence)}")
        out.append("")
    out.append("")

    out.append(f"## {SECTION_TITLES['hard_skills']}")
    groups: dict[str, list[Fact]] = {}
    for fact in profile.hard_skills:
        groups.setdefault(fact.category or taxonomy.category_of(fact.value), []).append(fact)
    for category in list(taxonomy.CATEGORY_LABELS):
        if category in groups:
            out.append(f"### {taxonomy.CATEGORY_LABELS[category]}")
            out += [f"- {f.value} {_tag(f.source, f.evidence)}" for f in groups[category]]
    out.append("")

    for section in ("soft_skills", "projects", "education", "certifications", "specializations"):
        out.append(f"## {SECTION_TITLES[section]}")
        out += [f"- {f.value} {_tag(f.source, f.evidence)}" for f in getattr(profile, section)]
        out.append("")

    out.append(f"## {SECTION_TITLES['languages']}")
    for lang in profile.languages:
        label = taxonomy.LANGUAGE_LABELS.get(lang.code, lang.code)
        out.append(f"- {label}: {lang.level or '?'} {_tag(lang.source, lang.evidence)}")
    out.append("")
    return "\n".join(out).rstrip() + "\n"


def _split_tag(line: str) -> tuple[str, str, str | None]:
    match = _TAG_RE.match(line)
    if not match:
        return line.strip(), "user", None
    return match.group("body").strip(), match.group("src"), (match.group("ev") or None)


def _parse_period(value: str) -> tuple[str | None, str | None]:
    parts = re.split(r"\s+(?:–|—|-|a|to|até|\.\.)\s+", value.strip(), maxsplit=1)
    start = parts[0].strip() if parts and parts[0].strip() not in {"", "?"} else None
    end = None
    if len(parts) > 1:
        raw = parts[1].strip().lower()
        if raw in {"atual", "present", "presente", "hoje", "current"}:
            end = "present"
        elif raw not in {"", "?"}:
            end = parts[1].strip()
    return start, end


def parse(text: str) -> tuple[Profile, list[str]]:
    """Parse profile.md. Returns the profile and non-fatal warnings."""
    warnings: list[str] = []
    profile = Profile()
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            meta = yaml.safe_load(text[3:end]) or {}
            profile.version = int(meta.get("version") or 0)
            profile.updated_at = meta.get("updated_at")
            body = text[end + 4:]
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)

    section: str | None = None
    category: str | None = None
    exp: Experience | None = None
    summary_lines: list[str] = []

    for lineno, raw in enumerate(body.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.startswith("# "):
            continue
        if line.startswith("## "):
            title = line[3:].strip().lower()
            section = _SECTION_ALIASES.get(title)
            if section is None:
                warnings.append(f"linha {lineno}: seção desconhecida '{line[3:].strip()}' ignorada")
            category, exp = None, None
            continue
        if section is None:
            continue
        if line.startswith("### "):
            heading = line[4:].strip()
            if section == "experiences":
                head, source, _ = _split_tag(heading)
                title, _, company = head.partition(" @ ")
                exp = Experience(title=title.strip(), company=company.strip(), id="pending", source=source)
                profile.experiences.append(exp)
            elif section == "hard_skills":
                category = _CATEGORY_BY_LABEL.get(heading.lower(), "other")
            continue

        stripped = line.strip()
        is_bullet = stripped.startswith(("- ", "* "))
        item = stripped[2:].strip() if is_bullet else stripped

        if section == "summary":
            summary_lines.append(item)
            continue
        if not is_bullet:
            warnings.append(f"linha {lineno}: texto fora de lista ignorado: '{stripped[:60]}'")
            continue
        if section == "contact":
            key, _, rest = item.partition(":")
            canonical = _CONTACT_ALIASES.get(key.strip().lower())
            if canonical is None:
                warnings.append(f"linha {lineno}: campo de contato desconhecido '{key.strip()}'")
                continue
            value, source, evidence = _split_tag(rest)
            profile.contact[canonical] = Fact(value, source, evidence)
        elif section == "experiences":
            if exp is None:
                warnings.append(f"linha {lineno}: item de experiência sem cabeçalho '### Cargo @ Empresa'")
                continue
            key, sep, rest = item.partition(":")
            exp_key = _EXP_KEYS.get(key.strip().lower()) if sep else None
            if exp_key == "id":
                exp.id = rest.strip()
            elif exp_key == "period":
                exp.start, exp.end = _parse_period(rest)
            elif exp_key == "location":
                exp.location = rest.strip() or None
            elif exp_key == "technologies":
                exp.technologies = [t.strip() for t in rest.split(",") if t.strip()]
            else:
                value, source, evidence = _split_tag(item)
                exp.highlights.append(Fact(value, source, evidence))
        elif section == "languages":
            value, source, evidence = _split_tag(item)
            name, _, level = value.partition(":")
            code = taxonomy.language_code(name.strip())
            if code is None:
                warnings.append(f"linha {lineno}: idioma não reconhecido '{name.strip()}'")
                continue
            level = level.strip()
            parsed_level = None if level in {"", "?"} else (taxonomy.parse_level(level) or level)
            profile.languages.append(Language(code, parsed_level, source, evidence))
        else:
            value, source, evidence = _split_tag(item)
            if not value:
                continue
            fact = Fact(value, source, evidence)
            if section == "hard_skills":
                fact.category = category or taxonomy.category_of(value)
            getattr(profile, section).append(fact)

    if summary_lines:
        value, source, evidence = _split_tag(" ".join(summary_lines))
        profile.summary = Fact(value, source, evidence)

    seen: set[str] = set()
    for item in profile.experiences:
        if item.id in {"", "pending"}:
            item.id = ""
            item.__post_init__()
        while item.id in seen:
            item.id += "-b"
        seen.add(item.id)
        if not item.title or not item.company:
            warnings.append(f"experiência '{item.id}' sem cargo ou empresa (use '### Cargo @ Empresa')")
    return profile, warnings
