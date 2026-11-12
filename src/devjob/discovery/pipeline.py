"""Discovery pipeline: discover, fetch, normalize, dedupe, verify.

Matching and presentation happen later, in the search command. A missing salary,
contract or requirement never drops a posting here.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from urllib.parse import urlsplit

from devjob.discovery.classify import classify_url
from devjob.discovery.models import CompanySource, Job
from devjob.discovery.normalize import finalize
from devjob.discovery import store
from devjob.providers import ProviderError, get_provider
from devjob.providers.base import SourceNotFound
from devjob.storage.db import dumps, loads, now_iso
from devjob.textutil import norm, sha256_text

_FETCHABLE = {"greenhouse", "lever", "inhire"}
_HOST_SKIP = {"www", "jobs", "job", "careers", "career", "carreiras", "vagas", "br", "com", "io", "app",
              "co", "net", "org"}
COMPANY_TEXT = {
    "found": "oportunidades encontradas",
    "not_found": "nenhuma oportunidade encontrada",
    "discarded": "vagas descartadas pelos critérios do candidato",
    "inaccessible": "fonte inacessível",
    "incomplete": "consulta não concluída",
}


def run_discovery(conn: sqlite3.Connection, http, payload: dict | list, prefs: dict, config: dict) -> dict:
    queries = _queries(payload)
    hits, leads, failures = _discover(queries)
    fetched, fetch_failures = _fetch(http, hits)
    failures.extend(fetch_failures)
    normalized = [finalize(job, now_iso()) for job in fetched]
    unique = _prefer_official(normalized)
    verified = _verify(unique)
    stored, outcomes = _persist(conn, verified)
    summary = _summary(queries, hits, leads, unique, stored, outcomes, failures, prefs, config)
    summary["reposts"] = _open_reposts(latest_report(conn), summary["reposts"], unique)
    save_report(conn, summary)
    return summary


def save_report(conn: sqlite3.Connection, summary: dict) -> None:
    with conn:
        conn.execute("INSERT INTO discovery_reports (created_at, summary_json) VALUES (?, ?)",
                     (now_iso(), dumps(summary)))


def latest_report(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT summary_json FROM discovery_reports ORDER BY id DESC LIMIT 1").fetchone()
    return loads(row["summary_json"], None) if row else None


def with_filter_outcomes(company_status: dict, matched_companies: set[str]) -> dict:
    """A company whose postings were all removed by the candidate's rules is not an empty search."""
    updated = dict(company_status)
    for name, status in company_status.items():
        if status == "found" and norm(name) not in matched_companies:
            updated[name] = "discarded"
    return updated


def format_priority_report(prefs: dict, shown: list, ranked: list, company_status: dict | None = None,
                           summary: dict | None = None) -> str:
    """Say what happened to each priority company, using the jobs rather than the ingest label alone."""
    names = [str(name).strip() for name in ((prefs.get("companies") or {}).get("priority") or []) if str(name).strip()]
    if not names:
        return ""
    status = company_status or {}
    indexes = {id(item): index for index, item in enumerate(shown, 1)}
    lines = ["Empresas prioritárias"]
    if summary:
        lines.append(f"Pesquisas: {summary.get('queries_run', 0)} consultas, "
                     f"{summary.get('raw_results', 0)} resultados brutos, "
                     f"{summary.get('unique_postings', 0)} anúncios únicos, "
                     f"{summary.get('verified', 0)} verificadas.")
    for name in names:
        lines.append(_priority_line(name, shown, ranked, indexes, status.get(name),
                                    (summary or {}).get("reposts") or []))
    return "\n".join(lines)


def mentions_company(name: str, item) -> bool:
    """The posting is about this priority company, including a name left inside a split title."""
    return _mentions(name, item.job.company) or _mentions(name, item.job.title)


def _mentions(name: str, text: str | None) -> bool:
    from devjob.employment import same_employer

    if same_employer(name, text):
        return True
    wanted = norm(name).split()
    hay = norm(text).split()
    if not wanted or len(hay) < len(wanted):
        return False
    width = len(wanted)
    return any(_same_tokens(hay[index:index + width], wanted) for index in range(len(hay) - width + 1))


