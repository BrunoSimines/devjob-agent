"""Search orchestration: fetch -> normalize -> dedupe -> filter -> match -> rank."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from devjob import taxonomy
from devjob.discovery import companies, store
from devjob.discovery.models import CompanySource, Job
from devjob.discovery.normalize import finalize, seniority_from_title, work_model_from_text
from devjob.matching.candidate import (MatchResult, _CRAFT_TOKENS, _TITLE_FILLER, _countries_in,
                                       distinctive_tokens, evaluate, occupations, title_alignment,
                                       title_constraints)
from devjob.profile.model import Profile
from devjob.providers import ProviderError, get_provider
from devjob.storage.db import dumps, now_iso
from devjob.textutil import norm

log = logging.getLogger("devjob.search")

_ACTIVE_STATUSES = {"discovered", "shortlisted"}
_QUERY_STOPWORDS = {"de", "da", "do", "e", "com", "em", "para", "vaga", "vagas", "job", "jobs", "role", "roles",
                    "position", "positions", "acima", "above", "mil", "k", "r", "remunera", "salario", "salary",
                    "of", "and", "the", "for", "in", "a", "o", "as", "os", "remota", "remotas", "remoto", "remotos",
                    "remote", "hibrido", "hybrid", "presencial", "onsite"}


@dataclass
class RankedJob:
    job: Job
    match: MatchResult
    also_locations: list[str] = field(default_factory=list)


@dataclass
class SearchReport:
    search_id: int
    query: str | None
    sources_ok: int = 0
    sources_cached: int = 0
    sources_failed: int = 0
    errors: list[dict] = field(default_factory=list)
    scanned: int = 0
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    not_listed: int = 0
    considered: int = 0
    filtered_out: int = 0
    excluded_seen: int = 0
    collapsed: int = 0
    pruned: int = 0
    withheld: int = 0
    home_results: int = 0
    abroad_results: int = 0
    matched_companies: list[str] = field(default_factory=list)
    results: list[RankedJob] = field(default_factory=list)
    eliminated: list[RankedJob] = field(default_factory=list)
    ranked: list[RankedJob] = field(default_factory=list)


@dataclass
class ParsedQuery:
    terms: list[str]
    skills: list[str]
    seniority: str | None
    work_model: str | None


def parse_query(query: str | None) -> ParsedQuery:
    if not query:
        return ParsedQuery([], [], None, None)
    text = query.replace("back-end", "backend").replace("back end", "backend").replace("front-end", "frontend")
    skills = sorted(taxonomy.find_skills(text))
    seniority = seniority_from_title(text)
    model = work_model_from_text(text) or (
        "remote" if re.search(r"\bremot[oa]s?\b", text, re.IGNORECASE) else None)
    skill_tokens = {t for s in skills for t in norm(s).split()}
    level_words = {"senior", "sr", "junior", "jr", "pleno", "staff", "principal", "lead", "intern", "estagio", "mid"}
    terms = [t for t in norm(text).split()
             if t not in _QUERY_STOPWORDS and t not in skill_tokens and t not in level_words and not t.isdigit()]
    return ParsedQuery(terms, skills, seniority, model)


def _searchable(job: Job) -> set[str]:
    text = f"{job.title}\n{job.description}".replace("back-end", "backend").replace("Back-end", "backend")
    text = re.sub(r"back\s+end", "backend", text, flags=re.IGNORECASE)
    return set(norm(text).split())


def matches_query(job: Job, parsed: ParsedQuery) -> tuple[bool, str]:
    job_skills = set((job.requirements or {}).get("required", [])) | set(
        (job.requirements or {}).get("preferred", [])) | set((job.requirements or {}).get("mentioned", []))
    missing = [s for s in parsed.skills if s not in job_skills and s not in taxonomy.find_skills(job.title)]
    if missing:
        return False, f"não menciona {', '.join(missing)}"
    words = _searchable(job)
    absent = [t for t in parsed.terms if t not in words]
    if absent:
        return False, f"não contém '{' '.join(absent)}'"
    if parsed.seniority and job.seniority and job.seniority != parsed.seniority:
        return False, f"senioridade {job.seniority}"
    return True, ""


def _mentions_stack(job: Job, stack: list) -> bool:
    wanted = {taxonomy.canonical_skill(s) or s for s in stack}
    req = job.requirements or {}
    found = set(req.get("required", [])) | set(req.get("preferred", [])) | set(req.get("mentioned", []))
    found |= set(taxonomy.find_skills(job.title))
    return bool(wanted & found)


def specialization_in_title(title: str, specializations: list) -> bool:
    """True when the title itself names a configured specialization, not only the description."""
    low = f" {norm(title)} "
    for spec in specializations:
        phrase = norm(spec)
        if phrase and f" {phrase} " in low:
            return True
        canonical = taxonomy.canonical_skill(spec)
        if canonical and canonical in taxonomy.find_skills(title):
            return True
    return False


def _person_titles(profile: Profile, prefs: dict) -> list[str]:
    """Roles the person is aiming at, plus the titles they have actually held."""
    titles = [str(role) for role in (prefs.get("target_roles") or []) if str(role).strip()]
    titles += [exp.title for exp in profile.confirmed_experiences() if exp.title]
    return titles


def _specialty_tokens(specs: list[str]) -> set[str]:
    """Words that mean one of the person's specializations, including short title aliases."""
    tokens: set[str] = set()
    for spec in specs:
        canonical = taxonomy.canonical_skill(spec) or spec
        tokens.add(norm(canonical))
        tokens.update(part for part in norm(canonical).split() if len(part) > 1)
        skill = taxonomy._by_name().get(canonical)
        if skill:
            for alias in skill.aliases:
                tokens.update(part for part in norm(alias).split() if len(part) > 3)
    return tokens


