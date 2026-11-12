import urllib.error

import pytest
from fixtures import FakeHttp, default_routes

from devjob.discovery import companies, detect, search, store
from devjob.discovery.models import CompanySource
from devjob.discovery.normalize import finalize
from devjob.providers import AccessDenied, ProviderUnavailable, SourceNotFound, get_provider
from devjob.providers.http import HttpClient
from devjob.providers.web import find_job_postings, job_from_posting, jobs_from_records


def _add_sources(ctx):
    companies.add_source(ctx.conn, CompanySource("greenhouse", "acmecloud", "Acme Cloud"))
    companies.add_source(ctx.conn, CompanySource("lever", "betaco", "BetaCo"))
    companies.add_source(ctx.conn, CompanySource("inhire", "gamatech", "Gama Tech"))


def test_greenhouse_normalization(http):
    jobs = get_provider("greenhouse", http).fetch_jobs(CompanySource("greenhouse", "acmecloud"))
    job = finalize(jobs[0], "2026-11-11T00:00:00+00:00")
    assert job.id == "greenhouse:acmecloud:1001"
    assert job.company == "Acme Cloud" and job.work_model == "remote"
    assert job.field_sources["work_model"] == "location_text"
    assert job.posted_at == "2026-10-01T10:00:00-03:00"
    assert job.requirements["required"] == ["Java", "Kafka", "PostgreSQL", "Spring Boot"]
    assert job.requirements["preferred"] == ["Go", "Kubernetes"]
    assert not job.has_salary, "Greenhouse não informou salário: nada é inventado"
    assert job.verification == "listed" and job.last_verified_at


def test_lever_normalization(http):
    jobs = get_provider("lever", http).fetch_jobs(CompanySource("lever", "betaco", "BetaCo"))
    job = finalize(jobs[0])
    assert (job.salary_min, job.salary_max, job.salary_currency, job.salary_period) == (19000, 24000, "BRL", "month")
    assert job.field_sources["salary"] == "lever:salaryRange"
    assert job.work_model == "remote" and job.contract_type == "clt"
    assert "criação" in job.field_sources["posted_at"], "createdAt não é apresentado como data de publicação"


def test_inhire_uses_documented_header(http):
    jobs = get_provider("inhire", http).fetch_jobs(CompanySource("inhire", "gamatech"))
    job = finalize(jobs[0])
    assert all(headers.get("X-Tenant") == "gamatech" for _, headers in http.calls)
    assert job.company == "Gama Tech" and job.contract_type == "pj" and job.work_model == "remote"
    assert job.url == "https://gamatech.inhire.app/vagas/9f0c-0001/pessoa-desenvolvedora-java-senior"
    assert job.requirements["required"] == ["Java", "Kafka", "Spring Boot"]


def test_search_dedupes_and_survives_provider_failure(ctx):
    _add_sources(ctx)
    companies.add_source(ctx.conn, CompanySource("greenhouse", "brokenco", "Broken"))
    companies.add_source(ctx.conn, CompanySource("lever", "goneco", "Gone"))
    ctx.http.routes["https://boards-api.greenhouse.io/v1/boards/brokenco/jobs?content=true"] = \
        ProviderUnavailable("boards-api.greenhouse.io: HTTP 503")
    ctx.http.routes["https://api.lever.co/v0/postings/goneco?mode=json&skip=0&limit=100"] = {
        "ok": False, "error": "Document not found"}
    from devjob.profile.model import Fact, Profile
    profile = Profile(hard_skills=[Fact("Java", "resume")])
    report = search.run_search(ctx.conn, ctx.http, profile, ctx.prefs(), ctx.config, refresh=True)
    assert report.sources_ok == 3 and report.sources_failed == 2
    assert {e["source"] for e in report.errors} == {"greenhouse:brokenco", "lever:goneco"}
    assert report.new == 7

    web = [{"title": "Senior Backend Engineer", "company": "Acme Cloud", "location": "Remote - Brazil",
            "url": "https://boards.greenhouse.io/acmecloud/jobs/1001?gh_jid=1001&utm_source=linkedin"},
           {"title": "Senior Java Engineer", "company": "BetaCo", "location": "Brazil",
            "url": "https://betaco.example/careers/senior-java-engineer"},
           {"title": "Platform Engineer", "company": "Delta", "url": "https://delta.example/jobs/42"}]
    jobs, errors = jobs_from_records(web + [{"title": "sem url"}])
    results = search.import_jobs(ctx.conn, jobs)
    outcomes = [o for _, o in results]
    assert outcomes == ["duplicate", "duplicate", "new"]
    assert results[0][0] == "greenhouse:acmecloud:1001"
    assert results[1][0] == "lever:betaco:aaaa-1111", "duplicata entre plataformas pela empresa + cargo"
    assert errors and "url" in errors[0]
    kept = store.get_job(ctx.conn, "greenhouse:acmecloud:1001")
    assert kept.verification == "listed", "dado não verificado não sobrescreve o verificado"
    assert store.get_job(ctx.conn, "https://betaco.example/careers/senior-java-engineer").external_id == "aaaa-1111"
    assert store.get_job(ctx.conn, "web:delta:" + jobs[2].external_id).verification == "unverified"


