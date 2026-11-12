"""Web discovery is planned by the program and executed by the host, not by a private API."""

import inspect

from devjob.config.settings import DEFAULT_CONFIG
from devjob.discovery import pipeline, queries
from devjob.discovery.brave import brave_configured, provider_status, request_urls
from devjob.discovery.classify import classify_url
from devjob.discovery.models import Job
from devjob.discovery.search import RankedJob, compose_results
from devjob.matching.candidate import MatchResult
from devjob.profile.model import Experience, Fact, Profile
from devjob.profile.preferences import defaults
from devjob.providers.base import ProviderUnavailable


def _prefs():
    prefs = defaults()
    prefs["target_roles"] = ["Senior Software Engineer"]
    prefs["seniority"] = {"levels": ["senior", "staff"], "eliminatory": False}
    prefs["primary_stack"] = ["Java"]
    prefs["specializations"] = ["IAM"]
    prefs["location"] = {**prefs["location"], "country": "BR", "focus": "mixed", "home_share": 70}
    prefs["work_model"] = {"accepted": ["remote"], "eliminatory": True}
    prefs["contract_types"] = {"accepted": ["clt", "pj", "international"], "eliminatory": False}
    prefs["companies"] = {"desired": [], "blocked": ["Acme Pagamentos"], "priority": ["iFood", "Mercado Livre"]}
    return prefs


def _profile():
    return Profile(
        experiences=[Experience("Engenheira de Software Backend", "Acme Pagamentos", source="resume")],
        specializations=[Fact("IAM", "user")],
    )


def _ranked(url, company, title, number):
    job = Job("web", str(number), title, company, url)
    match = MatchResult(job.id, 80, 0.9, "recommended", False)
    return RankedJob(job, match)


def test_a_repost_is_not_a_place_to_apply():
    from devjob.discovery.classify import trusted_apply

    assert trusted_apply("https://job-boards.greenhouse.io/ifoodcarreiras/jobs/1", "iFood")
    assert trusted_apply("https://carreiras.ifood.com.br/job/backend", "iFood")
    assert trusted_apply("https://jobs.ashbyhq.com/nubank/302f1e7c-6e2d-40f3-bf15-6dc60eb74b69", "Nubank")
    assert not trusted_apply("https://alion.io/job/picpay-desenvolvedor-backend", "PicPay")
    assert not trusted_apply("https://eu.dev.br/vagas/picpay-backend", "Conta Global at PicPay")
    assert not trusted_apply("https://jobs.lever.co/jobgether/7929b65b-ea7e-4531-b739-447f7d0d4c28", "PicPay")
    ashby = classify_url("https://jobs.ashbyhq.com/nubank/302f1e7c-6e2d-40f3-bf15-6dc60eb74b69")
    assert ashby.kind == "posting" and ashby.slug == "nubank"


def test_plan_expands_roles_without_centering_an_aggregator():
    plan = queries.plan_queries(_profile(), _prefs(), DEFAULT_CONFIG)
    texts = [query.text.lower() for query in plan.queries]
    strategies = {query.strategy for query in plan.queries}
    assert 1 < len(plan.queries) <= plan.budget
    assert strategies >= {"role", "stack", "specialization", "company"}
    assert any(query.language == "pt" for query in plan.queries)
    assert any(query.language == "en" for query in plan.queries)
    assert any("senior software engineer" in text for text in texts)
    assert any("java" in text for text in texts)
    assert any(text.strip() == "iam" for text in texts)
    assert all("platform engineer" not in text for text in texts)
    assert all("identity engineer" not in text for text in texts)
    assert any(query.company == "iFood" for query in plan.queries)
    assert all("jobgether" not in text for text in texts)
    assert all("acme pagamentos" not in text for text in texts)
    assert "jobgether" not in defaults()["sources"]["priority"]


def test_native_search_is_free_and_optional_brave_is_not_called(http):
    status = provider_status(DEFAULT_CONFIG)
    assert status["mode"] == "native" and status["paid_api_required"] is False
    assert brave_configured(DEFAULT_CONFIG) is False
    pages = request_urls("backend engineer", {**DEFAULT_CONFIG, "search": {"discovery": {"max_pages": 2,
                                                                                        "max_results_per_query": 10}}})
    assert len(pages) == 2 and all("offset=" in url for url in pages)
    assert http.calls == []


