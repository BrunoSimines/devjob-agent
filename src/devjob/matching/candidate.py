"""Candidate x job compatibility.

Design rules:
* Each component has an explicit criterion and a value in [0, 1].
* Components without enough information get ``value = None``: they are left out
  of the score (weights are renormalized) and reported as uncertain. The share
  of weight that could be evaluated is returned as ``confidence``.
* Eliminatory rules from preferences.yaml are evaluated separately and can't be
  compensated by a high score. Unknown information never eliminates.
* Only confirmed profile facts ([resume]/[user]) count as met. Inferred facts
  produce "uncertain" items.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from devjob import taxonomy
from devjob.discovery.models import Job
from devjob.discovery.normalize import location_tokens
from devjob.profile.model import Profile
from devjob.textutil import norm, token_set

LEVEL_ORDER = {"intern": 0, "junior": 1, "mid": 2, "senior": 3, "lead": 4, "staff": 4, "principal": 5}
COMPONENT_LABELS = {
    "required_skills": "Requisitos obrigatórios",
    "experience": "Experiência relevante",
    "preferred_skills": "Requisitos desejáveis",
    "seniority": "Senioridade",
    "languages": "Idiomas",
    "location": "Localização e regime",
    "compensation": "Remuneração",
    "preferences": "Preferências profissionais",
}
RECOMMENDATION_LABELS = {
    "recommended": "recomendada",
    "consider": "avaliar",
    "not_recommended": "não recomendada",
    "eliminated": "eliminada",
    "insufficient_data": "dados insuficientes",
}
_TITLE_STOPWORDS = {"senior", "sr", "junior", "jr", "pleno", "pl", "staff", "principal", "lead", "ii", "iii", "iv", "i",
                    "de", "da", "do", "of", "the", "and", "e", "a", "o", "em", "in", "for", "para", "remote",
                    "remoto", "hybrid", "brazil", "brasil", "latam", "mid", "level"}
_COUNTRY_ALIASES = {
    "BR": {"br", "brazil", "brasil", "bra", "sao paulo", "rio de janeiro", "curitiba",
           "belo horizonte", "brasilia", "recife", "porto alegre", "florianopolis", "campinas"},
    "US": {"us", "usa", "united states", "estados unidos"},
    "PT": {"pt", "portugal"},
    "CA": {"ca", "canada"},
    "UK": {"uk", "united kingdom", "england", "london"},
    "DE": {"de", "germany", "alemanha", "berlin"},
    "ES": {"es", "spain", "espanha"},
    "MX": {"mx", "mexico"},
    "AR": {"ar", "argentina"},
    "IN": {"in", "india"},
}
_GLOBAL_REGIONS = {"worldwide", "anywhere", "global", "latam", "latin america", "americas", "south america",
                   "america latina"}
_PLACELESS_REMOTE = {"remote", "remoto", "remota", "remotos", "wfh", "home", "anywhere", "worldwide", "global"}
_REGION_MEMBERS = {"latam": {"BR", "MX", "AR"}, "latin america": {"BR", "MX", "AR"}, "americas": {"BR", "US", "CA", "MX", "AR"},
                   "south america": {"BR", "AR"}, "america latina": {"BR", "MX", "AR"},
                   "europe": {"PT", "UK", "DE", "ES"}, "emea": {"PT", "UK", "DE", "ES"},
                   "worldwide": set(), "anywhere": set(), "global": set()}


@dataclass
class Component:
    name: str
    weight: float
    value: float | None
    criterion: str

    @property
    def label(self) -> str:
        return COMPONENT_LABELS.get(self.name, self.name)


@dataclass
class MatchResult:
    job_id: str
    score: float | None
    confidence: float
    recommendation: str
    eliminated: bool
    eliminations: list[str] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    met: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    justification: str = ""
    profile_version: int | None = None

    @property
    def required_coverage(self) -> float | None:
        for c in self.components:
            if c.name == "required_skills":
                return c.value
        return None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["components"] = [{**asdict(c), "label": c.label} for c in self.components]
        data["recommendation_label"] = RECOMMENDATION_LABELS[self.recommendation]
        return data


def _countries_in(text: str | None) -> set[str]:
    low = f" {norm(text)} "
    return {code for code, names in _COUNTRY_ALIASES.items() if any(f" {n} " in low for n in names)}


def _regions_in(text: str | None) -> set[str]:
    low = f" {norm(text)} "
    return {r for r in _REGION_MEMBERS if f" {r} " in low}


def _remote_without_place(location: str | None) -> bool:
    tokens = set(norm(location).split())
    return bool(tokens) and tokens <= _PLACELESS_REMOTE


_TITLE_SYNONYMS = {"developer": "engineer", "developers": "engineer", "desenvolvedor": "engineer",
                   "desenvolvedora": "engineer", "desenvolvedores": "engineer", "engenheiro": "engineer",
                   "engenheira": "engineer", "ingeniero": "engineer", "ingeniera": "engineer",
                   "programador": "engineer", "programadora": "engineer",
                   "programmer": "engineer", "programmers": "engineer"}
# Words that name the craft, not a specialty. "Engineer" alone does not make two jobs the same.
_CRAFT_TOKENS = {"engineer", "developer", "programmer", "architect", "arquiteto", "arquiteta"}
_TITLE_FILLER = {"software", "pessoa", "pessoas", "technical", "tecnico", "tecnica", "tech", "it", "ti",
                 "systems", "sistema", "sistemas"}
# A job in one of these is a different profession, unless the person's roles or experiences say so.
_OTHER_OCCUPATIONS = {
    "product": {"product", "produto"},
    "management": {"manager", "gerente", "gestor", "gestora", "head", "director", "diretor", "diretora"},
    "design": {"designer"},
    "analysis": {"analyst", "analista"},
    "support": {"support", "suporte"},
    "sales": {"sales", "comercial", "vendedor", "vendedora"},
    "recruiting": {"recruiter", "recrutador", "recrutadora"},
    "marketing": {"marketing"},
}


def role_tokens(text: str) -> set[str]:
    folded = norm(text).replace("back end", "backend").replace("front end", "frontend")
    folded = folded.replace("full stack", "fullstack")
    raw = {word for word in folded.split() if len(word) > 1}
    return {_TITLE_SYNONYMS.get(token, token) for token in raw} - _TITLE_STOPWORDS


def occupations(title: str) -> set[str]:
    """Craft and profession tags present in a title. Empty when the title names neither."""
    tokens = role_tokens(title)
    found = {"build"} if tokens & _CRAFT_TOKENS else set()
    for name, words in _OTHER_OCCUPATIONS.items():
        if tokens & words:
            found.add(name)
    return found


def distinctive_tokens(title: str) -> set[str]:
    """Title tokens that name a specialty. Craft and filler words are left out."""
    return role_tokens(title) - _CRAFT_TOKENS - _TITLE_FILLER


# Words that show up in titles without naming a specialty or a tool.
_TITLE_NOISE = {
    "users", "user", "first", "team", "squad", "level", "only", "applicants", "applicant",
    "pwd", "pcd", "people", "vaga", "new", "core", "internal", "external", "open",
}


def title_constraints(title: str, company: str = "") -> set[str]:
    """Skills and specialty words a title commits to. Company names and harmless words are ignored."""
    company_tokens = role_tokens(company)
    constraints = {norm(skill) for skill in taxonomy.find_skills(title)}
    for token in distinctive_tokens(title):
        if token in company_tokens or token in _TITLE_NOISE or any(char.isdigit() for char in token):
            continue
        canonical = taxonomy.canonical_skill(token)
        if canonical:
            constraints.add(norm(canonical))
            continue
        matched = taxonomy.find_skills(token)
        if len(matched) == 1:
            constraints.add(norm(next(iter(matched))))
            continue
        constraints.add(token)
    return constraints


def _role_tokens(text: str) -> set[str]:
    return role_tokens(text)


def title_alignment(title: str, roles: list[str]) -> float | None:
    if not roles:
        return None
    title_tokens = _role_tokens(title)
    if not title_tokens:
        return None
    best = 0.0
    for role in roles:
        role_tokens = _role_tokens(role)
        if role_tokens:
            best = max(best, len(role_tokens & title_tokens) / len(role_tokens))
    return best


def job_skill_pools(job: Job) -> tuple[list[str], list[str], str]:
    """(required pool, preferred pool, description of the required criterion)."""
    req = job.requirements or {}
    if req.get("required"):
        preferred = list(dict.fromkeys(req.get("preferred", []) + req.get("mentioned", [])))
        return req["required"], preferred, "requisitos obrigatórios da vaga"
    if not req.get("structured") and req.get("mentioned"):
        return req["mentioned"], req.get("preferred", []), "tecnologias mencionadas (vaga sem seção de requisitos)"
    return [], list(dict.fromkeys(req.get("preferred", []) + req.get("mentioned", []))), "requisitos obrigatórios"


def candidate_skills(profile: Profile) -> tuple[set[str], dict[str, str], set[str]]:
    confirmed = profile.confirmed_hard_skills()
    implied = taxonomy.expand_implications(confirmed)
    inferred = profile.inferred_hard_skills()
    inferred |= set(taxonomy.expand_implications(inferred)) - confirmed - set(implied)
    return confirmed, implied, inferred


def _salary_minimum(job: Job, prefs: dict) -> tuple[dict | None, str | None]:
    minimums = [m for m in prefs["salary"].get("minimums") or [] if isinstance(m, dict) and m.get("amount")]
    if not minimums:
        return None, "nenhum salário mínimo definido em preferences.yaml"
    currency = (job.salary_currency or "").upper()
    if not currency:
        return None, "moeda do salário não identificada"
    same = [m for m in minimums if str(m.get("currency", "")).upper() == currency]
    if not same:
        return None, f"sem mínimo definido para {currency} (não há conversão cambial)"
    if job.contract_type:
        exact = [m for m in same if m.get("contract") == job.contract_type]
        if exact:
            return exact[0], None
    return min(same, key=lambda m: m["amount"]), None


def _convert(amount: float, from_period: str, to_period: str) -> float | None:
    if from_period == to_period:
        return amount
    if from_period == "year" and to_period == "month":
        return amount / 12
    if from_period == "month" and to_period == "year":
        return amount * 12
    return None


def evaluate(job: Job, profile: Profile, prefs: dict, config: dict, profile_version: int | None = None) -> MatchResult:
    weights = config["matching"]["weights"]
    comps: list[Component] = []
    met: list[str] = []
    gaps: list[str] = []
    uncertain: list[str] = []
    eliminations: list[str] = []
    warnings: list[str] = []
    req = job.requirements or {}
    text = f"{job.title}\n{job.description}"

    confirmed, implied, inferred = candidate_skills(profile)
    has = confirmed | set(implied)

    # 1. Requisitos obrigatórios
    required, preferred, req_label = job_skill_pools(job)
    required_met = 0
    for skill in required:
        if skill in confirmed:
            required_met += 1
            met.append(skill)
        elif skill in implied:
            required_met += 1
            met.append(f"{skill} (comprovado por {implied[skill]})")
        elif skill in inferred:
            uncertain.append(f"{skill}: inferido no perfil, precisa de confirmação")
        else:
            gaps.append(f"{skill} (obrigatório)")
    comps.append(Component("required_skills", weights["required_skills"],
                           required_met / len(required) if required else None,
                           f"{required_met}/{len(required)} {req_label} comprovados no perfil" if required
                           else "vaga sem requisitos técnicos identificáveis"))
    if not required:
        uncertain.append("requisitos obrigatórios não identificados na descrição")

    # 2. Experiência relevante
    used_in_experience = [s for s in required if profile.experiences_using(s)
                          or (s in implied and profile.experiences_using(implied[s]))]
    relevant = [e for e in profile.confirmed_experiences()
                if (e.skills() | set(taxonomy.expand_implications(e.skills()))) & set(required)]
    years = profile.months_of(relevant) / 12 if relevant else profile.total_months() / 12
    min_years = req.get("min_years")
    exp_value: float | None = None
    parts = []
    if required:
        exp_value = len(used_in_experience) / len(required)
        parts.append(f"{len(used_in_experience)}/{len(required)} requisitos usados em experiências profissionais")
    if min_years:
        ratio = min(1.0, years / min_years)
        exp_value = ratio if exp_value is None else (exp_value + ratio) / 2
        parts.append(f"~{years:.1f} anos relevantes comprovados de {min_years}+ pedidos")
        if years < min_years:
            gaps.append(f"experiência: vaga pede {min_years}+ anos; perfil comprova ~{years:.1f}")
    comps.append(Component("experience", weights["experience"], exp_value,
                           "; ".join(parts) or "sem requisitos de experiência identificáveis"))

    # 3. Requisitos desejáveis (técnicos e comportamentais)
    soft_pool = list(dict.fromkeys(req.get("soft_required", []) + req.get("soft_preferred", [])))
    pool_size = len(preferred) + len(soft_pool)
    preferred_met = 0
    for skill in preferred:
        if skill in has:
            preferred_met += 1
            met.append(f"{skill} (desejável)")
        elif skill in inferred:
            uncertain.append(f"{skill} (desejável): inferido no perfil")
        else:
            gaps.append(f"{skill} (desejável)")
    soft_confirmed, soft_inferred = profile.confirmed_soft_skills(), profile.inferred_soft_skills()
    soft_uncertain: list[str] = []
    for skill in soft_pool:
        if skill in soft_confirmed:
            preferred_met += 1
            met.append(f"{skill} (comportamental)")
        elif skill in soft_inferred:
            soft_uncertain.append(f"{skill} (comportamental): inferido, confirme com exemplos reais")
        else:
            soft_uncertain.append(f"{skill} (comportamental): não registrado no perfil")
    comps.append(Component("preferred_skills", weights["preferred_skills"],
                           preferred_met / pool_size if pool_size else None,
                           f"{preferred_met}/{pool_size} requisitos desejáveis atendidos" if pool_size
                           else "vaga sem requisitos desejáveis identificáveis"))

    # 4. Senioridade
    desired = [str(s).lower() for s in prefs["seniority"].get("levels") or []]
    level = job.seniority
    sen_value: float | None = None
    if not level:
        uncertain.append("senioridade não informada no título")
        sen_criterion = "senioridade da vaga desconhecida"
    elif not desired:
        sen_criterion = "defina seniority.levels em preferences.yaml"
    else:
        if level in desired:
            sen_value = 1.0
        elif level in LEVEL_ORDER and any(abs(LEVEL_ORDER[level] - LEVEL_ORDER[d]) == 1
                                          for d in desired if d in LEVEL_ORDER):
            sen_value = 0.5
        else:
            sen_value = 0.0
        sen_criterion = f"vaga '{level}' vs desejado {desired} (1 = igual, 0,5 = nível adjacente, 0 = outro)"
        if sen_value < 1:
            gaps.append(f"senioridade: vaga '{level}', desejado {', '.join(desired)}")
        if level not in desired and prefs["seniority"].get("eliminatory"):
            eliminations.append(f"senioridade '{level}' fora de {desired} (eliminatório)")
    comps.append(Component("seniority", weights["seniority"], sen_value, sen_criterion))

    # 5. Idiomas
    lang_checked = lang_met = 0
    working = {taxonomy.language_code(str(w.get("language", ""))): w.get("level")
               for w in prefs["languages"].get("working") or [] if isinstance(w, dict)}
    for lang in req.get("languages", []):
        code, needed = lang["code"], lang.get("level") or "B2"
        label = taxonomy.LANGUAGE_LABELS.get(code, code)
        have = profile.language_level(code) or working.get(code)
        if not have:
            uncertain.append(f"{label} {needed}: nível não registrado no perfil")
            continue
        lang_checked += 1
        if taxonomy.LEVEL_RANK.get(str(have), 0) >= taxonomy.LEVEL_RANK.get(str(needed), 0):
            lang_met += 1
            met.append(f"{label} ({have})")
        elif lang.get("explicit"):
            gaps.append(f"{label}: vaga pede {needed}, perfil indica {have}")
            if lang.get("required") and prefs["languages"].get("eliminatory"):
                eliminations.append(f"{label} {needed} exigido; perfil indica {have} (eliminatório)")
        else:
            uncertain.append(f"{label}: vaga escrita em {label}; perfil indica {have}")
    comps.append(Component("languages", weights["languages"],
                           lang_met / lang_checked if lang_checked else None,
                           f"{lang_met}/{lang_checked} exigências de idioma atendidas" if lang_checked
                           else "sem exigência de idioma avaliável"))

    # 6. Localização e regime
    accepted = [str(m).lower() for m in prefs["work_model"].get("accepted") or []]
    loc_prefs = prefs["location"]
    country = str(loc_prefs.get("country") or "").upper()
    city = norm(loc_prefs.get("city"))
    loc_value: float | None = None
    model = job.work_model
    if not model:
        uncertain.append("modelo de trabalho (remoto/híbrido/presencial) não informado")
        loc_criterion = "modelo de trabalho desconhecido"
    elif accepted and model not in accepted:
        loc_value = 0.0
        loc_criterion = f"modelo '{model}' fora de {accepted}"
        gaps.append(f"modelo de trabalho '{model}' (aceito: {', '.join(accepted)})")
        if prefs["work_model"].get("eliminatory"):
            eliminations.append(f"modelo de trabalho '{model}' não aceito (eliminatório)")
    elif model == "remote":
        job_countries, job_regions = _countries_in(job.location), _regions_in(job.location)
        if city and country and set(city.split()) <= set(norm(job.location).split()):
            job_countries.add(country)
        if loc_prefs.get("only_country") and country:
            if country in job_countries:
                loc_value, loc_criterion = 1.0, f"remoto no país {country}"
            else:
                loc_value, loc_criterion = 0.0, f"remoto fora de {country}"
                where = job.location or "local não informado"
                eliminations.append(f"vaga fora de {country}: '{where}' (eliminatório)")
        elif not country:
            loc_value, loc_criterion = 1.0, "remoto (sem país do candidato para comparar)"
            if job.location:
                uncertain.append("defina location.country para avaliar restrições geográficas")
        elif not job.location or _remote_without_place(job.location):
            loc_value, loc_criterion = 1.0, "remoto (sem restrição geográfica identificada)"
        elif not (job_countries or job_regions):
            loc_criterion = f"remoto em '{job.location}', país não reconhecido"
            uncertain.append(f"remoto com localização '{job.location}': país não reconhecido; "
                             f"confirme se aceita candidatos de {country}")
        elif country in job_countries or any(not _REGION_MEMBERS[r] or country in _REGION_MEMBERS[r]
                                             for r in job_regions):
            loc_value, loc_criterion = 1.0, f"remoto, região '{job.location}' compatível com {country}"
        else:
            loc_criterion = f"remoto restrito a '{job.location}'"
            uncertain.append(f"remoto com localização '{job.location}': confirmar se aceita candidatos de {country}")
    else:
        tokens = location_tokens(job.location)
        if not job.location:
            loc_criterion = f"{model}, localização não informada"
            uncertain.append("localização da vaga não informada")
        elif (city and set(city.split()) <= tokens) or (country and country in _countries_in(job.location)
                                                        and not city):
            loc_value, loc_criterion = 1.0, f"{model} em '{job.location}', compatível"
        elif loc_prefs.get("accept_relocation"):
            loc_value, loc_criterion = 1.0, f"{model} em '{job.location}' (aceita mudança)"
        else:
            loc_value, loc_criterion = 0.0, f"{model} em '{job.location}', fora da sua localização"
            gaps.append(f"localização: {model} em {job.location}")
            if loc_prefs.get("eliminatory"):
                eliminations.append(f"{model} em '{job.location}' sem aceitar mudança (eliminatório)")
    comps.append(Component("location", weights["location"], loc_value, loc_criterion))

    # 7. Remuneração
    comp_value: float | None = None
    if not job.has_salary:
        uncertain.append("salário não informado pela vaga")
        comp_criterion = "salário não informado"
    else:
        minimum, problem = _salary_minimum(job, prefs)
        if problem:
            uncertain.append(f"salário informado, mas não comparável: {problem}")
            comp_criterion = problem
        elif not job.salary_period:
            uncertain.append("salário informado sem período (mês/ano)")
            comp_criterion = "período do salário desconhecido"
        else:
            target_period = minimum.get("period", "month")
            low = job.salary_min if job.salary_min is not None else job.salary_max
            high = job.salary_max if job.salary_max is not None else job.salary_min
            low_c, high_c = _convert(low, job.salary_period, target_period), _convert(high, job.salary_period, target_period)
            if low_c is None:
                uncertain.append(f"salário por '{job.salary_period}' não convertível para '{target_period}'")
                comp_criterion = "períodos incompatíveis"
            else:
                floor = float(minimum["amount"])
                cur = minimum["currency"]
                period_inferred = job.field_sources.get("salary_period") == "inferred"
                if low_c >= floor:
                    comp_value = 1.0
                    met.append(f"salário {cur} {low_c:,.0f}+/{target_period} ≥ mínimo {floor:,.0f}")
                elif high_c >= floor:
                    comp_value = 0.5
                    uncertain.append(f"faixa {cur} {low_c:,.0f}–{high_c:,.0f}/{target_period} cruza o mínimo {floor:,.0f}")
                else:
                    comp_value = 0.0
                    gaps.append(f"salário até {cur} {high_c:,.0f}/{target_period} abaixo do mínimo {floor:,.0f}")
                    if prefs["salary"].get("eliminatory") and not period_inferred:
                        eliminations.append(f"salário máximo {cur} {high_c:,.0f}/{target_period} abaixo do mínimo "
                                            f"{floor:,.0f} (eliminatório)")
                if period_inferred:
                    uncertain.append("período do salário inferido (não explícito na vaga)")
                comp_criterion = (f"faixa convertida para {target_period} vs mínimo {cur} {floor:,.0f} "
                                  "(1 = faixa toda acima, 0,5 = cruza o mínimo, 0 = abaixo)")
    comps.append(Component("compensation", weights["compensation"], comp_value, comp_criterion))

    # 8. Preferências profissionais
    subs: list[tuple[str, float]] = []
    job_skills = set(required) | set(preferred) | set(req.get("mentioned", []))
    if (align := title_alignment(job.title, prefs.get("target_roles") or [])) is not None:
        subs.append(("cargo-alvo", align))
    for key, label in (("primary_stack", "stack principal"), ("hard_skills_to_use", "skills que deseja usar")):
        wanted = [taxonomy.canonical_skill(s) or s for s in prefs.get(key) or []]
        if wanted:
            subs.append((label, sum(1 for s in wanted if s in job_skills) / len(wanted)))
    if prefs.get("specializations"):
        hits = [s for s in prefs["specializations"] if norm(s) and f" {norm(s)} " in f" {norm(text)} "]
        subs.append(("especializações", 1.0 if hits else 0.0))
    nice = (prefs.get("nice_to_have") or {}).get("keywords") or []
    if nice:
        subs.append(("palavras desejadas", sum(1 for k in nice if norm(k) in norm(text)) / len(nice)))
    contracts = [str(c).lower() for c in prefs["contract_types"].get("accepted") or []]
    if job.contract_type and contracts:
        ok = job.contract_type in contracts
        subs.append(("tipo de contratação", 1.0 if ok else 0.0))
        if not ok:
            gaps.append(f"contratação '{job.contract_type}' (aceito: {', '.join(contracts)})")
            if prefs["contract_types"].get("eliminatory"):
                eliminations.append(f"contratação '{job.contract_type}' não aceita (eliminatório)")
    elif not job.contract_type:
        uncertain.append("tipo de contratação (CLT/PJ/internacional) não informado")
    desired_companies = [norm(c) for c in (prefs.get("companies") or {}).get("desired") or []]
    if norm(job.company) in desired_companies:
        subs.append(("empresa desejada", 1.0))
        met.append(f"empresa desejada: {job.company}")
    comps.append(Component("preferences", weights["preferences"],
                           sum(v for _, v in subs) / len(subs) if subs else None,
                           "; ".join(f"{name} {value:.0%}" for name, value in subs) or "sem preferências aplicáveis"))

    # Eliminatórios independentes de componentes
    from devjob.employment import exclusion_label
    if (employer := exclusion_label(job.company, prefs)):
        eliminations.append(employer)
    for keyword in (prefs.get("dealbreakers") or {}).get("keywords") or []:
        if norm(keyword) and f" {norm(keyword)} " in f" {norm(text)} ":
            eliminations.append(f"contém termo eliminatório '{keyword}'")
    if job.suspicious:
        warnings.append("a descrição contém trechos que parecem instruções para IA; foram tratados apenas como "
                        "texto e não influenciam a análise")
    if job.verification != "listed":
        warnings.append(f"vaga {job.verification}: confirme no link original se ainda está aberta")

    total_weight = sum(c.weight for c in comps)
    known = [c for c in comps if c.value is not None]
    known_weight = sum(c.weight for c in known)
    score = round(100 * sum(c.weight * c.value for c in known) / known_weight, 1) if known_weight else None
    confidence = round(known_weight / total_weight, 2) if total_weight else 0.0

    bands = config["matching"]["bands"]
    coverage = required_met / len(required) if required else None
    if eliminations:
        recommendation = "eliminated"
    elif score is None:
        recommendation = "insufficient_data"
    elif coverage is not None and coverage < config["matching"]["min_required_coverage"]:
        recommendation = "consider" if score >= bands["moderate"] else "not_recommended"
    elif coverage is None:
        # Without identifiable requirements the job can't be recommended, only flagged for review.
        recommendation = "consider" if score >= bands["moderate"] else "not_recommended"
    elif score >= bands["strong"] and confidence >= config["matching"]["min_confidence"]:
        recommendation = "recommended"
    elif score >= bands["moderate"]:
        recommendation = "consider"
    else:
        recommendation = "not_recommended"

    result = MatchResult(job_id=job.id, score=score, confidence=confidence, recommendation=recommendation,
                         eliminated=bool(eliminations), eliminations=eliminations, components=comps,
                         met=met, gaps=gaps, uncertain=list(dict.fromkeys(uncertain + soft_uncertain)),
                         warnings=warnings,
                         profile_version=profile_version)
    result.justification = _justify(result, required, required_met)
    return result


def _justify(result: MatchResult, required: list[str], required_met: int) -> str:
    label = RECOMMENDATION_LABELS[result.recommendation].capitalize()
    if result.eliminated:
        return f"{label}: " + "; ".join(result.eliminations)
    parts = []
    if required:
        missing = [g.split(" (")[0] for g in result.gaps if g.endswith("(obrigatório)")]
        parts.append(f"atende {required_met}/{len(required)} requisitos obrigatórios"
                     + (f" (faltam: {', '.join(missing[:4])})" if missing else ""))
    strong = [c.label.lower() for c in result.components if c.value is not None and c.value >= 1 and
              c.name != "required_skills"]
    if strong:
        parts.append("compatível em " + ", ".join(strong[:4]))
    unknown = [c.label.lower() for c in result.components if c.value is None]
    if unknown:
        parts.append("sem informação sobre " + ", ".join(unknown[:4]))
    score = f"{result.score:.0f}/100" if result.score is not None else "sem nota"
    return f"{label} ({score}, confiança {result.confidence:.0%}): " + "; ".join(parts)
