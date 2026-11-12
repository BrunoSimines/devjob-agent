"""InHire public career page API (no authentication, requires ``X-Tenant``).

Docs: https://docs.inhire.com.br/api/pagina-de-divulgacao/
  GET https://api.inhire.app/job-posts/public/pages            -> default career page + published jobs
  GET https://api.inhire.app/job-posts/public/pages/{jobId}    -> one published job

The documentation does not specify the response schema. Field names below were
observed in real public responses; parsing is tolerant and missing fields stay
empty. The public job URL follows the pattern seen on InHire career pages:
https://{tenant}.inhire.app/vagas/{jobId}/{slug}
"""

from __future__ import annotations

from urllib.parse import quote

from devjob.discovery.models import CompanySource, Job
from devjob.providers.base import JobProvider, SourceNotFound
from devjob.textutil import html_to_text, slugify

API = "https://api.inhire.app/job-posts/public/pages"
_WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite",
              "presencial": "onsite", "híbrido": "hybrid", "remoto": "remote"}
_CONTRACT = {"clt": "clt", "pj": "pj"}


class InHireProvider(JobProvider):
    name = "inhire"
    label = "InHire (página de carreira pública)"
    docs_url = "https://docs.inhire.com.br/api/pagina-de-divulgacao/"

    def _headers(self, source: CompanySource) -> dict[str, str]:
        return {"X-Tenant": source.slug}

    def _to_job(self, source: CompanySource, item: dict, company: str | None) -> Job:
        job_id = str(item.get("jobId") or item.get("id"))
        title = (item.get("displayName") or item.get("name") or "").strip()
        sources = {"title": "inhire:displayName", "location": "inhire:location",
                   "url": "construído pelo padrão público {tenant}.inhire.app/vagas/{jobId}/{slug}"}
        job = Job(
            source=self.name, external_id=job_id, company_slug=source.slug, title=title,
            company=company or source.name or source.slug,
            url=f"https://{source.slug}.inhire.app/vagas/{job_id}/{slugify(title, 80)}",
            description=html_to_text(item.get("description")),
            location=item.get("location"), field_sources=sources, verification="listed",
        )
        job.apply_url = job.url
        workplace = _WORKPLACE.get(str(item.get("workplaceType") or "").lower())
        if workplace:
            job.work_model, sources["work_model"] = workplace, "inhire:workplaceType"
        contracts = [_CONTRACT.get(str(c).lower()) for c in item.get("contractType") or []]
        contracts = [c for c in contracts if c]
        if len(contracts) == 1:
            job.contract_type, sources["contract_type"] = contracts[0], "inhire:contractType"
        if item.get("publishedAt"):
            job.posted_at, sources["posted_at"] = item["publishedAt"], "inhire:publishedAt"
        return job

    def _page(self, source: CompanySource) -> dict:
        page = self.http.get_json(API, self._headers(source))
        if not isinstance(page, dict) or "jobsPage" not in page:
            raise SourceNotFound(f"InHire: tenant '{source.slug}' sem página de carreira pública")
        return page

    def fetch_listings(self, source: CompanySource) -> list[Job]:
        """Titles from the career page. Each description is a separate request."""
        page = self._page(source)
        company = page.get("tenantName")
        jobs = []
        for summary in page.get("jobsPage") or []:
            if summary.get("status") not in (None, "published") or not summary.get("jobId"):
                continue
            jobs.append(self._to_job(source, summary, company))
        return jobs

    def fetch_jobs(self, source: CompanySource) -> list[Job]:
        page = self._page(source)
        company = page.get("tenantName")
        jobs: list[Job] = []
        for summary in page.get("jobsPage") or []:
            if summary.get("status") not in (None, "published") or not summary.get("jobId"):
                continue
            detail = self.fetch_job(source, summary["jobId"], company=company)
            jobs.append(detail or self._to_job(source, summary, company))
        return jobs

    def fetch_job(self, source: CompanySource, external_id: str, company: str | None = None) -> Job | None:
        try:
            item = self.http.get_json(f"{API}/{quote(str(external_id))}", self._headers(source))
        except SourceNotFound:
            return None
        if not isinstance(item, dict) or item.get("status") not in (None, "published"):
            return None
        return self._to_job(source, item, company or item.get("tenantName"))

    def validate_source(self, source: CompanySource) -> str | None:
        page = self.http.get_json(API, self._headers(source))
        if not isinstance(page, dict) or "jobsPage" not in page:
            raise SourceNotFound(f"InHire: tenant '{source.slug}' não encontrado")
        return page.get("tenantName")