def test_description_is_opened_only_when_the_title_fits(ctx):
    _add_sources(ctx)
    from devjob.config.settings import deep_merge
    from devjob.profile import preferences
    from devjob.profile.model import Experience, Profile
    from fixtures import PREFERENCES

    preferences.save_preferences(ctx.paths.preferences, deep_merge(preferences.defaults(), PREFERENCES))
    profile = Profile(experiences=[Experience("Engenheira de Software Backend", "Acme", start="2020-01")])
    search.run_search(ctx.conn, ctx.http, profile, ctx.prefs(), ctx.config, refresh=True)
    urls = [url for url, _ in ctx.http.calls]
    assert not any("content=true" in url for url in urls)
    assert "https://boards-api.greenhouse.io/v1/boards/acmecloud/jobs/1001" in urls
    assert "https://boards-api.greenhouse.io/v1/boards/acmecloud/jobs/1002" not in urls
    assert "https://boards-api.greenhouse.io/v1/boards/acmecloud/jobs/1003" not in urls
    assert store.get_job(ctx.conn, "greenhouse:acmecloud:1002") is None
    assert store.get_job(ctx.conn, "greenhouse:acmecloud:1003") is None


def test_closed_jobs_are_marked_not_listed(ctx):
    _add_sources(ctx)
    from devjob.profile.model import Profile
    search.run_search(ctx.conn, ctx.http, Profile(), ctx.prefs(), ctx.config, refresh=True)
    ctx.http.routes["https://boards-api.greenhouse.io/v1/boards/acmecloud/jobs"] = {
        "jobs": [], "meta": {"total": 0}}
    report = search.run_search(ctx.conn, ctx.http, Profile(), ctx.prefs(), ctx.config, refresh=True)
    assert report.not_listed == 3
    assert store.get_job(ctx.conn, "greenhouse:acmecloud:1001").verification == "not_listed"


def test_cache_avoids_refetch(ctx):
    _add_sources(ctx)
    from devjob.profile.model import Profile
    search.run_search(ctx.conn, ctx.http, Profile(), ctx.prefs(), ctx.config)
    calls = len(ctx.http.calls)
    report = search.run_search(ctx.conn, ctx.http, Profile(), ctx.prefs(), ctx.config)
    assert len(ctx.http.calls) == calls and report.sources_cached == 3


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/acme/jobs/123?gh_jid=123", ("greenhouse", "acme", "", "123")),
    ("https://job-boards.greenhouse.io/embed/job_board?for=acme", ("greenhouse", "acme", "", None)),
    ("https://jobs.lever.co/beta/abc-123/apply", ("lever", "beta", "", "abc-123")),
    ("https://jobs.eu.lever.co/beta", ("lever", "beta", "eu", None)),
    ("https://gama.inhire.app/vagas/9f0c/dev-java", ("inhire", "gama", "", "9f0c")),
])
def test_detect_urls(url, expected):
    source, job_id = detect.parse_url(url)
    assert (source.provider, source.slug, source.region, job_id) == expected


def test_detect_unknown_url_and_scan_html():
    assert detect.parse_url("https://example.com/careers") is None
    html = ('<iframe src="https://job-boards.greenhouse.io/embed/job_board?for=acme"></iframe>'
            '<a href="https://jobs.lever.co/beta/1">x</a><a href="https://gama.inhire.app/vagas">y</a>')
    found = {(s.provider, s.slug) for s in detect.scan_html(html)}
    assert found == {("greenhouse", "acme"), ("lever", "beta"), ("inhire", "gama")}


def test_json_ld_job_posting():
    html = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
      "title":"Backend Engineer","hiringOrganization":{"name":"Omega"},"datePosted":"2026-10-10",
      "jobLocationType":"TELECOMMUTE","description":"<p>Requirements: Java</p>",
      "baseSalary":{"@type":"MonetaryAmount","currency":"BRL","value":{"minValue":15000,"maxValue":20000,"unitText":"MONTH"}}}
      </script>"""
    job = job_from_posting(find_job_postings(html)[0], "https://omega.example/jobs/1")
    assert (job.company, job.work_model, job.salary_currency, job.salary_period) == ("Omega", "remote", "BRL", "month")
    assert job.verification == "page_found" and job.posted_at == "2026-10-10"


class _Resp:
    def __init__(self, body: bytes):
        self.body = body

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_client_retries_and_never_bypasses_auth(monkeypatch):
    attempts = []

    def fake_urlopen(request, timeout):
        attempts.append(request.full_url)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {"Retry-After": "1"}, None)
        return _Resp(b'{"ok": true}')

    sleeps = []
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = HttpClient("test-agent", min_interval=0, max_retries=2, sleep=sleeps.append)
    assert client.get_json("https://api.example/x") == {"ok": True}
    assert len(attempts) == 3 and 1.0 in sleeps

    def denied(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", denied)
    with pytest.raises(AccessDenied):
        client.get_json("https://api.example/private")

    def missing(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "nf", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", missing)
    with pytest.raises(SourceNotFound):
        client.get_json("https://api.example/none")

    def offline(request, timeout):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr("urllib.request.urlopen", offline)
    with pytest.raises(ProviderUnavailable):
        client.get_json("https://api.example/offline")


def test_fake_http_unknown_route_is_not_found():
    with pytest.raises(SourceNotFound):
        FakeHttp(default_routes()).get_json("https://unknown.example")