def _specific_specializations(specs: list[str]) -> list[str]:
    """Drop specializations that only repeat the craft, such as Backend or Software."""
    craft = _CRAFT_TOKENS | _TITLE_FILLER | {"backend", "frontend", "fullstack", "mobile", "web"}
    specific = []
    for spec in specs:
        parts = {part for part in norm(spec).split() if len(part) > 1}
        if parts and parts <= craft:
            continue
        specific.append(spec)
    return specific


def _person_signals(profile: Profile, prefs: dict, titles: list[str]) -> set[str]:
    """Specialty words from the person's roles, experiences, stack and specializations."""
    signals: set[str] = set()
    for title in titles:
        signals |= distinctive_tokens(title)
    values = list(prefs.get("primary_stack") or []) + list(prefs.get("specializations") or [])
    values += [fact.value for fact in profile.specializations if fact.confirmed]
    for exp in profile.confirmed_experiences():
        values += list(exp.technologies)
    for value in values:
        canonical = taxonomy.canonical_skill(value) or value
        signals.add(norm(canonical))
        signals.update(token for token in norm(canonical).split() if len(token) > 1)
        skill = taxonomy._by_name().get(canonical)
        if skill:
            for alias in (*skill.aliases, *skill.case_sensitive):
                signals.update(token for token in norm(alias).split() if len(token) > 1)
    return signals


def _is_relevant(job: Job, profile: Profile, prefs: dict) -> bool:
    """Keep jobs of the person's profession. A shared skill or specialty word is not enough.

    A title from another profession stays out even when it mentions one of the person's
    skills. The same rule keeps a non-engineering search on that person's own roles.
    """
    titles = _person_titles(profile, prefs)
    if not titles:
        req = job.requirements or {}
        job_skills = set(req.get("required", [])) | set(req.get("preferred", [])) | set(req.get("mentioned", []))
        return bool(job_skills & profile.confirmed_hard_skills())
    person_occ: set[str] = set()
    for title in titles:
        person_occ |= occupations(title)
    job_occ = occupations(job.title)
    if job_occ - person_occ:
        return False
    specs = list(prefs.get("specializations") or [])
    specs += [fact.value for fact in profile.specializations if fact.confirmed]
    allowed = _person_signals(profile, prefs, titles) | _specialty_tokens(specs)
    job_signals = title_constraints(job.title, job.company)
    if job_signals and not job_signals <= allowed:
        return False
    if specialization_in_title(job.title, _specific_specializations(specs)) and job_occ & person_occ:
        return True
    align = title_alignment(job.title, titles) or 0
    stack = prefs.get("primary_stack") or []
    if stack:
        return align >= 0.5 and _mentions_stack(job, stack)
    return align >= 1


