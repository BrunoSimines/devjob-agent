"""Greenhouse Job Board API (public, no authentication for GET).

Docs: https://docs.greenhouse.io/job-board.html
  GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
  GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}
"""

from __future__ import annotations

from urllib.parse import quote

from devjob.discovery.models import CompanySource, Job
from devjob.providers.base import JobProvider, SourceNotFound
from devjob.textutil import html_to_text

API = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseProvider(JobProvider):
    name = "greenhouse"
    label = "Greenhouse Job Board API"
    docs_url = "https://docs.greenhouse.io/job-board.html"

    def _to_job(self, source: CompanySource, item: dict) -> Job:
        token = source.slug
        job_id = str(item["id"])
        board_url = f"https://job-boards.greenhouse.io/{token}/jobs/{job_id}"
        url = item.get("absolute_url") or board_url
        sources = {"title": "greenhouse:title", "location": "greenhouse:location.name",
                   "description": "greenhouse:content"}
        posted = item.get("first_published")
        if posted:
            sources["posted_at"] = "greenhouse:first_published"
        return Job(
            source=self.name, external_id=job_id, company_slug=token,
            title=item.get("title") or "",
            company=item.get("company_name") or source.name or token,
            url=url, apply_url=url,
            description=html_to_text(item.get("content")),
            location=(item.get("location") or {}).get("name"),
            posted_at=posted,
            field_sources=sources,
            aliases=[board_url],
            verification="listed",
        )

    def _jobs(self, source: CompanySource, data: dict, *, with_content: bool) -> list[Job]:
        if not isinstance(data, dict) or "jobs" not in data:
            raise SourceNotFound(f"Greenhouse: resposta inesperada para '{source.slug}'")
        jobs = []
        for item in data["jobs"]:
            if not item.get("id") or not item.get("title"):
                continue
            if not with_content:
                item = {key: value for key, value in item.items() if key != "content"}
            jobs.append(self._to_job(source, item))
        return jobs

    def fetch_listings(self, source: CompanySource) -> list[Job]:
        """Titles and locations only. The description is a second request."""
        return self._jobs(source, self.http.get_json(f"{API}/{quote(source.slug)}/jobs"), with_content=False)

    def fetch_jobs(self, source: CompanySource) -> list[Job]:
        return self._jobs(source, self.http.get_json(f"{API}/{quote(source.slug)}/jobs?content=true"),
                          with_content=True)

    def fetch_job(self, source: CompanySource, external_id: str) -> Job | None:
        try:
            item = self.http.get_json(f"{API}/{quote(source.slug)}/jobs/{quote(str(external_id))}")
        except SourceNotFound:
            return None
        return self._to_job(source, item)

    def validate_source(self, source: CompanySource) -> str | None:
        data = self.http.get_json(f"{API}/{quote(source.slug)}")
        return data.get("name") if isinstance(data, dict) else None