def _same_tokens(left: list[str], right: list[str]) -> bool:
    if len(left) != len(right):
        return False
    for one, other in zip(left, right):
        if one == other or {one, other} == {"livre", "libre"}:
            continue
        return False
    return True


def _priority_line(name: str, shown: list, ranked: list, indexes: dict[int, int], status: str | None,
                   reposts: list | None = None) -> str:
    from devjob.discovery.classify import trusted_apply

    listed = [item for item in shown if mentions_company(name, item)]
    others = [item for item in ranked if mentions_company(name, item) and id(item) not in indexes]
    untrusted = [item for item in others if not item.match.eliminated and not trusted_apply(item.job.url, item.job.company)]
    blocked = {id(item) for item in untrusted}
    others = [item for item in others if id(item) not in blocked]
    discarded = [item for item in others if item.match.eliminated]
    waiting = [item for item in others if not item.match.eliminated
               and item.match.recommendation in {"recommended", "consider"}]
    below = [item for item in others if not item.match.eliminated and item not in waiting]
    parts: list[str] = []
    if listed:
        refs = "; ".join(f"{indexes[id(item)]}. {item.job.title}" for item in listed)
        parts.append(f"{len(listed)} na lista ({refs})")
    if discarded:
        parts.append(f"{_n(len(discarded), 'descartada', 'descartadas')} ({_job_notes(discarded)})")
    if waiting:
        parts.append(f"{_n(len(waiting), 'encontrada, fora da lista', 'encontradas, fora da lista')} "
                     f"({_job_notes(waiting, with_reason=False)})")
    if below:
        parts.append(f"{len(below)} abaixo do corte ({_job_notes(below, with_reason=False)})")
    if untrusted:
        parts.append(f"{_n(len(untrusted), 'anúncio em outro site, não incluído', 'anúncios em outros sites, não incluídos')}: "
                     "o link não é o da empresa")
    known = {norm(item.job.title) for item in listed + waiting}
    pending = [item for item in (reposts or [])
               if (_mentions(name, item.get("company")) or _mentions(name, item.get("title")))
               and norm(item.get("title")) not in known]
    if pending:
        titles = "; ".join(str(item.get("title") or name) for item in pending[:3])
        parts.append(f"visto fora do site da empresa; a página oficial não foi encontrada ({titles})")
    if parts:
        return f"{name}: " + ". ".join(parts) + "."
    if status == "found":
        return f"{name}: anúncios encontrados, nenhum entrou na lista."
    return f"{name}: {COMPANY_TEXT.get(status or '', COMPANY_TEXT['not_found'])}."