def _spec_priority(job: Job, prefs: dict) -> int:
    specs = prefs.get("specializations") or []
    if not specs:
        return 0
    if specialization_in_title(job.title, specs):
        return 2
    body = taxonomy.find_skills(job.description or "")
    for spec in specs:
        canonical = taxonomy.canonical_skill(spec)
        if canonical and canonical in body:
            return 1
        phrase = norm(spec)
        if phrase and f" {phrase} " in f" {norm(job.description)} ":
            return 1
    return 0


_TRACKS = {"backend", "frontend", "fullstack", "mobile"}


def _worth_reading(job: Job, profile: Profile, prefs: dict) -> bool:
    """Open the description only when the title is this person's craft.

    The language may live only in the description, so a plain Backend Engineer is
    opened. A product, sales or analyst title is not, and neither is a title that
    already names a stack the person does not have.
    """
    titles = _person_titles(profile, prefs)
    if not titles:
        return True
    person_occ: set[str] = set()
    for title in titles:
        person_occ |= occupations(title)
    job_occ = occupations(job.title)
    if job_occ - person_occ or "build" not in job_occ or "build" not in person_occ:
        return False
    specs = list(prefs.get("specializations") or [])
    specs += [fact.value for fact in profile.specializations if fact.confirmed]
    allowed = _person_signals(profile, prefs, titles) | _specialty_tokens(specs)
    tracks = _TRACKS & allowed
    job_tracks = set()
    for token in title_constraints(job.title, job.company):
        if token in _TRACKS:
            job_tracks.add(token)
        if token not in allowed and taxonomy.canonical_skill(token):
            return False
    return not tracks or not job_tracks or bool(tracks & job_tracks)


def _fresh(source: CompanySource, ttl_hours: float) -> bool:
    if not source.last_fetched_at or source.last_status != "ok":
        return False
    fetched = datetime.fromisoformat(source.last_fetched_at)
    return datetime.now(timezone.utc) - fetched < timedelta(hours=ttl_hours)


def refresh_sources(conn: sqlite3.Connection, http, sources: list[CompanySource], report: SearchReport,
                    ttl_hours: float, refresh: bool, profile: Profile, prefs: dict) -> None:
    """Read each board. Only postings of this person's profession are stored."""
    narrow = bool(_person_titles(profile, prefs))
    for source in sources:
        if not refresh and _fresh(source, ttl_hours):
            report.sources_cached += 1
            continue
        label = f"{source.provider}:{source.slug}"
        try:
            provider = get_provider(source.provider, http)
            listings = getattr(provider, "fetch_listings", None)
            jobs = listings(source) if listings else provider.fetch_jobs(source)
            titles_only = listings is not None
        except ProviderError as exc:
            report.sources_failed += 1
            report.errors.append({"source": label, "error": str(exc), "type": type(exc).__name__})
            companies.record_fetch(conn, source, "error", str(exc))
            log.warning("falha ao consultar %s: %s", label, exc)
            continue
        now = now_iso()
        seen: set[str] = set()
        for job in jobs:
            finalize(job, now)
            seen.add(job.id)
            report.scanned += 1
            if titles_only and not (job.description or "").strip():
                if narrow and not _worth_reading(job, profile, prefs):
                    report.filtered_out += 1
                    continue
                try:
                    full = provider.fetch_job(source, job.external_id)
                except ProviderError as exc:
                    log.warning("falha ao abrir %s %s: %s", label, job.external_id, exc)
                    continue
                if full is None:
                    seen.discard(job.id)
                    continue
                job = finalize(full, now)
            report.fetched += 1
            if narrow and not _is_relevant(job, profile, prefs):
                report.filtered_out += 1
                continue
            job_id, outcome = store.upsert_job(conn, job, report.search_id)
            report.new += outcome == "new"
            report.duplicates += outcome == "duplicate"
        report.not_listed += store.mark_not_listed(conn, source.provider, source.slug, seen)
        report.sources_ok += 1
        companies.record_fetch(conn, source, "ok", None, jobs[0].company if jobs else None)


