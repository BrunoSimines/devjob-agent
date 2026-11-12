"""Lever Postings API v0 (public, published postings only).

Docs: https://github.com/lever/postings-api
  GET https://api.lever.co/v0/postings/{site}?mode=json&skip=&limit=
  GET https://api.eu.lever.co/v0/postings/{site}?mode=json   (EU-hosted sites)
"""

from __future__ import annotations

from urllib.parse import quote

from devjob.discovery.models import CompanySource, Job
from devjob.discovery.normalize import ms_to_iso
from devjob.providers.base import JobProvider, SourceNotFound
from devjob.textutil import html_to_text

HOSTS = {"": "https://api.lever.co", "global": "https://api.lever.co", "eu": "https://api.eu.lever.co"}
PAGE_SIZE = 100
_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}
_INTERVAL = {"per-year-salary": "year", "per-month-salary": "month", "per-hour-wage": "hour",
             "per-week-salary": None, "per-day-wage": None, "one-time": None}


class LeverProvider(JobProvider):
    name = "lever"
    label = "Lever Postings API"
    docs_url = "https://github.com/lever/postings-api"

    def _base(self, source: CompanySource) -> str:
        return f"{HOSTS.get(source.region or '', HOSTS[''])}/v0/postings/{quote(source.slug)}"

    def _to_job(self, source: CompanySource, item: dict) -> Job:
        categories = item.get("categories") or {}
        parts = [item.get("openingPlain") or "", item.get("descriptionBodyPlain") or item.get("descriptionPlain") or ""]
        for block in item.get("lists") or []:
            heading = (block.get("text") or "").strip()
            parts.append(f"## {heading}\n{html_to_text(block.get('content'))}")
        parts.append(item.get("additionalPlain") or "")
        sources = {"title": "lever:text", "location": "lever:categories.location",
                   "description": "lever:description+lists"}
        job = Job(
            source=self.name, external_id=str(item["id"]), company_slug=source.slug,
            title=item.get("text") or "", company=source.name or source.slug,
            url=item.get("hostedUrl") or f"https://jobs.lever.co/{source.slug}/{item['id']}",
            apply_url=item.get("applyUrl"),
            description="\n\n".join(p for p in parts if p.strip()),
            location=categories.get("location"),
            field_sources=sources, verification="listed",
        )
        workplace = _WORKPLACE.get((item.get("workplaceType") or "").lower())
        if workplace:
            job.work_model, sources["work_model"] = workplace, "lever:workplaceType"
        created = ms_to_iso(item.get("createdAt"))
        if created:
            job.posted_at = created
            sources["posted_at"] = "lever:createdAt (data de criação da vaga, não necessariamente de publicação)"
        salary = item.get("salaryRange") or {}
        if salary.get("min") is not None or salary.get("max") is not None:
            job.salary_min, job.salary_max = salary.get("min"), salary.get("max")
            job.salary_currency = salary.get("currency")
            job.salary_period = _INTERVAL.get(salary.get("interval"))
            sources["salary"] = "lever:salaryRange"
        return job

    def fetch_jobs(self, source: CompanySource) -> list[Job]:
        jobs: list[Job] = []
        skip = 0
        while True:
            data = self.http.get_json(f"{self._base(source)}?mode=json&skip={skip}&limit={PAGE_SIZE}")
            if isinstance(data, dict) and data.get("ok") is False:
                raise SourceNotFound(f"Lever: site '{source.slug}' não encontrado ({data.get('error')})")
            if not isinstance(data, list):
                raise SourceNotFound(f"Lever: resposta inesperada para '{source.slug}'")
            jobs += [self._to_job(source, item) for item in data if item.get("id") and item.get("text")]
            if len(data) < PAGE_SIZE:
                return jobs
            skip += PAGE_SIZE

    def fetch_job(self, source: CompanySource, external_id: str) -> Job | None:
        try:
            item = self.http.get_json(f"{self._base(source)}/{quote(str(external_id))}?mode=json")
        except SourceNotFound:
            return None
        if not isinstance(item, dict) or item.get("ok") is False:
            return None
        return self._to_job(source, item)

    def validate_source(self, source: CompanySource) -> str | None:
        data = self.http.get_json(f"{self._base(source)}?mode=json&limit=1")
        if isinstance(data, dict) and data.get("ok") is False:
            raise SourceNotFound(f"Lever: site '{source.slug}' não encontrado")
        return source.name
