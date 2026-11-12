"""Human-readable search results. Presentation only: scores are shown as calculated."""

from __future__ import annotations

import re

from devjob.discovery.search import RankedJob, source_tier
from devjob.textutil import norm

_WORK_MODEL = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial"}
_CONTRACT = {"clt": "CLT", "pj": "PJ", "international": "Internacional", "contractor": "Contractor"}
_PERIOD = {"month": "mês", "year": "ano", "hour": "hora"}
_MISSING = "Não informado"
_CELL_LIMIT = 110

_ROWS = (
    ("Cargo", "cargo"),
    ("Localização", "location"),
    ("Modelo", "model"),
    ("Salário", "salary"),
    ("Contratação", "contract"),
    ("Compatibilidade", "score"),
    ("Confiança", "confidence"),
    ("Requisitos atendidos", "met"),
    ("Gaps ou competências não comprovadas", "unmet"),
    ("Requisitos incertos ou não verificados", "unverified"),
)


def order_for_display(results: list[RankedJob], prefs: dict | None = None) -> list[RankedJob]:
    """Preferred boards first, then companies by their best score. Jobs inside a company by score."""
    groups: dict[str, list[RankedJob]] = {}
    names: dict[str, str] = {}
    for item in results:
        key = norm(item.job.company) or ""
        groups.setdefault(key, []).append(item)
        names.setdefault(key, (item.job.company or "").strip() or _MISSING)

    def company_key(key: str) -> tuple:
        items = groups[key]
        tier = min(source_tier(item.job, prefs) for item in items)
        return (tier, -_best_score(items), names[key].casefold())

    ordered_keys = sorted(groups, key=company_key)
    ordered: list[RankedJob] = []
    for key in ordered_keys:
        ordered.extend(sorted(groups[key], key=lambda item: (-(item.match.score if item.match.score is not None else -1),
                                                            item.job.title)))
    return ordered


def render_results(results: list[RankedJob], prefs: dict | None = None) -> str:
    """Markdown tables grouped by company. Each job gets its own vertical table."""
    ordered = order_for_display(results, prefs)
    if not ordered:
        return "Nenhuma vaga compatível encontrada com os filtros atuais."
    numbers = {id(item): index for index, item in enumerate(ordered, 1)}
    groups: dict[str, list[RankedJob]] = {}
    names: dict[str, str] = {}
    for item in ordered:
        key = norm(item.job.company) or ""
        groups.setdefault(key, []).append(item)
        names.setdefault(key, (item.job.company or "").strip() or _MISSING)
    blocks = [_company_block(names[key], groups[key], numbers) for key in groups]
    return "\n\n".join(blocks)


def split_findings(match) -> tuple[str, str, str]:
    """Met skills, proven gaps, and items the resume does not confirm or the posting does not state."""
    unmet: list[str] = []
    unverified: list[str] = []
    for gap in match.gaps:
        if "(desejável)" in gap:
            unverified.append(_clean(gap))
        else:
            unmet.append(_clean(gap))
    unverified.extend(_clean(item) for item in match.uncertain)
    return _join(list(match.met)), _join(unmet), _join(unverified)


def _company_block(name: str, items: list[RankedJob], numbers: dict[int, int]) -> str:
    heading = f"## {_cell(name)}"
    tables = [_vertical(_row(item, numbers[id(item)])) for item in items]
    return heading + "\n\n" + "\n\n".join(tables)


def _row(item: RankedJob, number: int) -> dict[str, str]:
    job, match = item.job, item.match
    met, unmet, unverified = split_findings(match)
    return {
        "cargo": _cargo(number, job.title, job.url),
        "location": _location(job.location, item.also_locations),
        "model": _WORK_MODEL.get(job.work_model or "", _MISSING),
        "salary": _salary(job),
        "contract": _CONTRACT.get((job.contract_type or "").lower(), _MISSING if not job.contract_type else job.contract_type),
        "score": _percent(match.score, 1),
        "confidence": _percent(match.confidence, 100),
        "met": met,
        "unmet": unmet,
        "unverified": unverified,
    }


def _vertical(row: dict[str, str]) -> str:
    lines = ["| Informação | Vaga |", "| --- | --- |"]
    lines += [f"| {_cell(label)} | {row[key]} |" for label, key in _ROWS]
    return "\n".join(lines)


def _cargo(number: int, title: str, url: str) -> str:
    label = f"{number}. {_cell(title)}"
    if not url:
        return label
    return f"[{label}]({url.strip()})"


def _location(location: str | None, also: list[str]) -> str:
    main = (location or "").strip() or _MISSING
    extra = [place.strip() for place in also if place and place.strip() and place.strip() != main]
    if not extra:
        return _cell(main)
    suffix = ", ".join(extra[:3])
    if len(extra) > 3:
        suffix += f" +{len(extra) - 3}"
    return _cell(f"{main} (também {suffix})")


def _salary(job) -> str:
    if not job.has_salary:
        return _MISSING
    low = _amount(job.salary_min)
    high = _amount(job.salary_max) if job.salary_max not in (None, job.salary_min) else ""
    amount = f"{low}–{high}" if high else low
    currency = job.salary_currency or _MISSING
    period = _PERIOD.get(job.salary_period or "", job.salary_period or "")
    text = f"{currency} {amount}"
    if period:
        text += f"/{period}"
    return _cell(text)


def _amount(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{value:,.0f}".replace(",", ".")


def _percent(value: float | None, scale: float) -> str:
    if value is None:
        return _MISSING
    number = value * scale
    if abs(number - round(number)) < 0.05:
        return f"{number:.0f}%"
    return f"{number:.1f}%"


def _clean(item: str) -> str:
    text = item.replace(" (obrigatório)", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _join(items: list[str]) -> str:
    if not items:
        return "Nenhum"
    kept: list[str] = []
    for item in items:
        if item and item not in kept:
            kept.append(item)
    shown = kept[:5]
    text = ", ".join(shown)
    if len(kept) > len(shown):
        text += f" +{len(kept) - len(shown)}"
    return _cell(text)


def _cell(text: str) -> str:
    text = text.replace("\n", " ").replace("|", "\\|").replace("]", "\\]")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _CELL_LIMIT:
        text = text[: _CELL_LIMIT - 3].rstrip() + "..."
    return text or _MISSING


def _best_score(items: list[RankedJob]) -> float:
    scores = [item.match.score for item in items if item.match.score is not None]
    return max(scores) if scores else -1.0
