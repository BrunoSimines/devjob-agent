"""Classify a public URL. No network, and no ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_GH_JOB = re.compile(r"/([^/]+)/jobs/(\d+)", re.IGNORECASE)
_LEVER_JOB = re.compile(r"/([^/]+)/([0-9a-f-]{8,})", re.IGNORECASE)
_INHIRE_JOB = re.compile(r"/vagas/([^/]+)", re.IGNORECASE)
_JOB_PATH = re.compile(r"/(?:job|jobs|vaga|vagas|position|positions)/([^/]+)", re.IGNORECASE)
_CAREER_ROOT = re.compile(r"^/?(?:careers|carreiras|jobs|vagas|trabalhe-conosco)/?$", re.IGNORECASE)
_CAREER_HOST = ("careers", "carreiras", "jobs", "vagas")
_ATS_CHANNELS = {"greenhouse", "lever", "ashby", "inhire", "gupy", "smartrecruiters", "workday"}
_HOST_LABELS = {"www", "jobs", "job", "careers", "career", "carreiras", "vagas", "br", "com", "io", "app",
                "co", "net", "org", "me", "lat"}
_ASHBY_JOB = re.compile(r"/([^/]+)/([0-9a-f-]{36})", re.IGNORECASE)


@dataclass(frozen=True)
class ClassifiedUrl:
    channel: str
    kind: str
    aggregator: bool
    slug: str = ""
    external_id: str = ""

    @property
    def official(self) -> bool:
        return not self.aggregator and self.kind in {"posting", "career_page", "board"}


def classify_url(url: str | None) -> ClassifiedUrl:
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path or "/"
    channel, aggregator = _channel(host, path)
    slug, external_id, kind = "", "", "other"
    if channel == "greenhouse":
        match = _GH_JOB.search(path)
        if match:
            slug, external_id, kind = match.group(1), match.group(2), "posting"
        else:
            kind = "board"
            slug = path.strip("/").split("/")[0]
    elif channel in {"lever", "jobgether"}:
        match = _LEVER_JOB.search(path)
        if match:
            slug, external_id, kind = match.group(1), match.group(2), "posting"
        else:
            kind = "board"
            slug = path.strip("/").split("/")[0]
    elif channel == "inhire":
        slug = host.split(".")[0]
        match = _INHIRE_JOB.search(path)
        if match:
            external_id, kind = match.group(1), "posting"
        else:
            kind = "board"
    elif channel == "ashby":
        match = _ASHBY_JOB.search(path)
        if match:
            slug, external_id, kind = match.group(1), match.group(2), "posting"
        else:
            kind = "board"
            slug = path.strip("/").split("/")[0] if path.strip("/") else ""
    elif _JOB_PATH.search(path):
        kind = "posting"
        if channel == "web":
            channel = "careers"
    elif _CAREER_ROOT.match(path.strip()) or (channel == "careers" and path.strip("/") == ""):
        kind = "career_page"
        if channel == "web":
            channel = "careers"
    return ClassifiedUrl(channel, kind, aggregator, slug, external_id)


def _channel(host: str, path: str) -> tuple[str, bool]:
    if any(needle in host for needle in ("linkedin.com", "indeed.", "glassdoor.")):
        return "aggregator", True
    if "jobgether" in host or path == "/jobgether" or path.startswith("/jobgether/"):
        return "jobgether", True
    if "greenhouse.io" in host:
        return "greenhouse", False
    if host.endswith("lever.co"):
        return "lever", False
    if "ashbyhq.com" in host:
        return "ashby", False
    if host.endswith("inhire.app"):
        return "inhire", False
    if "gupy.io" in host:
        return "gupy", False
    if "smartrecruiters.com" in host:
        return "smartrecruiters", False
    if "myworkdayjobs.com" in host or host.endswith("workday.com"):
        return "workday", False
    labels = host.split(".")
    if any(label in _CAREER_HOST for label in labels):
        return "careers", False
    return "web", False


def trusted_apply(url: str | None, company: str | None) -> bool:
    """The link is the employer's site or a board that employer runs.

    A page on another domain that only names the company is not a place to send someone.
    """
    if not url:
        return False
    classified = classify_url(url)
    if classified.aggregator:
        return False
    if classified.channel in _ATS_CHANNELS:
        return True
    return _employer_in_host(company, url)


def _employer_in_host(company: str | None, url: str) -> bool:
    from devjob.employment import _tokens

    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    labels = [part for part in host.split(".") if part and part not in _HOST_LABELS]
    blob = "".join(labels)
    tokens = _tokens(company)
    long = [token for token in tokens if len(token) >= 4]
    if long:
        return any(token in blob for token in long)
    return any(len(token) >= 2 and token in labels for token in tokens)
