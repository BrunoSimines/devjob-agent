"""Search results are grouped into Markdown tables without changing match data."""

from devjob.discovery.models import Job
from devjob.discovery.render import order_for_display, render_results, split_findings
from devjob.discovery.search import RankedJob
from devjob.matching.candidate import MatchResult


def _job(title, company, url, **fields):
    data = dict(source="lever", external_id=title, title=title, company=company, url=url,
                location=None, work_model=None)
    data.update(fields)
    return Job(**data)


def _ranked(title, company, score, *, url="https://jobs.example/1", confidence=0.9, met=None, gaps=None,
            uncertain=None, also=None, **fields):
    match = MatchResult(job_id=title, score=score, confidence=confidence, recommendation="consider",
                        eliminated=False, met=met if met is not None else ["Java"],
                        gaps=gaps or [], uncertain=uncertain or [])
    return RankedJob(_job(title, company, url, **fields), match, also_locations=also or [])


def test_single_job_is_a_vertical_table():
    item = _ranked("Senior Auth Engineer", "Clara", 85.4, url="https://jobs.example/auth", confidence=0.6,
                   location=None, met=["IAM", "Java"], gaps=["Azure (obrigatório)", "Okta (desejável)"],
                   uncertain=["salário não informado pela vaga"])
    text = render_results([item])
    assert "## Clara" in text
    assert "| Informação | Vaga |" in text
    assert "[1. Senior Auth Engineer](https://jobs.example/auth)" in text
    assert "| Localização | Não informado |" in text
    assert "| Modelo | Não informado |" in text
    assert "| Salário | Não informado |" in text
    assert "| Contratação | Não informado |" in text
    assert "| Compatibilidade | 85.4% |" in text
    assert "| Confiança | 60% |" in text
    assert "| Requisitos atendidos | IAM, Java |" in text
    met, unmet, unverified = split_findings(item.match)
    assert unmet == "Azure"
    assert "Okta (desejável)" in unverified
    assert "salário não informado pela vaga" in unverified
    assert "Okta" not in text.split("Gaps ou competências não comprovadas")[1].split("\n", 1)[0]
    assert "Por quê" not in text
    assert not any(line.strip().startswith("http") for line in text.splitlines())


def test_several_jobs_at_one_company_each_get_a_vertical_table():
    low = _ranked("Staff Platform Engineer", "QuintoAndar", 56.4, url="https://jobs.example/staff",
                  location="Brasil", work_model="remote", contract_type="clt",
                  salary_min=18000, salary_max=22000, salary_currency="BRL", salary_period="month",
                  met=["Java", "Go"], gaps=["Kotlin (obrigatório)"])
    high = _ranked("Senior Software Engineer - IAM", "QuintoAndar", 90, url="https://jobs.example/iam",
                   location="Brasil", work_model="remote", met=["IAM", "Java"])
    text = render_results([low, high])
    assert text.count("| Informação | Vaga |") == 2
    assert "| Cargo | Localização | Modelo |" not in text
    assert text.index("1. Senior Software Engineer - IAM") < text.index("2. Staff Platform Engineer")
    assert "Remoto" in text and "CLT" in text and "BRL 18.000–22.000/mês" in text
    assert "[1. Senior Software Engineer - IAM](https://jobs.example/iam)" in text


def test_preferred_boards_come_before_a_higher_score_elsewhere():
    from devjob.discovery.search import rank

    prefs = {"sources": {"priority": ["inhire", "greenhouse"]}}
    greenhouse = _ranked("Senior Backend Engineer", "Acme", 60, url="https://jobs.example/gh", source="greenhouse")
    inhire = _ranked("Pessoa Desenvolvedora Java", "DB", 55, url="https://jobs.example/in", source="inhire")
    lever = _ranked("Senior Java Developer", "Jobgether", 90, url="https://jobs.example/lv", source="lever")
    ordered = rank([lever, greenhouse, inhire], prefs)
    assert [item.job.source for item in ordered] == ["greenhouse", "inhire", "lever"]
    text = render_results([lever, greenhouse, inhire], prefs)
    assert text.index("## Acme") < text.index("## Jobgether")
    assert text.index("## DB") < text.index("## Jobgether")


def test_mixed_focus_keeps_seventy_percent_at_home():
    from devjob.discovery.search import compose_results

    prefs = {"location": {"country": "BR", "city": "", "focus": "mixed", "home_share": 70}}
    home = [_ranked(f"Home {i}", "Acme", 50, url=f"https://acme.com/jobs/h{i}", location="Brazil") for i in range(10)]
    abroad = [_ranked(f"Away {i}", "Farcorp", 90, url=f"https://farcorp.com/jobs/a{i}", location="United States")
              for i in range(10)]
    chosen, _ = compose_results(abroad + home, prefs, 10)
    assert sum(1 for item in chosen if item.job.location == "Brazil") == 7
    assert sum(1 for item in chosen if item.job.location == "United States") == 3
    short, _ = compose_results(home[:2] + abroad, prefs, 10)
    assert len(short) == 10
    assert sum(1 for item in short if item.job.location == "Brazil") == 2
    prefs["location"]["focus"] = "home"
    only_home, _ = compose_results(home + abroad, prefs, 10)
    assert len(only_home) == 10
    assert {item.job.location for item in only_home} == {"Brazil"}
    weak = _ranked("Weak", "Acme", 40, url="https://acme.com/jobs/weak", location="Brazil")
    weak.match.recommendation = "not_recommended"
    certain, _ = compose_results(home[:1] + [weak], prefs, 10)
    assert [item.job.title for item in certain] == ["Home 0"]


def test_priority_companies_stay_in_the_list_beside_higher_scores():
    from devjob.discovery.search import compose_results

    prefs = {"location": {"country": "BR", "city": "", "focus": "home", "home_share": 70},
             "companies": {"priority": ["iFood"]}}
    others = [_ranked(f"Other {i}", "Acme", 90, url=f"https://acme.com/jobs/o{i}", location="Brazil") for i in range(8)]
    priority = _ranked("Senior Backend", "Conta at iFood", 40, url="https://carreiras.ifood.com.br/jobs/backend", location="Brazil")
    chosen, _ = compose_results(others + [priority], prefs, 4)
    assert len(chosen) == 4
    assert any(item.job.company == "Conta at iFood" for item in chosen)
    assert any(item.job.company == "Acme" for item in chosen)


def test_companies_follow_their_best_job_and_numbers_continue():
    beta = _ranked("Backend Engineer", "Beta", 70, url="https://jobs.example/beta")
    acme_low = _ranked("Java Engineer", "Acme", 40, url="https://jobs.example/acme-low")
    acme_high = _ranked("IAM Engineer | Auth", "Acme", 88, url="https://jobs.example/acme-high",
                        also=["France", "Ireland"])
    ordered = order_for_display([beta, acme_low, acme_high])
    assert [item.job.title for item in ordered] == ["IAM Engineer | Auth", "Java Engineer", "Backend Engineer"]
    text = render_results([beta, acme_low, acme_high])
    assert text.count("| Informação | Vaga |") == 3
    assert text.index("## Acme") < text.index("## Beta")
    assert "[1. IAM Engineer \\| Auth](https://jobs.example/acme-high)" in text
    assert "[2. Java Engineer](https://jobs.example/acme-low)" in text
    assert "[3. Backend Engineer](https://jobs.example/beta)" in text
    assert "também France, Ireland" in text
    assert "Por quê" not in text


def test_empty_results_say_nothing_was_found():
    assert "Nenhuma vaga" in render_results([])
