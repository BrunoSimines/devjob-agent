"""Jobs found outside the supported ATS APIs.

* ``job_from_page``: a single posting page fetched on user request, parsed from
  schema.org ``JobPosting`` JSON-LD (https://schema.org/JobPosting).
* ``jobs_from_records``: postings reported by the host agent's web search.
  They are stored as ``unverified`` until checked against an official source.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from devjob.discovery.models import Job
from devjob.discovery.normalize import canonical_url
from devjob.textutil import html_to_text, sha256_text

_LD_RE = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_UNIT = {"MONTH": "month", "YEAR": "year", "HOUR": "hour"}
_EMPLOYMENT = {"CONTRACTOR": "contractor"}


def _walk(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from _walk(node["@graph"])


def _is_posting(node: dict) -> bool:
    kind = node.get("@type")
    return kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind)


def find_job_postings(html: str) -> list[dict]:
    postings = []
    for block in _LD_RE.findall(html or ""):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        postings += [n for n in _walk(data) if _is_posting(n)]
    return postings


def _external_id(url: str) -> str:
    return sha256_text(canonical_url(url))[:16]


def _location(posting: dict) -> str | None:
    locations = posting.get("jobLocation")
    if isinstance(locations, dict):
        locations = [locations]
    names = []
    for loc in locations or []:
        address = (loc or {}).get("address") or {}
        if isinstance(address, str):
            names.append(address)
            continue
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        parts = [address.get("addressLocality"), address.get("addressRegion"), country]
        names.append(", ".join(p for p in parts if p))
    return " • ".join(n for n in names if n) or None


def job_from_posting(posting: dict, url: str) -> Job:
    org = posting.get("hiringOrganization") or {}
    company = org.get("name") if isinstance(org, dict) else str(org)
    job = Job(
        source="web", external_id=_external_id(url), title=str(posting.get("title") or "").strip(),
        company=company or "", url=url, apply_url=url,
        description=html_to_text(posting.get("description")), location=_location(posting),
        verification="page_found",
        field_sources={"title": "json-ld:title", "description": "json-ld:description"},
    )
    sources = job.field_sources
    if posting.get("datePosted"):
        job.posted_at, sources["posted_at"] = str(posting["datePosted"]), "json-ld:datePosted"
    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        job.work_model, sources["work_model"] = "remote", "json-ld:jobLocationType"
    employment = posting.get("employmentType")
    if isinstance(employment, str) and employment.upper() in _EMPLOYMENT:
        job.contract_type, sources["contract_type"] = _EMPLOYMENT[employment.upper()], "json-ld:employmentType"
    salary = posting.get("baseSalary") or {}
    value = salary.get("value") if isinstance(salary, dict) else None
    if isinstance(value, dict) and (value.get("minValue") or value.get("maxValue") or value.get("value")):
        job.salary_min = value.get("minValue") or value.get("value")
        job.salary_max = value.get("maxValue")
        job.salary_currency = salary.get("currency")
        job.salary_period = _UNIT.get(str(value.get("unitText", "")).upper())
        sources["salary"] = "json-ld:baseSalary"
    valid = posting.get("validThrough")
    if valid:
        sources["valid_through"] = f"json-ld:validThrough={valid}"
        try:
            expires = datetime.fromisoformat(str(valid).replace("Z", "+00:00"))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < datetime.now(timezone.utc):
                job.verification = "not_listed"
        except ValueError:
            pass
    return job


def job_from_page(http, url: str) -> Job | None:
    html = http.get_text(url)
    postings = find_job_postings(html)
    if not postings:
        return None
    return job_from_posting(postings[0], url)


REQUIRED_FIELDS = ("title", "company", "url")


def jobs_from_records(records: list[dict]) -> tuple[list[Job], list[str]]:
    """Build unverified jobs from agent-reported records. Returns (jobs, errors)."""
    jobs: list[Job] = []
    errors: list[str] = []
    for i, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"registro {i}: não é um objeto")
            continue
        missing = [f for f in REQUIRED_FIELDS if not str(record.get(f) or "").strip()]
        if missing:
            errors.append(f"registro {i}: campos obrigatórios ausentes: {', '.join(missing)}")
            continue
        url = str(record["url"]).strip()
        if not url.lower().startswith(("http://", "https://")):
            errors.append(f"registro {i}: URL inválida")
            continue
        job = Job(source="web", external_id=_external_id(url), title=str(record["title"]),
                  company=str(record["company"]), url=url, apply_url=url,
                  description=str(record.get("description") or ""), location=record.get("location"),
                  verification="unverified",
                  field_sources={"all": f"reportado pela busca web do agente ({record.get('found_via', 'web')})"})
        if record.get("work_model") in ("remote", "hybrid", "onsite"):
            job.work_model = record["work_model"]
            job.field_sources["work_model"] = "reportado pela página (agente)"
        salary = record.get("salary") or {}
        if isinstance(salary, dict) and (salary.get("min") or salary.get("max")) and salary.get("currency"):
            job.salary_min, job.salary_max = salary.get("min"), salary.get("max")
            job.salary_currency, job.salary_period = salary.get("currency"), salary.get("period")
            job.field_sources["salary"] = f"reportado pela página (agente): \"{salary.get('evidence', '')}\""
        if record.get("posted_at") and record.get("posted_at_evidence"):
            job.posted_at = str(record["posted_at"])
            job.field_sources["posted_at"] = f"reportado pela página: \"{record['posted_at_evidence']}\""
        jobs.append(job)
    return jobs, errors