def test_discovery_accepts_career_sites_and_ignores_matching(ctx):
    payload = {"queries": [
        {"id": "q1", "text": "\"iFood\" careers jobs", "strategy": "company", "company": "iFood",
         "status": "completed", "results": [
             {"title": "Senior Backend Engineer - iFood", "url": "https://carreiras.ifood.com.br/job/backend-senior",
              "snippet": "Backend role."},
             {"title": "Carreiras", "url": "https://carreiras.ifood.com.br/"},
         ]},
        {"id": "q2", "text": "backend engineer", "strategy": "role", "status": "completed", "results": [
            {"title": "Backend Engineer - Mercado Livre",
             "url": "https://mercadolivre.gupy.io/job/engenharia-backend", "snippet": "Sem salário informado."},
        ]},
    ]}
    summary = pipeline.run_discovery(ctx.conn, ctx.http, payload, _prefs(), ctx.config)
    assert summary["unique_postings"] == 2
    assert summary["source_count"] >= 2
    assert any(item["channel"] == "careers" for item in summary["career_pages"])
    stored = [row["url"] for row in ctx.conn.execute("SELECT url FROM jobs")]
    assert any("ifood.com.br" in url for url in stored)
    assert any("gupy.io" in url for url in stored)
    assert ctx.conn.execute("SELECT COUNT(*) FROM match_results").fetchone()[0] == 0
    assert "evaluate(" not in inspect.getsource(pipeline)
    assert all("brave" not in url and "google." not in url for url, _headers in ctx.http.calls)
    job = next(row for row in ctx.conn.execute("SELECT * FROM jobs") if "gupy.io" in row["url"])
    assert job["salary_min"] is None and job["contract_type"] is None


def test_repost_is_a_clue_until_the_company_page_is_found(ctx):
    official = "https://carreiras.ifood.com.br/job/backend-senior"
    title = "Senior Backend Engineer - iFood"
    first = pipeline.run_discovery(ctx.conn, None, {"queries": [
        {"text": "backend", "status": "completed", "company": "iFood",
         "results": [{"title": title, "url": "https://jobs.lever.co/jobgether/7929b65b-ea7e-4531-b739-447f7d0d4c28"}]},
    ]}, _prefs(), ctx.config)
    assert ctx.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert first["reposts"] == [{"company": "iFood", "title": "Senior Backend Engineer"}]
    assert "jobgether" not in str(first["reposts"])
    summary = pipeline.run_discovery(ctx.conn, None, {"queries": [
        {"text": "backend", "status": "completed", "results": [{"title": title, "url": official}]},
    ]}, _prefs(), ctx.config)
    assert summary["unique_postings"] == 1
    assert summary["reposts"] == []
    kept = ctx.conn.execute("SELECT url FROM jobs").fetchone()["url"]
    assert kept == official


def test_one_source_failing_does_not_stop_the_others(ctx):
    ctx.http.routes["https://boards-api.greenhouse.io/v1/boards/brokenboard/jobs/555"] = ProviderUnavailable(
        "boards-api.greenhouse.io: HTTP 503")
    summary = pipeline.run_discovery(ctx.conn, ctx.http, {"queries": [
        {"text": "\"Nuvem\" careers", "company": "Nuvem", "status": "failed", "error": "tempo esgotado",
         "results": []},
        {"text": "\"iFood\" careers jobs", "company": "iFood", "status": "completed", "results": [
            {"title": "Senior Backend Engineer - iFood", "url": "https://carreiras.ifood.com.br/job/backend-senior"},
        ]},
        {"text": "backend", "status": "completed", "results": [
            {"title": "Backend Engineer - Oficina", "url": "https://job-boards.greenhouse.io/brokenboard/jobs/555"},
        ]},
    ]}, _prefs(), ctx.config)
    assert summary["company_status"]["Nuvem"] == "inaccessible"
    assert summary["company_status"]["iFood"] == "found"
    assert summary["company_status"]["Mercado Livre"] == "incomplete"
    urls = [row["url"] for row in ctx.conn.execute("SELECT url FROM jobs")]
    assert any("ifood.com.br" in url for url in urls)
    assert any("brokenboard" in url for url in urls)
    assert summary["failures"]


