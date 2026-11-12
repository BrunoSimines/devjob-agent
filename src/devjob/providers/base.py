"""Provider interface for job sources."""

from __future__ import annotations

from abc import ABC, abstractmethod

from devjob.discovery.models import CompanySource, Job


class ProviderError(Exception):
    """Base error for job sources."""


class SourceNotFound(ProviderError):
    """The board/site/tenant does not exist (HTTP 404 or equivalent)."""


class AccessDenied(ProviderError):
    """The source requires authentication or refused access. Never bypassed."""


class ProviderUnavailable(ProviderError):
    """Network failure, timeout, rate limit or server error after retries."""


class JobProvider(ABC):
    name: str = ""
    label: str = ""
    docs_url: str = ""

    def __init__(self, http) -> None:
        self.http = http

    @abstractmethod
    def fetch_jobs(self, source: CompanySource) -> list[Job]:
        """Return every published job for a company source (not yet finalized)."""

    @abstractmethod
    def fetch_job(self, source: CompanySource, external_id: str) -> Job | None:
        """Return a single job, or None when it is no longer published."""

    def validate_source(self, source: CompanySource) -> str | None:
        """Check the source exists. Returns the company name when available."""
        jobs = self.fetch_jobs(source)
        return jobs[0].company if jobs else source.name
