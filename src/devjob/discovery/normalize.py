"""Normalization: canonical URLs, fingerprints and conservative field inference.

Field values coming from a provider's structured data are recorded as such in
``field_sources``. Values derived from free text are labelled with their origin
so the user can tell what was stated by the source and what was inferred.
Salary and publication dates are never guessed.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from devjob.discovery.models import Job
from devjob.matching.requirements import extract_requirements
from devjob.security import detect_injection, sanitize_text
from devjob.textutil import detect_language, norm, sha256_text

_TRACKING_PARAMS = {"gh_src", "source", "lever-source", "lever-origin", "ref", "referrer", "src", "trk",
                    "fbclid", "gclid", "mc_cid", "mc_eid", "_hsenc", "_hsmi", "lipi", "trackingid", "refid",
                    "origin", "s"}
_HOST_ALIASES = {"boards.greenhouse.io": "job-boards.greenhouse.io",
                 "boards.eu.greenhouse.io": "job-boards.eu.greenhouse.io"}


def canonical_url(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    host = _HOST_ALIASES.get(host, host)
    path = re.sub(r"/+", "/", parts.path or "/").rstrip("/") or "/"
    if host.endswith("lever.co") and path.endswith("/apply"):
        path = path[: -len("/apply")]
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS]
    if host.endswith("greenhouse.io") and re.search(r"/jobs/\d+$", path):
        query = []
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


_LOCATION_STOPWORDS = {"remote", "remoto", "remota", "hybrid", "hibrido", "onsite", "on", "site", "office",
                       "presencial", "home", "anywhere", "or", "ou", "and", "e", "de", "the", "only",
                       "full", "time", "100"}


def location_tokens(location: str | None) -> set[str]:
    return {t for t in norm(location).split() if t not in _LOCATION_STOPWORDS and len(t) > 1}


def fingerprint(company: str, title: str) -> str:
    return f"{norm(company)}|{norm(title)}"


_SENIORITY_PATTERNS = [
    ("manager", r"\b(manager|gerente|head of|director|diretor|diretora|vp)\b"),
    ("principal", r"\bprincipal\b"),
    ("staff", r"\bstaff\b"),
    ("lead", r"\b(tech lead|lead|l[ií]der t[eé]cnic[oa]|tech leader)\b"),
    ("senior", r"\b(senior|s[eê]nior|sr\.?)(?![a-z])"),
    ("mid", r"\b(pleno|mid[- ]level|mid|intermediate)\b"),
    ("junior", r"\b(junior|j[uú]nior|jr\.?)(?![a-z])"),
    ("intern", r"\b(intern|internship|estagi[aá]ri[oa]|est[aá]gio|trainee)\b"),
]


def seniority_from_title(title: str) -> str | None:
    for level, pattern in _SENIORITY_PATTERNS:
        if re.search(pattern, title or "", re.IGNORECASE):
            return level
    return None


_WORK_MODEL_PATTERNS = {
    "remote": r"\b(remote|remoto|remota|100% remot\w*|home office|anywhere|work from home|teletrabalho)\b",
    "hybrid": r"\b(hybrid|h[ií]brid[oa])\b",
    "onsite": r"\b(on-?site|in-office|presencial|in office)\b",
}


def work_model_from_text(text: str | None) -> str | None:
    found = [m for m, p in _WORK_MODEL_PATTERNS.items() if re.search(p, text or "", re.IGNORECASE)]
    return found[0] if len(found) == 1 else None


def contract_from_text(text: str | None) -> str | None:
    text = text or ""
    found = []
    if re.search(r"\bCLT\b", text):
        found.append("clt")
    if re.search(r"\bPJ\b|pessoa jur[ií]dica", text, re.IGNORECASE):
        found.append("pj")
    if re.search(r"\b(contractor|contract role|freelance|freelancer|B2B contract)\b", text, re.IGNORECASE):
        found.append("contractor")
    return found[0] if len(found) == 1 else None


_CURRENCY = r"(R\$|US\$|USD|BRL|EUR|€|GBP|£|\$)"
_AMOUNT = r"(\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s*(k|mil)?"
_SALARY_RE = re.compile(
    rf"{_CURRENCY}\s?{_AMOUNT}(?:\s*(?:-|–|—|to|a|até)\s*{_CURRENCY}?\s?{_AMOUNT})?", re.IGNORECASE
)
_SALARY_CONTEXT = re.compile(r"\b(salary|sal[aá]rio|salarial|compensation|remunera[cç][aã]o|pay|base|range|faixa|"
                             r"bolsa|ote|wage|ctc|pretens[aã]o)\b", re.IGNORECASE)
_CURRENCY_MAP = {"r$": "BRL", "brl": "BRL", "us$": "USD", "usd": "USD", "eur": "EUR", "€": "EUR",
                 "gbp": "GBP", "£": "GBP"}


def _parse_amount(raw: str, suffix: str | None) -> float | None:
    raw = raw.replace(" ", "")
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in raw or "." in raw:
        sep = "," if "," in raw else "."
        head, _, tail = raw.rpartition(sep)
        raw = raw.replace(sep, "") if len(tail) == 3 else head.replace(sep, "") + "." + tail
    try:
        value = float(raw)
    except ValueError:
        return None
    if suffix and suffix.lower() in {"k", "mil"}:
        value *= 1000
    return value


def _period_near(text: str) -> str | None:
    t = text.lower()
    if re.search(r"/\s*m[eê]s|por m[eê]s|mensal|per month|/\s*month|monthly|/mo\b", t):
        return "month"
    if re.search(r"/\s*ano|por ano|anual|per year|/\s*year|annual|annually|/\s*yr|a year|per annum", t):
        return "year"
    if re.search(r"/\s*h(?:our|ora)?\b|por hora|per hour|hourly", t):
        return "hour"
    return None


def salary_from_text(text: str | None) -> dict | None:
    """Only explicit amounts with a currency marker. Returns None when absent."""
    text = text or ""
    for match in _SALARY_RE.finditer(text):
        currency = _CURRENCY_MAP.get(match.group(1).lower())
        if currency is None:
            code = re.match(r"\s*(USD|BRL|EUR|GBP|CAD|AUD)\b", text[match.end(): match.end() + 12])
            currency = code.group(1) if code else None
        low = _parse_amount(match.group(2), match.group(3))
        high = _parse_amount(match.group(5), match.group(6)) if match.group(5) else None
        if low is None or low < 100:
            continue
        window = text[max(0, match.start() - 80): match.end() + 60]
        period = _period_near(window)
        if period is None and not _SALARY_CONTEXT.search(window):
            continue
        period_source = "description_text"
        if period is None and currency == "BRL" and 1000 <= (high or low) < 100000:
            period, period_source = "month", "inferred"
        elif period is None and currency in {"USD", "EUR", "GBP"} and (high or low) >= 20000:
            period, period_source = "year", "inferred"
        return {"min": low, "max": high, "currency": currency, "period": period,
                "period_source": period_source, "evidence": match.group(0)}
    return None


def finalize(job: Job, now: str | None = None) -> Job:
    """Sanitize and enrich a provider job in place. Returns the same object."""
    job.title = sanitize_text(job.title, 300)
    job.description = sanitize_text(job.description)
    job.location = sanitize_text(job.location, 300) or None
    job.suspicious = detect_injection(f"{job.title}\n{job.description}")
    sources = job.field_sources

    if not job.requirements:
        job.requirements = extract_requirements(job.description)
    if not job.seniority and (level := seniority_from_title(job.title)):
        job.seniority, sources["seniority"] = level, "title_text"
    if not job.work_model:
        if (model := work_model_from_text(job.location)):
            job.work_model, sources["work_model"] = model, "location_text"
        elif (model := work_model_from_text(job.description)):
            job.work_model, sources["work_model"] = model, "description_text"
    if not job.contract_type and (contract := contract_from_text(job.description)):
        job.contract_type, sources["contract_type"] = contract, "description_text"
    if not job.has_salary and (salary := salary_from_text(job.description)):
        job.salary_min, job.salary_max = salary["min"], salary["max"]
        job.salary_currency = job.salary_currency or salary["currency"]
        job.salary_period = salary["period"]
        sources["salary"] = f"description_text: \"{salary['evidence']}\""
        if salary["period"]:
            sources["salary_period"] = salary["period_source"]
    if not job.language:
        job.language = detect_language(job.description)

    job.canonical_url = canonical_url(job.url)
    job.aliases = sorted({canonical_url(u) for u in job.aliases if u} - {job.canonical_url})
    job.fingerprint = fingerprint(job.company, job.title)
    job.content_hash = sha256_text(f"{job.title}\n{job.company}\n{job.location}\n{job.description}")
    job.last_verified_at = job.last_verified_at or (now if job.verification in {"listed", "page_found"} else None)
    return job


def ms_to_iso(value) -> str | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None