def test_empty_search_is_not_reported_as_a_failure():
    status = pipeline._company_status([{"status": "completed", "results": []}], found=False)
    failed = pipeline._company_status([{"status": "failed", "error": "rede"}], found=False)
    assert status == "not_found" and failed == "inaccessible"
    text = pipeline.format_diagnosis({
        "queries_run": 2, "raw_results": 0, "unique_postings": 0, "verified": 0,
        "source_count": 0, "failures": [{"query": "vagas Nuvem", "error": "tempo esgotado"}],
        "company_status": {"Nuvem": "inaccessible", "iFood": "not_found"},
    })
    assert "nenhuma oportunidade encontrada" in text
    assert "fonte inacessível" in text
    assert "tempo esgotado" in text
    assert "ausência de pesquisa" in pipeline.format_diagnosis(None)


def test_discarded_by_the_candidate_is_not_an_empty_board():
    outcomes = pipeline.with_filter_outcomes({"iFood": "found", "Nuvem": "not_found"}, matched_companies=set())
    assert outcomes["iFood"] == "discarded"
    assert outcomes["Nuvem"] == "not_found"


def test_priority_report_follows_the_jobs():
    from devjob.discovery.pipeline import format_priority_report

    listed = _ranked("https://job-boards.greenhouse.io/ifoodcarreiras/jobs/1", "iFood", "Senior Backend", 1)
    outside = _ranked("https://picpay.com/carreiras/backend", "Conta Global at PicPay", "Backend Senior", 2)
    discarded = _ranked("https://example.com/meli", "Platform Services at Mercado Livre", "Backend", 3)
    discarded.match.eliminated = True
    discarded.match.eliminations = ["modelo de trabalho 'hybrid' não aceito (eliminatório)"]
    libre = _ranked("https://careers.mercadolibre.com/job/genai", "GenAI Gateway at Mercado Libre", "Backend", 4)
    repost = _ranked("https://alion.io/job/picpay-backend", "PicPay", "Outro anúncio", 5)
    libre.match.eliminated = True
    libre.match.eliminations = ["modelo de trabalho 'hybrid' não aceito (eliminatório)"]
    prefs = {"companies": {"priority": ["iFood", "Mercado Livre", "PicPay", "Nubank"]}}
    text = format_priority_report(
        prefs, [listed], [listed, outside, discarded, libre, repost],
        {"iFood": "not_found", "Mercado Livre": "not_found", "Nubank": "not_found", "PicPay": "discarded"})
    assert "iFood: 1 na lista (1. Senior Backend)." in text
    assert "nenhuma oportunidade encontrada" not in text.split("iFood")[1].split("\n")[0]
    assert "Mercado Livre: 2 descartadas" in text
    assert "hybrid" in text
    assert "Mercado Libre" not in text
    assert "PicPay: 1 encontrada, fora da lista (Backend Senior). 1 anúncio em outro site, não incluído: o link não é o da empresa." in text
    assert "alion.io" not in text
    assert "Nubank: nenhuma oportunidade encontrada." in text


def test_jobgether_does_not_dominate_the_list_when_other_sources_exist():
    chosen = []
    for number in range(8):
        chosen.append(_ranked(f"https://jobs.lever.co/jobgether/{number:08x}-aaaa-bbbb-cccc-ddddeeee{number:04d}",
                              "Agregador", f"Backend Engineer {number}", number))
    chosen.append(_ranked("https://carreiras.ifood.com.br/job/backend-senior", "iFood", "Backend Engineer", 20))
    chosen.append(_ranked("https://careers.mercadolivre.com.br/job/platform", "Mercado Livre", "Platform Engineer", 21))
    prefs = defaults()
    prefs["location"]["focus"] = "abroad"
    shown, _eliminated = compose_results(chosen, prefs, 10, max_source_share=0.4)
    assert not any("jobgether" in item.job.url for item in shown)
    assert {item.job.company for item in shown} == {"iFood", "Mercado Livre"}


def test_same_posting_is_not_stored_twice(ctx):
    payload = {"queries": [{"text": "\"iFood\" careers jobs", "company": "iFood", "status": "completed",
                           "results": [{"title": "Backend Engineer - iFood",
                                        "url": "https://carreiras.ifood.com.br/job/backend-senior"}]}]}
    first = pipeline.run_discovery(ctx.conn, None, payload, _prefs(), ctx.config)
    second = pipeline.run_discovery(ctx.conn, None, payload, _prefs(), ctx.config)
    assert first["stored"][0]["outcome"] == "new"
    assert second["stored"][0]["outcome"] in {"duplicate", "unchanged"}
    assert ctx.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    plan = queries.plan_queries(_profile(), _prefs(), ctx.config, conn=ctx.conn)
    assert any(query.cached and "ifood" in query.text.lower() for query in plan.queries)
