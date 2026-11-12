"""Map career page / job URLs to supported providers (company discovery)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from devjob.discovery.models import CompanySource

_INHIRE_RESERVED = {"api", "auth", "www", "app", "files", "docs", "help"}
_TOKEN = r"[A-Za-z0-9_.-]+"


def parse_url(url: str) -> tuple[CompanySource, str | None] | None:
    """Return (company source, external job id or None) for a supported URL."""
    parts = urlsplit(url.strip() if "://" in url else "https://" + url.strip())
    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]
    query = parse_qs(parts.query)

    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        if segments[:2] == ["embed", "job_board"] and query.get("for"):
            return CompanySource("greenhouse", query["for"][0]), None
        if segments and segments[0] != "embed":
            job_id = segments[2] if len(segments) >= 3 and segments[1] == "jobs" else None
            return CompanySource("greenhouse", segments[0]), job_id
    if host == "boards-api.greenhouse.io" and len(segments) >= 3 and segments[:2] == ["v1", "boards"]:
        job_id = segments[4] if len(segments) >= 5 and segments[3] == "jobs" else None
        return CompanySource("greenhouse", segments[2]), job_id
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} and segments:
        region = "eu" if ".eu." in host else ""
        return CompanySource("lever", segments[0], region=region), (segments[1] if len(segments) > 1 else None)
    if host in {"api.lever.co", "api.eu.lever.co"} and len(segments) >= 3 and segments[:2] == ["v0", "postings"]:
        region = "eu" if ".eu." in host else ""
        return CompanySource("lever", segments[2], region=region), (segments[3] if len(segments) > 3 else None)
    if host.endswith(".inhire.app"):
        tenant = host[: -len(".inhire.app")]
        if tenant and "." not in tenant and tenant not in _INHIRE_RESERVED:
            job_id = segments[1] if len(segments) >= 2 and segments[0] == "vagas" else None
            return CompanySource("inhire", tenant), job_id
    return None


_HTML_PATTERNS = [
    ("greenhouse", "", re.compile(r"(?:job-)?boards\.greenhouse\.io/embed/job_board(?:/js)?\?for=(" + _TOKEN + ")")),
    ("greenhouse", "", re.compile(r"(?:job-)?boards\.greenhouse\.io/(?!embed)(" + _TOKEN + r")(?:/jobs|[\"'/?])")),
    ("greenhouse", "", re.compile(r"boards-api\.greenhouse\.io/v1/boards/(" + _TOKEN + ")")),
    ("lever", "", re.compile(r"jobs\.lever\.co/(" + _TOKEN + ")")),
    ("lever", "eu", re.compile(r"jobs\.eu\.lever\.co/(" + _TOKEN + ")")),
    ("inhire", "", re.compile(r"https?://([a-z0-9-]+)\.inhire\.app")),
]


def scan_html(html: str) -> list[CompanySource]:
    """Find ATS boards referenced by a career page (links, embeds, scripts)."""
    found: dict[tuple[str, str, str], CompanySource] = {}
    for provider, region, pattern in _HTML_PATTERNS:
        for match in pattern.finditer(html or ""):
            slug = match.group(1).strip(".")
            if provider == "inhire" and slug in _INHIRE_RESERVED:
                continue
            if provider == "greenhouse" and slug in {"embed", "jobs"}:
                continue
            found.setdefault((provider, slug.lower(), region), CompanySource(provider, slug, region=region))
    return list(found.values())