def save_match(conn: sqlite3.Connection, job_id: str, result: MatchResult) -> None:
    with conn:
        conn.execute("INSERT INTO match_results (job_id, profile_version, score, confidence, recommendation, "
                     "eliminated, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (job_id, result.profile_version, result.score, result.confidence, result.recommendation,
                      int(result.eliminated), dumps(result.to_dict()), now_iso()))


_ORDER = {"recommended": 0, "consider": 1, "insufficient_data": 2, "not_recommended": 3, "eliminated": 4}
# The list shows only matches the score can stand behind. Weak and incomplete fits stay out.
_SHOWN = {"recommended", "consider"}


def source_tier(job: Job, prefs: dict | None) -> int:
    """0 when the posting's board is one the user asked to see first."""
    priority = [str(item).lower() for item in ((prefs or {}).get("sources") or {}).get("priority") or []]
    if not priority:
        return 0
    return 0 if (job.source or "").lower() in priority else 1


def rank(results: list[RankedJob], prefs: dict | None = None) -> list[RankedJob]:
    """Preferred boards come first. Inside a board, recommendation then score x confidence."""
    prefs = prefs or {}
    return sorted(results, key=lambda r: (source_tier(r.job, prefs),
                                          _ORDER[r.match.recommendation],
                                          -((r.match.score or 0) * r.match.confidence),
                                          -_spec_priority(r.job, prefs),
                                          -(r.match.score or 0)))


def job_is_home(job: Job, prefs: dict) -> bool:
    """True when the posting names the person's country. A bare Remote does not."""
    loc = prefs.get("location") or {}
    country = str(loc.get("country") or "").upper()
    if not country:
        return True
    countries = _countries_in(job.location)
    city = set(norm(loc.get("city")).split())
    if city and city <= set(norm(job.location).split()):
        countries = set(countries)
        countries.add(country)
    return country in countries


def _is_aggregator(item: RankedJob) -> bool:
    from devjob.discovery.classify import classify_url

    return classify_url(item.job.url).channel == "jobgether"


def _priority_names(prefs: dict) -> list[str]:
    return [str(name).strip() for name in ((prefs.get("companies") or {}).get("priority") or []) if str(name).strip()]


def _split_priority(items: list[RankedJob], prefs: dict) -> tuple[list[RankedJob], list[RankedJob]]:
    from devjob.discovery.pipeline import mentions_company

    names = _priority_names(prefs)
    if not names:
        return [], list(items)
    priority: list[RankedJob] = []
    others: list[RankedJob] = []
    for item in items:
        if any(mentions_company(name, item) for name in names):
            priority.append(item)
        else:
            others.append(item)
    return priority, others


def _merge(priority: list[RankedJob], others: list[RankedJob], count: int) -> list[RankedJob]:
    """Alternate preference companies with the rest. A short side is filled from the other."""
    if count <= 0:
        return []
    merged: list[RankedJob] = []
    left = right = 0
    turn = 0
    while len(merged) < count and (left < len(priority) or right < len(others)):
        if turn == 0 and left < len(priority):
            merged.append(priority[left])
            left += 1
        elif right < len(others):
            merged.append(others[right])
            right += 1
        elif left < len(priority):
            merged.append(priority[left])
            left += 1
        turn = 1 - turn
    return merged


