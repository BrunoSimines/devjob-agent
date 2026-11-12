"""Heuristic resume parser (fallback when the host agent does not provide a
structured extraction). Output always goes to a draft for human review."""

from __future__ import annotations

import re

from devjob import taxonomy
from devjob.profile.model import Experience, Fact, Language, Profile
from devjob.textutil import norm

_HEADINGS = {
    "summary": ["resumo", "resumo profissional", "sobre", "sobre mim", "perfil", "perfil profissional",
                "summary", "professional summary", "about", "about me", "profile", "objetivo", "objective"],
    "experiences": ["experiencia", "experiencias", "experiencia profissional", "experiencias profissionais",
                    "historico profissional", "experience", "work experience", "professional experience",
                    "employment history", "employment"],
    "education": ["formacao", "formacao academica", "educacao", "escolaridade", "education",
                  "academic background"],
    "skills": ["habilidades", "competencias", "competencias tecnicas", "conhecimentos", "skills",
               "technical skills", "hard skills", "tecnologias", "technologies", "stack", "tech stack",
               "soft skills", "habilidades tecnicas"],
    "certifications": ["certificacoes", "certificados", "certifications", "certificates", "cursos",
                       "cursos e certificacoes", "licenses certifications"],
    "languages": ["idiomas", "linguas", "languages"],
    "projects": ["projetos", "projects", "projetos pessoais", "personal projects", "open source"],
}
_HEADING_LOOKUP = {h: section for section, names in _HEADINGS.items() for h in names}

_MONTHS = {
    "jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
}
_MONTH_WORD = (r"(?:jan(?:eiro|uary)?|fev(?:ereiro)?|feb(?:ruary)?|mar(?:ço|co|ch)?|abr(?:il)?|apr(?:il)?"
               r"|mai(?:o)?|may|jun(?:ho|e)?|jul(?:ho|y)?|ago(?:sto)?|aug(?:ust)?|set(?:embro)?"
               r"|sep(?:t(?:ember)?)?|out(?:ubro)?|oct(?:ober)?|nov(?:embro|ember)?|dez(?:embro)?|dec(?:ember)?)")
_DATE = rf"(?:\b{_MONTH_WORD}\.?\s+(?:de\s+)?|\b\d{{1,2}}/)?(?:19|20)\d{{2}}"
_PRESENT = r"presente|atual|atualmente|present|current|now|hoje|o momento|até o momento"
_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE})\s*(?:-|–|—|to|até|a)\s*(?P<end>{_DATE}|{_PRESENT})", re.IGNORECASE
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{2,3}\)?[\s.-]?\d{4,5}[\s.-]?\d{4}")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%]+/?", re.IGNORECASE)
_GITHUB_RE = re.compile(r"(?:https?://)?github\.com/[\w\-]+/?", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-•*▪●◦·–]|\d+[.)])\s+")
_TECH_LINE_RE = re.compile(r"^\s*(?:tecnologias|technologies|stack|tech stack|ferramentas|tools)\s*:\s*(.+)$",
                           re.IGNORECASE)
_ROLE_WORDS = ("engineer", "engenheir", "developer", "desenvolvedor", "programador", "programmer", "analyst",
               "analista", "architect", "arquitet", "lead", "lider", "líder", "manager", "gerente", "consultant",
               "consultor", "specialist", "especialista", "intern", "estagi", "sre", "devops", "cto", "head",
               "director", "diretor", "coordenador", "coordinator", "tech", "scientist", "cientista")


def _parse_date(raw: str) -> str | None:
    raw = raw.strip().lower()
    if re.fullmatch(_PRESENT, raw):
        return "present"
    year = re.search(r"(19|20)\d{2}", raw)
    if not year:
        return None
    month_num = re.match(r"(\d{1,2})/", raw)
    if month_num and 1 <= int(month_num.group(1)) <= 12:
        return f"{year.group(0)}-{int(month_num.group(1)):02d}"
    word = re.match(r"([a-zà-ÿ]{3,9})", raw)
    if word:
        key = norm(word.group(1))[:3]
        if key in _MONTHS:
            return f"{year.group(0)}-{_MONTHS[key]:02d}"
    return year.group(0)


def _heading(line: str) -> str | None:
    text = norm(line.strip().strip(":"))
    if not text or len(text) > 40:
        return None
    return _HEADING_LOOKUP.get(text)


def _split_title_company(text: str) -> tuple[str, str]:
    text = text.strip(" -–—|,")
    for sep in (" @ ", " at ", " na ", " no ", " em ", " | ", " – ", " — ", " - ", ", "):
        if sep in text:
            left, right = (p.strip(" -–—|,") for p in text.split(sep, 1))
            if any(w in left.lower() for w in _ROLE_WORDS) or sep in (" @ ", " at "):
                return left, right
            if any(w in right.lower() for w in _ROLE_WORDS):
                return right, left
            return left, right
    return text, ""


def _is_role(text: str) -> bool:
    return any(w in text.lower() for w in _ROLE_WORDS)


def _sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in lines:
        heading = _heading(line)
        if heading:
            current = heading
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _join_wrapped(lines: list[str]) -> list[str]:
    """Join lines broken by PDF extraction: a non-bullet line continues the previous one."""
    out: list[str] = []
    for line in lines:
        if out and not _BULLET_RE.match(line) and not out[-1].rstrip().endswith((".", ":", ";")) \
                and line[:1].islower():
            out[-1] = out[-1].rstrip() + " " + line.strip()
        else:
            out.append(line.strip())
    return out


