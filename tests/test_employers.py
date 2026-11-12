"""Employer exclusions and execution modes. Companies here are fictional."""

from pathlib import Path

import pytest

from devjob.config.settings import DEFAULT_CONFIG
from devjob.discovery.models import Job
from devjob.discovery.queries import plan_queries
from devjob.discovery.search import RankedJob, compose_results
from devjob.employment import (EmploymentError, add_previous, allow_past, confirm_current,
                               confirm_unemployed, exclusion_label, same_employer)
from devjob.matching.candidate import MatchResult, evaluate
from devjob.mode import UserModeError, current_mode, refuse_product_edit, set_mode
from devjob.profile.model import Profile
from devjob.profile.preferences import defaults, validate
from test_matching import CONFIG, make_job


def _employed():
    prefs = confirm_current(defaults(), "Empresa A", ["Empresa A S.A."])
    prefs = add_previous(prefs, "Empresa B")
    return add_previous(prefs, "Empresa C", ["Empresa C Ltda"])


def _visible(prefs, companies: list[str]) -> list[str]:
    kept = []
    for company in companies:
        if exclusion_label(company, prefs):
            continue
        job = make_job("Requirements:\n- Something", company=company, title="Specialist")
        result = evaluate(job, Profile(), prefs, CONFIG)
        if not result.eliminated:
            kept.append(company)
    return kept


def test_current_employer_never_appears_even_with_a_high_score():
    prefs = _employed()
    companies = ["Empresa A", "empresa a", "Empresa A S.A.", "EMPRESA-A", "Empresa A Ltda"]
    companies += [f"Outra {index}" for index in range(15)]
    assert len(companies) == 20
    visible = _visible(prefs, companies)
    assert len(visible) == 15
    assert all(not same_employer(company, "Empresa A") for company in visible)


def test_past_employers_are_excluded_by_default():
    prefs = _employed()
    visible = _visible(prefs, ["Empresa B", "Empresa C", "Empresa C Ltda", "Outra"])
    assert visible == ["Outra"]


def test_one_past_employer_can_be_allowed_back():
    prefs = allow_past(_employed(), "Empresa B")
    visible = _visible(prefs, ["Empresa A", "Empresa B", "Empresa C"])
    assert visible == ["Empresa B"]
    with pytest.raises(EmploymentError):
        allow_past(prefs, "Empresa A S.A.")


def test_changing_jobs_only_changes_data():
    prefs = confirm_current(_employed(), "Empresa D")
    assert exclusion_label("Empresa D", prefs).startswith("empregador atual")
    assert exclusion_label("Empresa A", prefs).startswith("ex-empregador")
    assert exclusion_label("Empresa B", prefs).startswith("ex-empregador")
    assert exclusion_label("Outra", prefs) is None
    turned_off = validate({**prefs, "employment": {**prefs["employment"], "exclude_current": False}})
    assert any("exclude_current" in problem for problem in turned_off)


def test_user_mode_is_the_default_and_a_search_does_not_edit_the_product(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVJOB_HOME", str(tmp_path / "home"))
    from devjob.config.settings import Paths, ensure_layout, resolve_home
    from devjob.cli import main

    paths = Paths(resolve_home())
    ensure_layout(paths)
    repo = Path(__file__).resolve().parents[1]
    watched = [repo / "src" / "devjob" / "cli.py", repo / "SKILL.md", Path(__file__)]
    before = {path: path.read_bytes() for path in watched}
    assert current_mode(paths) == "user"
    assert main(["mode"]) == 0
    assert main(["mode", "developer"]) == 1
    assert main(["employment", "confirm", "--unemployed"]) == 0
    main(["search"])
    with pytest.raises(UserModeError):
        refuse_product_edit(paths, repo / "src" / "devjob" / "employment.py")
    refuse_product_edit(paths, paths.home / "preferences.yaml")
    set_mode(paths, "developer", confirm=True)
    assert current_mode(paths) == "developer"
    set_mode(paths, "user")
    for path, content in before.items():
        assert path.read_bytes() == content


def test_three_professions_share_the_planner():
    for role, skill, spec in (
        ("Backend Engineer", "Java", "distributed systems"),
        ("Frontend Engineer", "React", "design systems"),
        ("Data Engineer", "Spark", "data modeling"),
    ):
        prefs = confirm_unemployed(defaults())
        prefs["target_roles"] = [role]
        prefs["primary_stack"] = [skill]
        prefs["specializations"] = [spec]
        texts = [query.text.lower() for query in plan_queries(Profile(), prefs, DEFAULT_CONFIG).queries]
        assert any(role.lower() in text for text in texts)
        assert any(skill.lower() in text for text in texts)
        assert any(spec in text for text in texts)
        foreign = {"backend engineer", "frontend engineer", "data engineer"} - {role.lower()}
        assert all(title not in text for text in texts for title in foreign)


def test_company_normalization_does_not_merge_different_organizations():
    assert same_employer("Acme Jobs", "AcmeJobs")
    assert same_employer("Empresa A", "Empresa A S.A.")
    assert not same_employer("Acme", "Acme Cloud")
    assert not same_employer("Empresa Alfa", "Empresa Beta")
    assert not same_employer("Nu", "Nu Pagamentos")
    prefs = confirm_current(defaults(), "Acme", ["Acme S.A."])
    assert exclusion_label("Acme S.A.", prefs)
    assert exclusion_label("Acme Cloud", prefs) is None


def test_excluded_employer_is_removed_before_the_list_is_shown():
    prefs = confirm_current(defaults(), "Empresa A")
    prefs["location"]["focus"] = "abroad"

    def ranked(company, score):
        slug = "empresaa" if company == "Empresa A" else "outra"
        job = Job("web", company, "Specialist", company, f"https://{slug}.com/jobs/1")
        match = MatchResult(job.id, score, 0.95, "recommended", False)
        return RankedJob(job, match)

    shown, _eliminated = compose_results(
        [ranked("Empresa A", 99), ranked("Outra", 70)], prefs, 10)
    assert [item.job.company for item in shown] == ["Outra"]