def _append_merge(chosen: list[RankedJob], pool: list[RankedJob], prefs: dict, limit: int) -> list[RankedJob]:
    """Fill empty slots from jobs that already passed, still alternating preference companies."""
    if len(chosen) >= limit:
        return chosen
    seen = {id(item) for item in chosen}
    priority, others = _split_priority([item for item in pool if id(item) not in seen], prefs)
    return list(chosen) + _merge(priority, others, limit - len(chosen))


def limit_source_share(chosen: list[RankedJob], max_share: float) -> list[RankedJob]:
    """Keep an aggregator from occupying the list when other sources already produced jobs.

    Extra aggregator rows are dropped. Nothing is invented to fill the gap.
    """
    if not chosen or not isinstance(max_share, (int, float)) or isinstance(max_share, bool):
        return chosen
    if max_share >= 1 or max_share <= 0:
        return chosen
    others = [item for item in chosen if not _is_aggregator(item)]
    if not others or all(not _is_aggregator(item) for item in chosen):
        return chosen
    allowed = int(max_share * len(others) / (1 - max_share) + 1e-9)
    kept: list[RankedJob] = []
    used = 0
    for item in chosen:
        if _is_aggregator(item):
            if used >= allowed:
                continue
            used += 1
        kept.append(item)
    return kept


def compose_results(ordered: list[RankedJob], prefs: dict, limit: int,
                    max_source_share: float = 1) -> tuple[list[RankedJob], list[RankedJob]]:
    """Pick the list. Preference companies are alternated with the others. mixed keeps the country share, then fills empty slots."""
    eliminated = [item for item in ordered if item.match.eliminated]
    from devjob.employment import exclusion_label
    from devjob.discovery.classify import trusted_apply
    kept = [item for item in ordered if item.match.recommendation in _SHOWN
            and not exclusion_label(item.job.company, prefs)
            and trusted_apply(item.job.url, item.job.company)]
    focus = str((prefs.get("location") or {}).get("focus") or "mixed").lower()
    if focus == "home":
        pool = [item for item in kept if job_is_home(item.job, prefs)]
        chosen = _merge(*_split_priority(pool, prefs), limit)
    elif focus == "abroad":
        pool = kept
        chosen = _merge(*_split_priority(pool, prefs), limit)
    else:
        share = (prefs.get("location") or {}).get("home_share")
        share = 70 if not isinstance(share, (int, float)) or isinstance(share, bool) else min(100, max(0, int(share)))
        home_slots = round(limit * share / 100)
        abroad_slots = limit - home_slots
        home = [item for item in kept if job_is_home(item.job, prefs)]
        abroad = [item for item in kept if not job_is_home(item.job, prefs)]
        chosen = _merge(*_split_priority(home, prefs), home_slots) + _merge(*_split_priority(abroad, prefs), abroad_slots)
        pool = kept
    chosen = _append_merge(chosen, pool, prefs, limit)
    chosen = limit_source_share(chosen, max_source_share)
    chosen = _append_merge(chosen, [item for item in pool if not _is_aggregator(item)], prefs, limit)
    return chosen, eliminated


def collapse_postings(results: list[RankedJob], prefs: dict | None = None) -> tuple[list[RankedJob], int]:
    """Keep one posting per title and company. Country copies stay as other locations."""
    prefs = prefs or {}
    country = str((prefs.get("location") or {}).get("country") or "").upper()
    groups: dict[tuple[str, str], list[RankedJob]] = {}
    for item in results:
        groups.setdefault((norm(item.job.title), norm(item.job.company)), []).append(item)
    chosen: list[RankedJob] = []
    hidden = 0
    for items in groups.values():
        def sort_key(item: RankedJob, home: str = country) -> tuple:
            here = 0 if home and home in _countries_in(item.job.location) else 1
            score = (item.match.score or 0) * item.match.confidence
            return (here, _ORDER[item.match.recommendation], -score)

        items.sort(key=sort_key)
        best = items[0]
        best.also_locations = []
        seen = {best.job.location}
        for other in items[1:]:
            if other.job.location and other.job.location not in seen:
                best.also_locations.append(other.job.location)
                seen.add(other.job.location)
        hidden += len(items) - 1
        chosen.append(best)
    return chosen, hidden