def _n(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _job_notes(items: list, *, with_reason: bool = True, limit: int = 3) -> str:
    notes = []
    for item in items[:limit]:
        reason = item.match.eliminations[0] if with_reason and item.match.eliminations else ""
        notes.append(f"{item.job.title}: {reason}" if reason else item.job.title)
    extra = len(items) - limit
    if extra > 0:
        notes.append(f"e mais {extra}")
    return "; ".join(notes)


def format_diagnosis(summary: dict | None, *, passed_filters: int | None = None) -> str:
    if not summary:
        return ("Descoberta web: nenhuma pesquisa foi executada. "
                "Isso é ausência de pesquisa, não falha de fonte.")
    failed = summary.get("failures") or []
    passed = "não calculado" if passed_filters is None else str(passed_filters)
    lines = [f"Descoberta: {summary.get('queries_run', 0)} pesquisas, "
             f"{summary.get('raw_results', 0)} resultados brutos, "
             f"{summary.get('unique_postings', 0)} anúncios únicos, "
             f"{summary.get('verified', 0)} verificadas, "
             f"{passed} passaram nos filtros, "
             f"{summary.get('source_count', 0)} fontes, "
             f"{len(failed)} buscas falharam."]
    for item in failed:
        lines.append(f"  falha: {item.get('query') or item.get('url')}: {item.get('error')}")
    for name, status in (summary.get("company_status") or {}).items():
        lines.append(f"  {name}: {COMPANY_TEXT.get(status, status)}")
    if summary.get("concentrated_source"):
        lines.append(f"  concentração: {summary['concentrated_source']} responde por boa parte dos anúncios.")
    if summary.get("career_pages"):
        lines.append(f"  páginas de carreiras: {len(summary['career_pages'])}")
    return "\n".join(lines)


def _queries(payload: dict | list) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("queries") or []
    return [item for item in payload if isinstance(item, dict)]


def _discover(queries: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    from devjob.discovery.classify import trusted_apply

    hits: list[tuple[dict, dict]] = []
    leads: list[dict] = []
    failures: list[dict] = []
    for query in queries:
        status = str(query.get("status") or "completed")
        if status == "failed":
            failures.append({"query": query.get("text") or query.get("id"), "error": query.get("error") or "falha"})
            continue
        if status != "completed":
            continue
        for result in query.get("results") or []:
            url = str(result.get("url") or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                continue
            classified = classify_url(url)
            if classified.kind in {"career_page", "board"}:
                leads.append({"url": url, "channel": classified.channel, "kind": classified.kind,
                              "company": query.get("company"), "title": result.get("title") or ""})
                continue
            if classified.kind != "posting":
                continue
            title, company = _split_title(str(result.get("title") or ""), query.get("company"))
            employer = company or str(query.get("company") or "").strip()
            if not trusted_apply(url, employer):
                if employer or title:
                    leads.append({"kind": "repost", "company": employer,
                                  "title": title or str(result.get("title") or "").strip()})
                continue
            hits.append((query, result))
    return hits, leads, failures


def _fetch(http, hits: list[tuple[dict, dict]]) -> tuple[list[Job], list[dict]]:
    jobs: list[Job] = []
    failures: list[dict] = []
    for query, result in hits:
        url = str(result["url"]).strip()
        classified = classify_url(url)
        if http is not None and classified.channel in _FETCHABLE and classified.external_id:
            try:
                source = CompanySource(classified.channel if classified.channel != "jobgether" else "lever",
                                        classified.slug, query.get("company"))
                provider = get_provider(source.provider, http)
                full = provider.fetch_job(source, classified.external_id)
            except SourceNotFound:
                full = None
            except ProviderError as exc:
                failures.append({"url": url, "error": str(exc), "query": query.get("text")})
                full = result
            if full is None:
                job = _job_from_hit(query, result)
                job.verification = "not_listed"
                jobs.append(job)
                continue
            if isinstance(full, Job):
                full.aliases = list(set(full.aliases) | {url})
                jobs.append(full)
                continue
        jobs.append(_job_from_hit(query, result))
    return jobs, failures


def _job_from_hit(query: dict, result: dict) -> Job:
    url = str(result["url"]).strip()
    classified = classify_url(url)
    title, company = _split_title(str(result.get("title") or ""), query.get("company"))
    if not company:
        company = _company_from_host(url)
    channel = classified.channel
    source = channel if channel in _FETCHABLE else "web"
    if channel == "jobgether":
        source = "lever"
    job = Job(source=source, external_id=classified.external_id or sha256_text(url)[:16],
              title=title or str(result.get("title") or "").strip(), company=company or "",
              url=url, apply_url=url, description=str(result.get("snippet") or result.get("description") or ""),
              location=result.get("location"), verification="unverified",
              field_sources={"all": "busca web", "channel": channel})
    if result.get("work_model") in ("remote", "hybrid", "onsite"):
        job.work_model = result["work_model"]
        job.field_sources["work_model"] = "busca web"
    return job


def _split_title(title: str, fallback: str | None) -> tuple[str, str]:
    parts = re.split(r"\s+(?:at|\||@)\s+|\s+-\s+", title, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        left, right = parts[0].strip(), parts[1].strip()
        right_tokens = set(norm(right).split())
        if left and right and not right_tokens <= {"remote", "remoto", "hybrid", "hibrido", "onsite", "senior",
                                                    "staff", "brazil", "brasil"}:
            return left, right
    return title.strip(), (fallback or "").strip()


def _company_from_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    parts = [part for part in host.split(".") if part and part not in _HOST_SKIP]
    return parts[0] if parts else ""


def _prefer_official(jobs: list[Job]) -> list[Job]:
    groups: dict[str, list[Job]] = {}
    order: list[str] = []
    for job in jobs:
        key = job.fingerprint or f"{norm(job.company)}|{norm(job.title)}|{job.canonical_url}"
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append(job)
    chosen = []
    for key in order:
        items = groups[key]
        official = [job for job in items if not classify_url(job.url).aggregator]
        best = official[0] if official else items[0]
        aliases = {job.canonical_url for job in items if job.canonical_url and job.canonical_url != best.canonical_url}
        best.aliases = sorted(set(best.aliases) | aliases)
        chosen.append(best)
    return chosen


def _verify(jobs: list[Job]) -> list[Job]:
    """A posting the official API no longer returns is kept, but not as an open role."""
    return jobs


def _persist(conn, jobs: list[Job]) -> tuple[list[tuple[str, str]], list[str]]:
    outcomes = []
    for job in jobs:
        outcomes.append(store.upsert_job(conn, job))
    return outcomes, [job.company for job in jobs if job.verification != "not_listed"]


def _summary(queries, hits, leads, unique, stored, open_companies, failures, prefs, config) -> dict:
    channels = [classify_url(job.url).channel for job in unique]
    counts = Counter(channel for channel in channels if channel)
    share = float(((config.get("search") or {}).get("discovery") or {}).get("max_source_share") or 0.4)
    concentrated = None
    if unique and counts:
        name, count = counts.most_common(1)[0]
        if count / len(unique) > share and name == "jobgether":
            concentrated = name
    by_company: dict[str, list[dict]] = {}
    for query in queries:
        company = str(query.get("company") or "").strip()
        if company:
            by_company.setdefault(company, []).append(query)
    open_norms = {norm(name) for name in open_companies if name}
    company_status = {}
    for name, submitted in by_company.items():
        company_status[name] = _company_status(submitted, norm(name) in open_norms)
    for name in (prefs.get("companies") or {}).get("priority") or []:
        label = str(name).strip()
        if label and label not in company_status:
            company_status[label] = "incomplete"
    verified = sum(1 for job in unique if job.verification in {"listed", "not_listed", "page_found"})
    reposts = [{"company": str(item.get("company") or "").strip(), "title": str(item.get("title") or "").strip()}
               for item in leads if item.get("kind") == "repost"]
    pages = [item for item in leads if item.get("kind") != "repost"]
    return {
        "queries_run": sum(1 for query in queries if query.get("status") in {"completed", "failed"}),
        "raw_results": len(hits) + len(leads),
        "unique_postings": len(unique),
        "verified": verified,
        "stored": [{"id": job_id, "outcome": outcome} for job_id, outcome in stored],
        "source_count": len(counts),
        "sources": dict(counts),
        "failures": failures,
        "company_status": company_status,
        "concentrated_source": concentrated,
        "career_pages": pages,
        "reposts": reposts,
        "queries": [{"id": query.get("id"), "text": query.get("text"), "status": query.get("status"),
                     "company": query.get("company"), "strategy": query.get("strategy")} for query in queries],
    }


def _open_reposts(previous: dict | None, current: list[dict], jobs: list) -> list[dict]:
    """Keep clues from other sites until the same opening is found on the company's own page."""
    from devjob.discovery.classify import trusted_apply
    from devjob.employment import same_employer

    resolved = [(job.company, job.title) for job in jobs if trusted_apply(job.url, job.company)]
    kept: list[dict] = []
    seen: set[tuple[str, str]] = set()
    earlier = (previous or {}).get("reposts") or []
    for item in [*earlier, *current]:
        company = str(item.get("company") or "").strip()
        title = str(item.get("title") or "").strip()
        key = (norm(company), norm(title))
        if key in seen or not (company or title):
            continue
        if any(_same_opening(company, title, other, role, same_employer) for other, role in resolved):
            continue
        seen.add(key)
        kept.append({"company": company, "title": title})
    return kept


def _same_opening(company: str, title: str, other: str, role: str, same) -> bool:
    if company and not (same(company, other) or _mentions(company, other) or _mentions(company, role)):
        return False
    return bool(title) and norm(title) == norm(role)


def _company_status(submitted: list[dict], found: bool) -> str:
    if found:
        return "found"
    statuses = {str(query.get("status") or "") for query in submitted}
    if statuses and statuses <= {"failed"}:
        return "inaccessible"
    if "completed" in statuses:
        return "not_found"
    return "incomplete"