def _parse_experiences(lines: list[str]) -> list[Experience]:
    experiences: list[Experience] = []
    pending_header: list[str] = []
    current: Experience | None = None
    for line in _join_wrapped([l for l in lines if l.strip()]):
        match = _RANGE_RE.search(line)
        if match:
            start, end = _parse_date(match.group("start")), _parse_date(match.group("end"))
            remainder = (line[:match.start()] + " " + line[match.end():]).strip(" ()|-–—,")
            header_parts = [p for p in pending_header[-2:] if p]
            if remainder:
                header_parts.append(remainder)
            title, company = "", ""
            if len(header_parts) == 1:
                title, company = _split_title_company(header_parts[0])
            elif len(header_parts) >= 2:
                a, b = header_parts[-2], header_parts[-1]
                if " @ " in b or " at " in b or (" | " in b and _is_role(b)):
                    title, company = _split_title_company(b)
                elif _is_role(a) and not _is_role(b):
                    title, company = a, b
                else:
                    title, company = b, a
            current = Experience(title=title or "(cargo não identificado)",
                                 company=company or "(empresa não identificada)",
                                 start=start if start != "present" else None, end=end, source="resume")
            experiences.append(current)
            pending_header = []
            continue
        tech = _TECH_LINE_RE.match(line)
        if current is not None and tech:
            for item in re.split(r"[,;/|]", tech.group(1)):
                item = item.strip()
                if item:
                    current.technologies.append(taxonomy.canonical_skill(item) or item)
            continue
        if current is not None and (_BULLET_RE.match(line) or len(line) > 60):
            current.highlights.append(Fact(_BULLET_RE.sub("", line).strip(), "resume"))
            continue
        pending_header.append(line)
        if current is not None and len(pending_header) > 2:
            # Long plain lines after an experience are descriptions, not headers.
            current.highlights.append(Fact(pending_header.pop(0), "resume"))
    for exp in experiences:
        for name in taxonomy.find_skills(exp.text(confirmed_only=False)):
            if name not in exp.technologies:
                exp.technologies.append(name)
    return experiences


def _parse_languages(lines: list[str], full_text: str) -> list[Language]:
    found: dict[str, Language] = {}
    for code, level, snippet in taxonomy.find_languages("\n".join(lines)):
        found[code] = Language(code, level, "resume", snippet[:120])
    if not found:
        for code, level, snippet in taxonomy.find_languages(full_text):
            if level:
                found[code] = Language(code, level, "inferred", snippet[:120])
    return list(found.values())


def parse_resume(text: str) -> tuple[Profile, list[str]]:
    """Return a draft profile and notes about what could not be identified."""
    notes: list[str] = []
    lines = [l.rstrip() for l in text.splitlines()]
    sections = _sections([l for l in lines if l.strip()])
    profile = Profile()

    header = sections.get("header", [])
    for line in header[:6]:
        if _EMAIL_RE.search(line) or _PHONE_RE.search(line) or "linkedin" in line.lower():
            continue
        words = line.split()
        if 2 <= len(words) <= 6 and not any(ch.isdigit() for ch in line) and not _is_role(line):
            profile.contact["name"] = Fact(line.strip(), "resume")
            break
    if (m := _EMAIL_RE.search(text)):
        profile.contact["email"] = Fact(m.group(0), "resume")
    if (m := _PHONE_RE.search("\n".join(header) or text)):
        profile.contact["phone"] = Fact(m.group(0).strip(), "resume")
    if (m := _LINKEDIN_RE.search(text)):
        profile.contact["linkedin"] = Fact(m.group(0), "resume")
    if (m := _GITHUB_RE.search(text)):
        profile.contact["github"] = Fact(m.group(0), "resume")
    for key, label in (("name", "nome"), ("email", "e-mail")):
        if key not in profile.contact:
            notes.append(f"{label} não identificado no currículo")

    summary = " ".join(l.strip() for l in sections.get("summary", []) if l.strip())
    if summary:
        profile.summary = Fact(summary, "resume")

    profile.experiences = _parse_experiences(sections.get("experiences", []))
    if not profile.experiences:
        notes.append("nenhuma experiência com datas identificada; revise a seção Experiência manualmente")
    for exp in profile.experiences:
        if exp.title.startswith("(") or exp.company.startswith("("):
            notes.append(f"experiência {exp.start or '?'}–{exp.end or '?'}: cargo ou empresa não identificados")

    skills_text = "\n".join(sections.get("skills", []))
    hard: dict[str, Fact] = {}
    for name, snippet in taxonomy.find_skills(skills_text).items():
        hard[name] = Fact(name, "resume", None, taxonomy.category_of(name))
    for name, snippet in taxonomy.find_skills(text).items():
        hard.setdefault(name, Fact(name, "resume", None, taxonomy.category_of(name)))
    profile.hard_skills = list(hard.values())

    soft: dict[str, Fact] = {}
    for name in taxonomy.find_soft_skills(skills_text):
        soft[name] = Fact(name, "resume")
    experience_text = "\n".join(e.text(confirmed_only=False) for e in profile.experiences)
    for name, evidence in taxonomy.infer_soft_skills(experience_text).items():
        soft.setdefault(name, Fact(name, "inferred", evidence))
    profile.soft_skills = list(soft.values())

    def items(section: str) -> list[Fact]:
        return [Fact(_BULLET_RE.sub("", l).strip(), "resume")
                for l in _join_wrapped([l for l in sections.get(section, []) if l.strip()])]

    profile.education = items("education")
    profile.certifications = items("certifications")
    profile.projects = items("projects")
    profile.languages = _parse_languages(sections.get("languages", []), text)
    if not profile.languages:
        notes.append("idiomas não identificados")
    return profile, notes