def run_search(conn: sqlite3.Connection, http, profile: Profile, prefs: dict, config: dict, *,
               query: str | None = None, limit: int | None = None, refresh: bool = False,
               providers: list[str] | None = None, company_slugs: list[str] | None = None,
               include_seen: bool = False, profile_version: int | None = None) -> SearchReport:
    if limit is None:
        configured = config["search"]["default_limit"]
        limit = 20 if not isinstance(configured, int) or isinstance(configured, bool) else min(int(configured), 20)
    parsed = parse_query(query)
    filters = {"providers": providers, "companies": company_slugs, "limit": limit, "refresh": refresh,
               "parsed_query": parsed.__dict__}
    with conn:
        cur = conn.execute("INSERT INTO searches (query, filters_json, started_at) VALUES (?, ?, ?)",
                           (query, dumps(filters), now_iso()))
    report = SearchReport(search_id=cur.lastrowid, query=query)

    sources = [s for s in companies.list_sources(conn)
               if (not providers or s.provider in providers) and (not company_slugs or s.slug in company_slugs)]
    refresh_sources(conn, http, sources, report, config["search"]["cache_ttl_hours"], refresh, profile, prefs)

    selected_slugs = {(s.provider, s.slug) for s in sources}
    if _person_titles(profile, prefs):
        stale = [store.stored_id(job) for job in store.list_jobs(conn)
                 if ((job.source, job.company_slug) in selected_slugs or (job.source == "web" and not providers))
                 and job.verification != "not_listed" and job.status in _ACTIVE_STATUSES
                 and not _is_relevant(job, profile, prefs)]
        report.pruned = store.discard_discovered(conn, stale)
    candidates = [j for j in store.list_jobs(conn)
                  if (j.source, j.company_slug) in selected_slugs or (j.source == "web" and not providers)]
    ranked: list[RankedJob] = []
    for job in candidates:
        if job.verification == "not_listed":
            continue
        if not include_seen and job.status not in _ACTIVE_STATUSES:
            report.excluded_seen += 1
            continue
        ok, _ = matches_query(job, parsed)
        if not ok or not _is_relevant(job, profile, prefs):
            report.filtered_out += 1
            continue
        if parsed.work_model and job.work_model and job.work_model != parsed.work_model:
            report.filtered_out += 1
            continue
        report.considered += 1
        result = evaluate(job, profile, prefs, config, profile_version)
        save_match(conn, store.stored_id(job), result)
        ranked.append(RankedJob(job, result))

    unique, report.collapsed = collapse_postings(ranked, prefs)
    ordered = rank(unique, prefs)
    report.ranked = ordered
    report.matched_companies = sorted({norm(item.job.company) for item in ordered if not item.match.eliminated})
    report.withheld = sum(1 for item in ordered
                          if not item.match.eliminated and item.match.recommendation not in _SHOWN)
    share = ((config.get("search") or {}).get("discovery") or {}).get("max_source_share", 0.4)
    report.results, report.eliminated = compose_results(ordered, prefs, limit, share)
    report.home_results = sum(1 for item in report.results if job_is_home(item.job, prefs))
    report.abroad_results = len(report.results) - report.home_results
    with conn:
        conn.execute("UPDATE searches SET finished_at = ?, sources_ok = ?, sources_failed = ?, jobs_fetched = ?, "
                     "jobs_new = ?, duplicates = ?, errors_json = ? WHERE id = ?",
                     (now_iso(), report.sources_ok + report.sources_cached, report.sources_failed, report.fetched,
                      report.new, report.duplicates, dumps(report.errors), report.search_id))
    return report


def import_jobs(conn: sqlite3.Connection, jobs: list[Job]) -> list[tuple[str, str]]:
    now = now_iso()
    return [store.upsert_job(conn, finalize(job, now)) for job in jobs]
