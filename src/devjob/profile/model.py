"""Professional profile data model.

Every fact carries a provenance:
  resume   -> found explicitly in an imported resume
  user     -> declared or confirmed by the user
  inferred -> suggested by the tool or agent; never used as a fact until confirmed
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date

from devjob import taxonomy
from devjob.textutil import norm, slugify

SOURCES = ("resume", "user", "inferred")
CONFIRMED = frozenset({"resume", "user"})
_TRUST = {"inferred": 0, "resume": 1, "user": 2}


@dataclass
class Fact:
    value: str
    source: str = "user"
    evidence: str | None = None
    category: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.source in CONFIRMED

    def key(self) -> str:
        return norm(self.value)


@dataclass
class Experience:
    title: str
    company: str
    id: str = ""
    start: str | None = None
    end: str | None = None
    location: str | None = None
    technologies: list[str] = field(default_factory=list)
    highlights: list[Fact] = field(default_factory=list)
    source: str = "resume"

    def __post_init__(self) -> None:
        if not self.id:
            year = (self.start or "")[:4]
            self.id = "exp-" + slugify(self.company or self.title, 30) + (f"-{year}" if year else "")

    @property
    def confirmed(self) -> bool:
        return self.source in CONFIRMED

    def key(self) -> tuple[str, str]:
        return norm(self.company), norm(self.title)

    def interval(self, today: date | None = None) -> tuple[int, int] | None:
        start = parse_month(self.start)
        if start is None:
            return None
        end = month_index(today or date.today()) if self.end in (None, "present") else parse_month(self.end)
        if end is None or end < start:
            return None
        return start, end

    def text(self, confirmed_only: bool = True) -> str:
        parts = [self.title, self.company, ", ".join(self.technologies)]
        parts += [h.value for h in self.highlights if h.confirmed or not confirmed_only]
        return "\n".join(p for p in parts if p)

    def skills(self) -> set[str]:
        found = set(taxonomy.find_skills(self.text()))
        for tech in self.technologies:
            found.add(taxonomy.canonical_skill(tech) or tech)
        return found


@dataclass
class Language:
    code: str
    level: str | None = None
    source: str = "user"
    evidence: str | None = None

    @property
    def confirmed(self) -> bool:
        return self.source in CONFIRMED


@dataclass
class Profile:
    contact: dict[str, Fact] = field(default_factory=dict)
    summary: Fact | None = None
    experiences: list[Experience] = field(default_factory=list)
    projects: list[Fact] = field(default_factory=list)
    hard_skills: list[Fact] = field(default_factory=list)
    soft_skills: list[Fact] = field(default_factory=list)
    education: list[Fact] = field(default_factory=list)
    certifications: list[Fact] = field(default_factory=list)
    languages: list[Language] = field(default_factory=list)
    specializations: list[Fact] = field(default_factory=list)
    version: int = 0
    updated_at: str | None = None

    LIST_SECTIONS = ("projects", "hard_skills", "soft_skills", "education", "certifications", "specializations")

    # -- consultas ---------------------------------------------------------
    @property
    def name(self) -> str | None:
        fact = self.contact.get("name")
        return fact.value if fact else None

    def confirmed_experiences(self) -> list[Experience]:
        return [e for e in self.experiences if e.confirmed]

    def confirmed_hard_skills(self) -> set[str]:
        skills = {f.value for f in self.hard_skills if f.confirmed}
        skills |= {f.value for f in self.specializations if f.confirmed}
        for exp in self.confirmed_experiences():
            skills |= exp.skills()
        return skills

    def inferred_hard_skills(self) -> set[str]:
        return {f.value for f in self.hard_skills if not f.confirmed} - self.confirmed_hard_skills()

    def confirmed_soft_skills(self) -> set[str]:
        return {f.value for f in self.soft_skills if f.confirmed}

    def inferred_soft_skills(self) -> set[str]:
        return {f.value for f in self.soft_skills if not f.confirmed} - self.confirmed_soft_skills()

    def experiences_using(self, skill: str) -> list[Experience]:
        return [e for e in self.confirmed_experiences() if skill in e.skills()]

    def months_of(self, experiences: list[Experience], today: date | None = None) -> int:
        intervals = sorted(i for i in (e.interval(today) for e in experiences) if i)
        total, current = 0, None
        for start, end in intervals:
            if current is None or start > current[1]:
                if current:
                    total += current[1] - current[0] + 1
                current = [start, end]
            else:
                current[1] = max(current[1], end)
        if current:
            total += current[1] - current[0] + 1
        return total

    def total_months(self) -> int:
        return self.months_of(self.confirmed_experiences())

    def language_level(self, code: str) -> str | None:
        for lang in self.languages:
            if lang.code == code and lang.confirmed:
                return lang.level
        return None

    def pending_inferences(self) -> list[tuple[str, str]]:
        pending: list[tuple[str, str]] = []
        for section in self.LIST_SECTIONS:
            pending += [(section, f.value) for f in getattr(self, section) if not f.confirmed]
        pending += [("languages", lang.code) for lang in self.languages if not lang.confirmed]
        for exp in self.experiences:
            if not exp.confirmed:
                pending.append(("experiences", f"{exp.title} @ {exp.company}"))
            pending += [("highlights", h.value) for h in exp.highlights if not h.confirmed]
        return pending

    def confirmed_text(self) -> str:
        """All confirmed content, used to verify generated resumes."""
        parts = [f.value for f in self.contact.values() if f.confirmed]
        if self.summary and self.summary.confirmed:
            parts.append(self.summary.value)
        for exp in self.confirmed_experiences():
            parts += [exp.title, exp.company, exp.location or "", exp.start or "", exp.end or ""]
            parts += exp.technologies
            parts += [h.value for h in exp.highlights if h.confirmed]
        for section in self.LIST_SECTIONS:
            parts += [f.value for f in getattr(self, section) if f.confirmed]
        return "\n".join(p for p in parts if p)


# -- datas -----------------------------------------------------------------

def month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def parse_month(value: str | None) -> int | None:
    if not value or value == "present":
        return None
    match = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?", value.strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2) or 1)
    return year * 12 + month - 1


# -- merge -----------------------------------------------------------------

def _merge_facts(current: list[Fact], incoming: list[Fact], label: str, changes: list[str]) -> list[Fact]:
    result = list(current)
    index = {f.key(): f for f in result}
    for fact in incoming:
        existing = index.get(fact.key())
        if existing is None:
            result.append(copy.copy(fact))
            index[fact.key()] = result[-1]
            changes.append(f"+ {label}: {fact.value} [{fact.source}]")
        elif _TRUST[fact.source] > _TRUST[existing.source]:
            changes.append(f"~ {label}: {existing.value} [{existing.source} -> {fact.source}]")
            existing.source = fact.source
            existing.evidence = fact.evidence or existing.evidence
    return result


def merge_profiles(current: Profile, incoming: Profile) -> tuple[Profile, list[str]]:
    """Add new facts from ``incoming`` without discarding anything already in ``current``."""
    merged = copy.deepcopy(current)
    changes: list[str] = []
    for key, fact in incoming.contact.items():
        existing = merged.contact.get(key)
        if existing is None:
            merged.contact[key] = copy.copy(fact)
            changes.append(f"+ contato.{key}: {fact.value}")
        elif existing.source != "user" and norm(existing.value) != norm(fact.value) and fact.confirmed:
            changes.append(f"~ contato.{key}: {existing.value} -> {fact.value}")
            merged.contact[key] = copy.copy(fact)
    if incoming.summary and (merged.summary is None or (merged.summary.source != "user"
                                                        and incoming.summary.key() != merged.summary.key())):
        changes.append("~ resumo atualizado" if merged.summary else "+ resumo")
        merged.summary = copy.copy(incoming.summary)

    by_key = {e.key(): e for e in merged.experiences}
    by_id = {e.id: e for e in merged.experiences}
    for exp in incoming.experiences:
        existing = by_key.get(exp.key()) or by_id.get(exp.id)
        if existing is None:
            new = copy.deepcopy(exp)
            while new.id in by_id:
                new.id += "-b"
            merged.experiences.append(new)
            by_key[new.key()] = by_id[new.id] = new
            changes.append(f"+ experiência: {exp.title} @ {exp.company} ({exp.start or '?'} – {exp.end or '?'})")
            continue
        for attr in ("start", "end", "location"):
            if not getattr(existing, attr) and getattr(exp, attr):
                setattr(existing, attr, getattr(exp, attr))
                changes.append(f"~ {existing.id}.{attr}: {getattr(exp, attr)}")
        known = {norm(t) for t in existing.technologies}
        for tech in exp.technologies:
            if norm(tech) not in known:
                existing.technologies.append(tech)
                known.add(norm(tech))
                changes.append(f"+ {existing.id}.tecnologia: {tech}")
        existing.highlights = _merge_facts(existing.highlights, exp.highlights, f"{existing.id}.destaque", changes)
        if _TRUST[exp.source] > _TRUST[existing.source]:
            existing.source = exp.source

    for section in Profile.LIST_SECTIONS:
        setattr(merged, section, _merge_facts(getattr(merged, section), getattr(incoming, section), section, changes))

    langs = {lang.code: lang for lang in merged.languages}
    for lang in incoming.languages:
        existing = langs.get(lang.code)
        if existing is None:
            merged.languages.append(copy.copy(lang))
            langs[lang.code] = merged.languages[-1]
            changes.append(f"+ idioma: {lang.code} {lang.level or '?'} [{lang.source}]")
        elif existing.source != "user" and lang.level and lang.level != existing.level:
            changes.append(f"~ idioma {lang.code}: {existing.level} -> {lang.level}")
            existing.level, existing.source = lang.level, lang.source
    return merged, changes
