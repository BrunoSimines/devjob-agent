"""Resume x job fit (independent from candidate x job).

The question here is: does a saved resume *show* the experience the candidate
actually has for this job? Requirements the candidate doesn't have are ignored
(a resume can't truthfully cover them), so a weak candidate can have a
well-fitting resume and a strong candidate can have a poorly fitting one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from devjob import taxonomy
from devjob.discovery.models import Job
from devjob.discovery.normalize import seniority_from_title
from devjob.matching.candidate import candidate_skills, job_skill_pools, title_alignment
from devjob.profile.model import Profile
from devjob.resumes.library import ResumeRecord
from devjob.textutil import norm

WEIGHTS = {"required": 0.60, "preferred": 0.15, "role": 0.15, "language": 0.10}
_STAFF_LEVELS = {"staff", "principal", "lead"}
# A specialization that only names the craft does not get its own resume.
_CRAFT_SPECS = {"backend", "frontend", "fullstack", "software", "mobile", "web", "engineer", "developer"}


@dataclass
class ResumeFit:
    resume_id: str
    label: str
    score: float
    components: dict[str, float | None]
    covered: list[str]
    missing: list[str]
    notes: list[str] = field(default_factory=list)


@dataclass
class ResumeDecision:
    decision: str  # reuse | reuse_with_gaps | propose_new | no_resumes | nothing_to_highlight
    best: ResumeFit | None
    ranking: list[ResumeFit]
    threshold: float
    potential_gain: float | None
    explanation: str
    suggestion: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _core(job: Job, profile: Profile) -> tuple[list[str], list[str]]:
    required, preferred, _ = job_skill_pools(job)
    confirmed, implied, _ = candidate_skills(profile)
    has = confirmed | set(implied)
    return [s for s in required if s in has], [s for s in preferred if s in has]


def _weighted(components: dict[str, float | None]) -> float:
    known = {k: v for k, v in components.items() if v is not None}
    weight = sum(WEIGHTS[k] for k in known)
    return round(sum(WEIGHTS[k] * v for k, v in known.items()) / weight, 3) if weight else 0.0


def evaluate_resume(job: Job, profile: Profile, resume: ResumeRecord) -> ResumeFit:
    core_required, core_preferred = _core(job, profile)
    skills = resume.skills()
    covered = [s for s in core_required + core_preferred if s in skills]
    missing = [s for s in core_required + core_preferred if s not in skills]
    roles = resume.target_roles + ([resume.label] if resume.label else [])
    components = {
        "required": (sum(1 for s in core_required if s in skills) / len(core_required)) if core_required else None,
        "preferred": (sum(1 for s in core_preferred if s in skills) / len(core_preferred)) if core_preferred else None,
        "role": title_alignment(job.title, roles),
        "language": (1.0 if resume.language == job.language else 0.0) if job.language and resume.language else None,
    }
    notes = []
    if components["language"] == 0.0:
        notes.append(f"currículo em '{resume.language}', vaga em '{job.language}'")
    if resume.archived:
        notes.append("currículo arquivado")
    return ResumeFit(resume.id, resume.label, _weighted(components), components, covered, missing, notes)


def _band(text: str) -> str:
    return "staff" if seniority_from_title(text) in _STAFF_LEVELS else "core"


def _specializations(profile: Profile) -> list[str]:
    found = []
    for fact in profile.specializations:
        if not fact.confirmed:
            continue
        parts = {part for part in norm(fact.value).split() if len(part) > 1}
        if parts and parts <= _CRAFT_SPECS:
            continue
        found.append(fact.value)
    return found


def _markers(spec: str) -> set[str]:
    """Names of this specialization. Aliases come from the shared skill list, not from one person."""
    canonical = taxonomy.canonical_skill(spec) or spec
    skill = taxonomy._by_name().get(canonical)
    names = [spec, canonical]
    if skill:
        names.extend(alias for alias in (*skill.aliases, *skill.case_sensitive) if "\\" not in alias and "(" not in alias)
    markers = set()
    for name in names:
        folded = norm(name)
        if not folded:
            continue
        markers.add(folded)
        if " " not in folded and len(folded) >= 3:
            markers.add(folded)
    return markers


def _emphasis(text: str, profile: Profile) -> str:
    """General, unless the title itself names a specialization this person confirmed."""
    tokens = set(norm(text).split())
    padded = f" {norm(text)} "
    best, hits = "general", 0
    for spec in _specializations(profile):
        score = 0
        for marker in _markers(spec):
            if " " in marker:
                score += 2 if f" {marker} " in padded else 0
            elif marker in tokens:
                score += 1
        if score > hits:
            best, hits = norm(taxonomy.canonical_skill(spec) or spec), score
    return best if hits else "general"


def lane_key(label: str, roles: list[str], language: str | None, profile: Profile) -> tuple[str, str, str]:
    """Language, seniority band and emphasis. One saved resume covers every job in the same lane."""
    text = " ".join([label or "", *(roles or [])])
    return ((language or ""), _band(text), _emphasis(text, profile))


def job_lane(job: Job, profile: Profile) -> tuple[str, str, str]:
    """Read the title only. A tool named in the description does not start a new resume."""
    return ((job.language or "pt"), _band(job.title), _emphasis(job.title, profile))


def same_lane(left: tuple[str, str, str], right: tuple[str, str, str]) -> bool:
    return left == right


def _lane_role(profile: Profile, prefs: dict | None, emphasis: str, band: str) -> str:
    if emphasis != "general":
        role = next((spec for spec in _specializations(profile) if norm(taxonomy.canonical_skill(spec) or spec) == emphasis), emphasis)
    else:
        roles = [str(role) for role in ((prefs or {}).get("target_roles") or []) if str(role).strip()]
        role = next((item for item in roles if _band(item) == band), "")
        if not role and band == "core":
            role = roles[0] if roles else ""
        if not role:
            titles = [exp.title for exp in profile.confirmed_experiences()]
            role = next((title for title in titles if _band(title) == band), "") or (titles[0] if titles else "Software Engineer")
    if band == "staff" and _band(role) != "staff":
        return f"Staff {role}"
    return role


def _lane_focus(profile: Profile, emphasis: str) -> list[str]:
    ordered: list[str] = []
    for exp in profile.confirmed_experiences():
        for tech in exp.technologies:
            name = taxonomy.canonical_skill(tech) or tech
            if name not in ordered:
                ordered.append(name)
    for fact in profile.hard_skills:
        if not fact.confirmed:
            continue
        name = taxonomy.canonical_skill(fact.value) or fact.value
        if name not in ordered:
            ordered.append(name)
    specialty_categories = set()
    for spec in _specializations(profile):
        canonical = taxonomy.canonical_skill(spec)
        if canonical:
            specialty_categories.add(taxonomy.category_of(canonical))
    if emphasis == "general":
        return [skill for skill in ordered if taxonomy.category_of(skill) not in specialty_categories][:12]
    lead = [skill for skill in ordered if taxonomy.category_of(skill) in specialty_categories]
    canonical = taxonomy.canonical_skill(emphasis)
    if canonical and canonical not in lead:
        lead.insert(0, canonical)
    rest = [skill for skill in ordered if skill not in lead]
    return (lead + rest)[:12]


def _suggestion(job: Job, profile: Profile, prefs: dict | None) -> dict:
    language, band, emphasis = job_lane(job, profile)
    focus = _lane_focus(profile, emphasis)
    experiences = [exp.id for exp in profile.confirmed_experiences() if not focus or exp.skills() & set(focus)]
    return {"focus_skills": focus, "experience_ids": experiences, "language": language,
            "target_role": _lane_role(profile, prefs, emphasis, band),
            "lane": {"language": language, "band": band, "emphasis": emphasis}}


def _lane_label(lane: tuple[str, str, str]) -> str:
    language, band, emphasis = lane
    seniority = "staff" if band == "staff" else "sênior e níveis próximos"
    focus = "generalista" if emphasis == "general" else emphasis
    return f"{focus}, {seniority}, {language or 'idioma não informado'}"


def select_resume(job: Job, profile: Profile, resumes: list[ResumeRecord], config: dict,
                  prefs: dict | None = None) -> ResumeDecision:
    """Reuse a resume unless it would tell the wrong story for this title.

    A new file is justified only when no saved resume matches the posting language,
    the level the title claims (staff, principal or lead versus the other levels),
    and a specialization the title names in this person's own profile. Extra tools
    in one description are gaps, not a reason to write another resume.
    """
    threshold = float(config["resumes"]["reuse_threshold"])
    suggestion = _suggestion(job, profile, prefs)
    wanted = job_lane(job, profile)
    active = [resume for resume in resumes if not resume.archived]
    ranking = sorted((evaluate_resume(job, profile, resume) for resume in active),
                     key=lambda fit: fit.score, reverse=True)
    if not ranking:
        return ResumeDecision("no_resumes", None, [], threshold, None,
                              "Nenhum currículo na biblioteca. Gere uma versão para este tipo de vaga; "
                              "as próximas vagas do mesmo tipo reutilizam essa versão.", suggestion)
    by_id = {resume.id: resume for resume in active}
    kind = _lane_label(wanted)
    same = [fit for fit in ranking if same_lane(lane_key(by_id[fit.resume_id].label, by_id[fit.resume_id].target_roles,
                                                        by_id[fit.resume_id].language, profile), wanted)]
    best = same[0] if same else ranking[0]
    if same:
        decision = "reuse" if best.score >= threshold else "reuse_with_gaps"
        return ResumeDecision(decision, best, ranking, threshold, 0.0,
                              f"Reutilizar '{best.resume_id}' para vagas deste tipo ({kind}), adequação {best.score:.0%}. "
                              "Outra vaga do mesmo tipo usa este currículo; não crie um arquivo por anúncio.",
                              suggestion)
    if not suggestion["focus_skills"]:
        return ResumeDecision("nothing_to_highlight", best, ranking, threshold, 0.0,
                              "O perfil não tem habilidades confirmadas para uma versão nova. "
                              f"Melhor opção existente: '{best.resume_id}' ({best.score:.0%}).", suggestion)
    return ResumeDecision("propose_new", best, ranking, threshold, None,
                          f"Não há currículo para vagas deste tipo ({kind}). "
                          f"Crie um, com o papel '{suggestion['target_role']}', e reutilize nas próximas. "
                          f"O mais próximo hoje é '{best.resume_id}' ({best.score:.0%}).", suggestion)
