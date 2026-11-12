"""Normalized job posting and company source models."""

from __future__ import annotations

from dataclasses import dataclass, field

from devjob.textutil import slugify

# verification:
#   listed      -> present in the official public ATS listing at last_verified_at
#   page_found  -> the posting page was fetched and described the job (not proof it is open)
#   unverified  -> reported by web search or the user; not checked
#   not_listed  -> previously listed, missing from the latest official listing (likely closed)
VERIFICATION_LABELS = {
    "listed": "listada na fonte oficial na última verificação",
    "page_found": "página encontrada; não confirma que está aberta",
    "unverified": "não verificada",
    "not_listed": "não aparece mais na fonte oficial (provavelmente encerrada)",
}
VERIFICATION_RANK = {"not_listed": 0, "unverified": 1, "page_found": 2, "listed": 3}


@dataclass
class CompanySource:
    provider: str
    slug: str
    name: str | None = None
    region: str = ""
    careers_url: str | None = None
    id: int | None = None
    last_fetched_at: str | None = None
    last_status: str | None = None


@dataclass
class Job:
    source: str
    external_id: str
    title: str
    company: str
    url: str
    company_slug: str = ""
    description: str = ""
    location: str | None = None
    work_model: str | None = None
    contract_type: str | None = None
    seniority: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    posted_at: str | None = None
    apply_url: str | None = None
    language: str | None = None
    canonical_url: str = ""
    fingerprint: str = ""
    content_hash: str = ""
    field_sources: dict[str, str] = field(default_factory=dict)
    requirements: dict = field(default_factory=dict)
    suspicious: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    verification: str = "unverified"
    last_verified_at: str | None = None
    status: str = "discovered"
    ignored: bool = False
    first_seen_at: str | None = None

    @property
    def id(self) -> str:
        return f"{self.source}:{self.company_slug or slugify(self.company)}:{self.external_id}"

    @property
    def has_salary(self) -> bool:
        return self.salary_min is not None or self.salary_max is not None
