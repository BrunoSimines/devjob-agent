"""Search queries derived from a profile. The host runs them; this module does not."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from devjob.employment import excluded_names, exclusion_label, mentions_excluded
from devjob.profile.model import Profile
from devjob.storage.db import loads
from devjob.textutil import norm

_CRAFT_SPEC = {"backend", "frontend", "fullstack", "software", "mobile", "web", "engineer", "developer",
               "engenheiro", "engenheira", "desenvolvedor", "desenvolvedora"}
_COUNTRY = {"BR": ("Brazil", "Brasil"), "US": ("United States", "Estados Unidos"),
            "PT": ("Portugal", "Portugal"), "MX": ("Mexico", "México")}
_STRATEGY_ORDER = ("role", "stack", "specialization", "work", "contract", "company")


@dataclass
class PlannedQuery:
    id: str
    text: str
    language: str
    strategy: str
    company: str | None = None
    cached: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QueryPlan:
    queries: list[PlannedQuery] = field(default_factory=list)
    budget: int = 0
    notes: list[str] = field(default_factory=list)


def plan_queries(profile: Profile | None, prefs: dict, config: dict, *,
                 refresh: bool = False, conn: sqlite3.Connection | None = None,
                 plan_path: Path | None = None) -> QueryPlan:
    """Use the model's saved plan when it exists. Otherwise repeat the person's own words.

    Related titles are not invented here. The host model writes them with
    ``discover save-plan`` after reading ``discover context``.
    """
    if plan_path is not None and plan_path.exists() and not refresh:
        return _plan_from_file(plan_path, prefs, config)
    discovery = (config.get("search") or {}).get("discovery") or {}
    budget = int(discovery.get("max_queries") or 12)
    buckets = {name: [] for name in _STRATEGY_ORDER}
    titles = _titles(profile, prefs)
    _fill_roles(buckets["role"], titles, prefs)
    _fill_stack(buckets["stack"], prefs, titles)
    _fill_specializations(buckets["specialization"], profile, prefs)
    _fill_work(buckets["work"], buckets["contract"], titles, prefs)
    _fill_companies(buckets["company"], prefs)
    chosen = [query for query in _cover_companies(_take(buckets, budget), buckets["company"], budget)
              if not _blocked_query(query, prefs)]
    for index, query in enumerate(chosen, 1):
        query.id = f"q{index:02d}"
    notes = []
    if not chosen:
        notes.append("Sem cargo, especialização ou empresa prioritária para montar consultas.")
    cached_texts = set() if refresh else _cached_texts(conn, config)
    for query in chosen:
        query.cached = norm(query.text) in cached_texts
    if any(query.cached for query in chosen):
        notes.append("Consultas iguais já feitas no prazo de cache podem ser puladas. Isso não é falha.")
    return QueryPlan(chosen, budget, notes)


def _titles(profile: Profile | None, prefs: dict) -> list[str]:
    found = [str(role).strip() for role in (prefs.get("target_roles") or []) if str(role).strip()]
    if profile is not None:
        found += [exp.title.strip() for exp in profile.confirmed_experiences() if exp.title and exp.title.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for title in found:
        key = norm(title)
        if key and key not in seen:
            seen.add(key)
            unique.append(title)
    return unique


def _fill_roles(bucket: list[PlannedQuery], titles: list[str], prefs: dict) -> None:
    del prefs
    for title in titles:
        bucket.append(PlannedQuery("", title, _language(title), "role"))


def _fill_stack(bucket: list[PlannedQuery], prefs: dict, titles: list[str] | None = None) -> None:
    role = (titles or [""])[0]
    for skill in list(prefs.get("primary_stack") or [])[:3]:
        name = str(skill).strip()
        if not name:
            continue
        text = f"{name} {role}".strip()
        bucket.append(PlannedQuery("", text, _language(text), "stack"))


def _fill_specializations(bucket: list[PlannedQuery], profile: Profile | None, prefs: dict) -> None:
    specs = [str(item).strip() for item in (prefs.get("specializations") or []) if str(item).strip()]
    if profile is not None:
        specs += [fact.value for fact in profile.specializations if fact.confirmed and fact.value.strip()]
    seen: set[str] = set()
    for spec in specs:
        key = norm(spec)
        if not key or key in seen or set(key.split()) <= _CRAFT_SPEC:
            continue
        seen.add(key)
        bucket.append(PlannedQuery("", spec, _language(spec), "specialization"))


def _fill_work(work: list[PlannedQuery], contract: list[PlannedQuery], titles: list[str], prefs: dict) -> None:
    if not titles:
        return
    role = titles[0]
    accepted = [str(item).lower() for item in ((prefs.get("work_model") or {}).get("accepted") or [])]
    remote = "remote" in accepted
    country = str(((prefs.get("location") or {}).get("country") or "")).upper()
    en_country, pt_country = _COUNTRY.get(country, (country, country))
    en = " ".join(part for part in ("remote" if remote else "", role, en_country) if part)
    pt_model = "remoto" if remote else ""
    pt = " ".join(part for part in (pt_model, role, pt_country) if part)
    work.append(PlannedQuery("", en, "en", "work"))
    work.append(PlannedQuery("", pt, "pt", "work"))
    contracts = [str(item).lower() for item in ((prefs.get("contract_types") or {}).get("accepted") or [])]
    if "clt" in contracts:
        contract.append(PlannedQuery("", " ".join(part for part in ("vaga", role, "CLT", pt_country) if part),
                                     "pt", "contract"))
    if "contractor" in contracts or "international" in contracts:
        contract.append(PlannedQuery("", " ".join(part for part in (role, "contractor", en_country) if part),
                                     "en", "contract"))


def _language(text: str) -> str:
    return "pt" if re.search(r"[áàâãéêíóôõúç]", text, re.IGNORECASE) else "en"


def _fill_companies(bucket: list[PlannedQuery], prefs: dict) -> None:
    for name in (prefs.get("companies") or {}).get("priority") or []:
        label = str(name).strip()
        if not label or exclusion_label(label, prefs):
            continue
        bucket.append(PlannedQuery("", f"\"{label}\" careers jobs", "en", "company", label))
        bucket.append(PlannedQuery("", f"vagas \"{label}\"", "pt", "company", label))


def _blocked_query(query: PlannedQuery, prefs: dict) -> bool:
    if query.company and exclusion_label(query.company, prefs):
        return True
    return mentions_excluded(query.text, prefs)


def _take(buckets: dict[str, list[PlannedQuery]], limit: int) -> list[PlannedQuery]:
    indexes = {name: 0 for name in _STRATEGY_ORDER}
    chosen: list[PlannedQuery] = []
    seen: set[str] = set()
    while len(chosen) < limit:
        progressed = False
        for name in _STRATEGY_ORDER:
            items = buckets[name]
            index = indexes[name]
            while index < len(items) and norm(items[index].text) in seen:
                index += 1
            if index >= len(items):
                indexes[name] = index
                continue
            seen.add(norm(items[index].text))
            chosen.append(items[index])
            indexes[name] = index + 1
            progressed = True
            if len(chosen) >= limit:
                break
        if not progressed:
            break
    return chosen


def _cover_companies(chosen: list[PlannedQuery], company_bucket: list[PlannedQuery], limit: int) -> list[PlannedQuery]:
    present = {query.company for query in chosen if query.company}
    for query in company_bucket:
        if query.company in present:
            continue
        if len(chosen) < limit:
            chosen.append(query)
        else:
            for index in range(len(chosen) - 1, -1, -1):
                if chosen[index].strategy != "company":
                    chosen[index] = query
                    break
        present.add(query.company)
    return chosen


def save_search_plan(path: Path, payload: dict | list, prefs: dict) -> dict:
    """Store a model-written plan. Queries that name an excluded employer are refused."""
    incoming = payload.get("queries") if isinstance(payload, dict) else payload
    kept: list[dict] = []
    rejected: list[str] = []
    for item in incoming or []:
        if not isinstance(item, dict):
            rejected.append("registro inválido")
            continue
        text = str(item.get("text") or "").strip()
        company = str(item.get("company") or "").strip() or None
        if not text or _blocked_query(PlannedQuery("", text, "pt", item.get("strategy") or "role", company), prefs):
            rejected.append(text or company or "consulta vazia")
            continue
        kept.append({"text": text, "language": item.get("language") or _language(text),
                     "strategy": item.get("strategy") or "role", "company": company})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"queries": kept}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": len(kept), "rejected": rejected, "path": str(path)}


def search_context(profile: Profile | None, prefs: dict) -> dict:
    """Facts the model needs to write a plan. Contact details stay out."""
    titles = _titles(profile, prefs)
    skills = [str(item) for item in (prefs.get("primary_stack") or [])]
    if profile is not None:
        skills += [fact.value for fact in profile.hard_skills if fact.confirmed]
    specs = [str(item) for item in (prefs.get("specializations") or [])]
    if profile is not None:
        specs += [fact.value for fact in profile.specializations if fact.confirmed]
    return {
        "target_roles": titles,
        "skills": list(dict.fromkeys(skills)),
        "specializations": list(dict.fromkeys(specs)),
        "seniority": (prefs.get("seniority") or {}).get("levels") or [],
        "work_model": (prefs.get("work_model") or {}).get("accepted") or [],
        "location": prefs.get("location") or {},
        "priority_companies": (prefs.get("companies") or {}).get("priority") or [],
        "do_not_query_companies": excluded_names(prefs),
        "note": "Escreva consultas relacionadas com estas palavras. Não inclua do_not_query_companies no texto.",
    }


def _plan_from_file(path: Path, prefs: dict, config: dict) -> QueryPlan:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("queries") if isinstance(data, dict) else data
    queries = []
    for index, item in enumerate(raw or [], 1):
        query = PlannedQuery(f"q{index:02d}", str(item.get("text") or ""), item.get("language") or "pt",
                             item.get("strategy") or "role", item.get("company"))
        if query.text and not _blocked_query(query, prefs):
            queries.append(query)
    budget = int(((config.get("search") or {}).get("discovery") or {}).get("max_queries") or 12)
    return QueryPlan(queries[:budget], budget, ["Plano salvo pelo modelo. O Python não inventou cargos."])


def _cached_texts(conn: sqlite3.Connection | None, config: dict) -> set[str]:
    if conn is None:
        return set()
    ttl = float((config.get("search") or {}).get("cache_ttl_hours") or 0)
    if ttl <= 0:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl)
    found: set[str] = set()
    rows = conn.execute("SELECT created_at, summary_json FROM discovery_reports ORDER BY id DESC LIMIT 20")
    for row in rows:
        created = datetime.fromisoformat(row["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < cutoff:
            continue
        summary = loads(row["summary_json"], {})
        for query in summary.get("queries") or []:
            if query.get("status") == "completed" and query.get("text"):
                found.add(norm(query["text"]))
    return found
