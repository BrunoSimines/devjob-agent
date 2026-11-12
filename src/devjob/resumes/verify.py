"""Truthfulness checks for a resume draft against the confirmed profile.

A draft may be reworded by the user or the host agent before approval, so it is
re-checked here: companies, titles, dates, numbers and technologies must all be
backed by confirmed facts in profile.md.
"""

from __future__ import annotations

import re

from devjob import taxonomy
from devjob.profile.model import Profile
from devjob.textutil import norm

_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*")
_HEADER_RE = re.compile(r"^###\s+(?P<title>.+?)\s+—\s+(?P<company>.+?)\s*$")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _numbers(text: str) -> set[str]:
    return {n.lstrip("0") or "0" for n in (m.group(0).replace(",", ".") for m in _NUMBER_RE.finditer(text))}


def verify_resume(markdown: str, profile: Profile) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block approval."""
    errors: list[str] = []
    warnings: list[str] = []
    if re.search(r"!\[[^\]]*\]\(|<img\b", markdown, re.IGNORECASE):
        errors.append("o tema proíbe imagens, ícones e gráficos")
    if re.search(r"[█▓▒░]{3,}", markdown):
        errors.append("o tema proíbe barras de habilidades")
    experiences = {(norm(e.title), norm(e.company)): e for e in profile.confirmed_experiences()}
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        match = _HEADER_RE.match(line.strip())
        if not match:
            continue
        key = (norm(match.group("title")), norm(match.group("company")))
        exp = experiences.get(key)
        if exp is None:
            errors.append(f"experiência '{match.group('title')} — {match.group('company')}' não existe como fato "
                          "confirmado no perfil")
            continue
        period_line = lines[i + 1] if i + 1 < len(lines) else ""
        years = set(_YEAR_RE.findall(period_line))
        allowed = {y for y in ((exp.start or "")[:4], (exp.end or "")[:4]) if y}
        if years - allowed:
            errors.append(f"datas de '{exp.title} @ {exp.company}' divergem do perfil "
                          f"({', '.join(sorted(years))} vs {exp.start} – {exp.end})")

    allowed_numbers = _numbers(profile.confirmed_text())
    body = "\n".join(lines[2:]) if len(lines) > 2 else markdown
    for number in sorted(_numbers(body) - allowed_numbers):
        errors.append(f"número '{number}' não aparece em nenhum fato confirmado do perfil")

    confirmed = profile.confirmed_hard_skills()
    supported = confirmed | set(taxonomy.expand_implications(confirmed))
    for skill in sorted(set(taxonomy.find_skills(markdown)) - supported):
        reason = "está apenas inferida no perfil" if skill in profile.inferred_hard_skills() else "não consta no perfil"
        errors.append(f"tecnologia '{skill}' {reason}")

    for skill in taxonomy.find_skills(markdown):
        count = len(re.findall(re.escape(skill), markdown, re.IGNORECASE))
        if count > 8:
            warnings.append(f"'{skill}' aparece {count} vezes; evite repetição excessiva (keyword stuffing)")
    return errors, warnings
