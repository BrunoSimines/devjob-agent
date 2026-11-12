"""Skill, soft-skill and language vocabulary.

Detection is keyword based and deliberately conservative. Implications are
strict "is-a" relations only (experience with EKS proves Kubernetes; Spring
Boot does not prove Java because it can be used with Kotlin).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from devjob.textutil import norm

CATEGORY_LABELS = {
    "languages_frameworks": "Linguagens e frameworks",
    "cloud": "Cloud",
    "databases": "Bancos de dados",
    "tools": "Ferramentas e infraestrutura",
    "architecture": "Arquitetura e práticas",
    "security": "Segurança e identidade",
    "other": "Outras",
}
CATEGORY_LABELS_EN = {
    "languages_frameworks": "Languages and frameworks",
    "cloud": "Cloud",
    "databases": "Databases",
    "tools": "Tools and infrastructure",
    "architecture": "Architecture and practices",
    "security": "Security and identity",
    "other": "Other",
}


@dataclass(frozen=True)
class Skill:
    name: str
    category: str
    aliases: tuple[str, ...] = ()
    case_sensitive: tuple[str, ...] = ()
    implies: tuple[str, ...] = ()


def _s(name, category, *aliases, cs=(), implies=()):
    return Skill(name, category, tuple(aliases), tuple(cs), tuple(implies))


SKILLS: list[Skill] = [
    # Linguagens e frameworks
    _s("Java", "languages_frameworks", "java"),
    _s("Kotlin", "languages_frameworks", "kotlin"),
    _s("Spring", "languages_frameworks", "spring framework", "spring"),
    _s("Spring Boot", "languages_frameworks", "spring boot", "springboot", implies=("Spring",)),
    _s("Quarkus", "languages_frameworks", "quarkus", implies=("Java",)),
    _s("Micronaut", "languages_frameworks", "micronaut"),
    _s("Hibernate", "languages_frameworks", "hibernate", "jpa"),
    _s("Python", "languages_frameworks", "python"),
    _s("Django", "languages_frameworks", "django", implies=("Python",)),
    _s("Flask", "languages_frameworks", "flask", implies=("Python",)),
    _s("FastAPI", "languages_frameworks", "fastapi", implies=("Python",)),
    _s("JavaScript", "languages_frameworks", "javascript", "ecmascript"),
    _s("TypeScript", "languages_frameworks", "typescript", implies=("JavaScript",)),
    _s("Node.js", "languages_frameworks", r"node\.?js", "nodejs", implies=("JavaScript",)),
    _s("NestJS", "languages_frameworks", "nestjs", r"nest\.js", implies=("Node.js",)),
    _s("React", "languages_frameworks", r"react\.js", "reactjs", "react native", cs=("React",)),
    _s("Next.js", "languages_frameworks", r"next\.js", "nextjs", implies=("React",)),
    _s("Angular", "languages_frameworks", "angular"),
    _s("Vue.js", "languages_frameworks", r"vue\.?js", "vue"),
    _s("Go", "languages_frameworks", "golang", cs=("Go",)),
    _s("Rust", "languages_frameworks", cs=("Rust",)),
    _s("C#", "languages_frameworks", "c#", "csharp"),
    _s(".NET", "languages_frameworks", r"\.net", r"\.net core", r"asp\.net", "dotnet"),
    _s("C++", "languages_frameworks", r"c\+\+", "cpp"),
    _s("Ruby", "languages_frameworks", "ruby"),
    _s("Ruby on Rails", "languages_frameworks", "ruby on rails", "rails", implies=("Ruby",)),
    _s("PHP", "languages_frameworks", "php"),
    _s("Laravel", "languages_frameworks", "laravel", implies=("PHP",)),
    _s("Scala", "languages_frameworks", "scala"),
    _s("Elixir", "languages_frameworks", "elixir"),
    _s("Swift", "languages_frameworks", cs=("Swift",)),
    # Cloud
    _s("AWS", "cloud", "aws", "amazon web services"),
    _s("GCP", "cloud", "gcp", "google cloud", "google cloud platform"),
    _s("Azure", "cloud", "azure", "microsoft azure"),
    _s("AWS Lambda", "cloud", "aws lambda", "lambda functions", implies=("AWS", "Serverless")),
    _s("EKS", "cloud", "eks", "amazon eks", implies=("AWS", "Kubernetes")),
    _s("GKE", "cloud", "gke", implies=("GCP", "Kubernetes")),
    _s("AKS", "cloud", "aks", implies=("Azure", "Kubernetes")),
    # Bancos de dados
    _s("SQL", "databases", "sql"),
    _s("NoSQL", "databases", "nosql"),
    _s("PostgreSQL", "databases", "postgresql", "postgres", implies=("SQL",)),
    _s("MySQL", "databases", "mysql", implies=("SQL",)),
    _s("Oracle Database", "databases", "oracle database", "oracle db", r"pl/sql", implies=("SQL",)),
    _s("SQL Server", "databases", "sql server", "mssql", implies=("SQL",)),
    _s("MongoDB", "databases", "mongodb", "mongo", implies=("NoSQL",)),
    _s("Redis", "databases", "redis"),
    _s("Cassandra", "databases", "cassandra", implies=("NoSQL",)),
    _s("DynamoDB", "databases", "dynamodb", implies=("NoSQL", "AWS")),
    _s("Elasticsearch", "databases", "elasticsearch", "opensearch"),
    # Ferramentas e infraestrutura
    _s("Docker", "tools", "docker"),
    _s("Kubernetes", "tools", "kubernetes", "k8s"),
    _s("Helm", "tools", "helm chart", "helm charts", cs=("Helm",)),
    _s("Terraform", "tools", "terraform"),
    _s("Ansible", "tools", "ansible"),
    _s("OpenShift", "tools", "openshift", implies=("Kubernetes",)),
    _s("Kafka", "tools", "kafka", "apache kafka"),
    _s("RabbitMQ", "tools", "rabbitmq"),
    _s("Amazon SQS", "tools", "sqs", implies=("AWS",)),
    _s("CI/CD", "tools", r"ci/cd", r"ci\s*/\s*cd", "continuous integration", "continuous delivery",
       "integração contínua"),
    _s("Jenkins", "tools", "jenkins", implies=("CI/CD",)),
    _s("GitHub Actions", "tools", "github actions", implies=("CI/CD",)),
    _s("GitLab CI", "tools", "gitlab ci", "gitlab-ci", implies=("CI/CD",)),
    _s("Argo CD", "tools", "argocd", "argo cd"),
    _s("Git", "tools", "git"),
    _s("Linux", "tools", "linux"),
    _s("Prometheus", "tools", "prometheus"),
    _s("Grafana", "tools", "grafana"),
    _s("Datadog", "tools", "datadog"),
    _s("OpenTelemetry", "tools", "opentelemetry", "otel"),
    _s("Maven", "tools", "maven"),
    _s("Gradle", "tools", "gradle"),
    _s("JUnit", "tools", "junit"),
    _s("Spark", "tools", "apache spark", "pyspark", cs=("Spark",)),
    _s("Airflow", "tools", "airflow"),
    # Arquitetura e práticas
    _s("Microservices", "architecture", "microservices", "microserviços", "microservicos", "microsserviços",
       "microsservicos", "micro-services", "microservice"),
    _s("Event-driven architecture", "architecture", "event-driven", "event driven", "orientada a eventos",
       "event sourcing"),
    _s("Domain-Driven Design", "architecture", "domain-driven design", "domain driven design", "ddd"),
    _s("REST APIs", "architecture", "restful", "rest api", "rest apis", "apis rest", "api rest",
       cs=("REST",)),
    _s("GraphQL", "architecture", "graphql"),
    _s("gRPC", "architecture", "grpc"),
    _s("Distributed systems", "architecture", "distributed systems", "sistemas distribuídos",
       "sistemas distribuidos"),
    _s("System design", "architecture", "system design", "software architecture", "arquitetura de software"),
    _s("Clean Architecture", "architecture", "clean architecture", "arquitetura limpa", "hexagonal architecture",
       "arquitetura hexagonal"),
    _s("Serverless", "architecture", "serverless"),
    _s("TDD", "architecture", "tdd", "test-driven development", "test driven development"),
    _s("Observability", "architecture", "observability", "observabilidade"),
    # Segurança e identidade
    _s("IAM", "security", "iam", "identity and access management", "gestão de identidade",
       "gestão de identidades e acessos", "identity management"),
    _s("OAuth 2.0", "security", "oauth", r"oauth\s*2(?:\.0)?"),
    _s("OpenID Connect", "security", "openid connect", "oidc"),
    _s("SAML", "security", "saml"),
    _s("Keycloak", "security", "keycloak"),
    _s("LDAP", "security", "ldap", "active directory"),
    _s("Okta", "security", "okta"),
    _s("Auth0", "security", "auth0"),
    _s("SSO", "security", "sso", "single sign-on", "single sign on"),
    _s("Application security", "security", "appsec", "application security", "owasp"),
]


@dataclass(frozen=True)
class SoftSkill:
    name: str
    aliases: tuple[str, ...]
    evidence_patterns: tuple[str, ...] = field(default=())


SOFT_SKILLS: list[SoftSkill] = [
    SoftSkill("Liderança", ("leadership", "liderança", "lideranca", "technical leadership", "liderança técnica"),
              (r"\bled\b", r"\bleading\b", r"\bliderei\b", r"\bliderou\b", r"\bliderando\b", r"\bcoordenei\b",
               r"\bmanaged (?:a |the )?team\b", r"\bgerenciei (?:um |uma |o |a )?(?:time|equipe)\b")),
    SoftSkill("Mentoria", ("mentoring", "mentorship", "mentoria", "coaching"),
              (r"\bmentor(?:ed|ing)?\b", r"\bmentorei\b", r"\bonboard(?:ed|ing)\b")),
    SoftSkill("Comunicação", ("communication", "communication skills", "comunicação", "comunicacao"),
              (r"\bpresented\b", r"\bapresentei\b", r"\bpalestr\w*", r"\btech talks?\b")),
    SoftSkill("Trabalho em equipe", ("teamwork", "team player", "trabalho em equipe")),
    SoftSkill("Resolução de problemas", ("problem solving", "problem-solving", "resolução de problemas",
                                         "resolucao de problemas"),
              (r"\broot cause\b", r"\bcausa raiz\b", r"\btroubleshoot\w*")),
    SoftSkill("Gestão de stakeholders", ("stakeholder management", "gestão de stakeholders",
                                         "gestao de stakeholders"),
              (r"\bstakeholders?\b",)),
    SoftSkill("Colaboração", ("collaboration", "colaboração", "colaboracao"),
              (r"\bcross-functional\b", r"\bmultidisciplinar\w*\b", r"\bcollaborat(?:ed|ing) with\b")),
    SoftSkill("Autonomia", ("autonomy", "autonomia", "self-starter", "self-motivated", "proatividade",
                            "proactive")),
    SoftSkill("Adaptabilidade", ("adaptability", "adaptabilidade", "flexibilidade")),
    SoftSkill("Pensamento crítico", ("critical thinking", "pensamento crítico", "pensamento critico")),
    SoftSkill("Ownership", ("ownership", "senso de dono")),
]

_BOUNDARY_BEFORE = r"(?<![A-Za-z0-9+#])"
_BOUNDARY_AFTER = r"(?![A-Za-z0-9+#])"


def _alias_regex(alias: str) -> str:
    # Aliases containing regex syntax are used verbatim; plain ones are escaped.
    if any(ch in alias for ch in "\\[]()?*"):
        body = alias
    else:
        body = re.escape(alias).replace(r"\ ", r"\s+")
    return _BOUNDARY_BEFORE + body + _BOUNDARY_AFTER


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[Skill, re.Pattern, re.Pattern | None]]:
    out = []
    for skill in SKILLS:
        insensitive = "|".join(_alias_regex(a) for a in skill.aliases) if skill.aliases else None
        sensitive = "|".join(_alias_regex(a) + r"(?!-)" for a in skill.case_sensitive) if skill.case_sensitive else None
        out.append((skill,
                    re.compile(insensitive, re.IGNORECASE) if insensitive else None,
                    re.compile(sensitive) if sensitive else None))
    return out


@lru_cache(maxsize=1)
def _by_name() -> dict[str, Skill]:
    return {s.name: s for s in SKILLS}


def _snippet(text: str, start: int, end: int, width: int = 50) -> str:
    return text[max(0, start - width): end + width].replace("\n", " ").strip()


def find_skills(text: str) -> dict[str, str]:
    """Return canonical skill name -> short evidence snippet for each mention."""
    found: dict[str, str] = {}
    if not text:
        return found
    for skill, insensitive, sensitive in _compiled():
        for pattern in (insensitive, sensitive):
            if pattern is None:
                continue
            match = pattern.search(text)
            if match:
                found.setdefault(skill.name, _snippet(text, match.start(), match.end()))
    # "Spring" alone should not be reported when it only appears inside "Spring Boot".
    if "Spring" in found and "Spring Boot" in found:
        remaining = re.sub(r"spring\s*boot", "", text, flags=re.IGNORECASE)
        if not re.search(_alias_regex("spring"), remaining, re.IGNORECASE):
            del found["Spring"]
    return found


@lru_cache(maxsize=1)
def _soft_compiled() -> list[tuple[SoftSkill, re.Pattern, list[re.Pattern]]]:
    return [
        (s, re.compile("|".join(_alias_regex(a) for a in s.aliases), re.IGNORECASE),
         [re.compile(p, re.IGNORECASE) for p in s.evidence_patterns])
        for s in SOFT_SKILLS
    ]


def find_soft_skills(text: str) -> dict[str, str]:
    """Soft skills explicitly named in the text."""
    found: dict[str, str] = {}
    for skill, explicit, _ in _soft_compiled():
        match = explicit.search(text or "")
        if match:
            found[skill.name] = _snippet(text, match.start(), match.end())
    return found


def infer_soft_skills(text: str) -> dict[str, str]:
    """Soft skills suggested by described behaviour (always an inference)."""
    found: dict[str, str] = {}
    for skill, _, patterns in _soft_compiled():
        for pattern in patterns:
            match = pattern.search(text or "")
            if match:
                found[skill.name] = _snippet(text, match.start(), match.end(), 70)
                break
    return found


def canonical_skill(name: str) -> str | None:
    """Map a user-provided name to a known canonical skill, if any."""
    if not name:
        return None
    key = norm(name)
    for skill in SKILLS:
        if norm(skill.name) == key:
            return skill.name
    matches = find_skills(name)
    if len(matches) == 1:
        only = next(iter(matches))
        if len(norm(only)) >= len(key) * 0.5:
            return only
    return None


def canonical_soft_skill(name: str) -> str | None:
    key = norm(name)
    for skill in SOFT_SKILLS:
        if norm(skill.name) == key or any(norm(a) == key for a in skill.aliases):
            return skill.name
    return None


def category_of(name: str) -> str:
    skill = _by_name().get(name)
    return skill.category if skill else "other"


def expand_implications(skills: set[str]) -> dict[str, str]:
    """Return skills proven by more specific ones: implied -> the specific skill."""
    implied: dict[str, str] = {}
    queue = list(skills)
    while queue:
        current = queue.pop()
        skill = _by_name().get(current)
        if not skill:
            continue
        for target in skill.implies:
            if target not in skills and target not in implied:
                implied[target] = current
                queue.append(target)
    return implied


# Idiomas --------------------------------------------------------------------

LANGUAGE_NAMES = {
    "en": ("english", "inglês", "ingles"),
    "pt": ("portuguese", "português", "portugues"),
    "es": ("spanish", "espanhol", "español", "espanol"),
    "fr": ("french", "francês", "frances"),
    "de": ("german", "alemão", "alemao"),
    "it": ("italian", "italiano"),
}
LANGUAGE_LABELS = {"en": "Inglês", "pt": "Português", "es": "Espanhol", "fr": "Francês", "de": "Alemão",
                   "it": "Italiano"}

LEVEL_RANK = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "native": 7}

_LEVEL_WORDS = [
    (("native", "nativo", "nativa", "mother tongue", "língua materna", "lingua materna"), "native"),
    (("proficient", "proficiente", "bilingual", "bilíngue", "bilingue"), "C2"),
    (("fluent", "fluente", "fluência", "fluencia", "fluency", "advanced", "avançado", "avancado"), "C1"),
    (("upper intermediate", "upper-intermediate", "intermediário avançado", "intermediario avancado"), "B2"),
    (("intermediate", "intermediário", "intermediario", "conversational", "conversação"), "B1"),
    (("basic", "básico", "basico", "elementary", "beginner", "iniciante"), "A2"),
]


def language_code(name: str) -> str | None:
    key = norm(name)
    if key in LANGUAGE_NAMES:
        return key
    for code, names in LANGUAGE_NAMES.items():
        if any(norm(n) == key for n in names):
            return code
    return None


@lru_cache(maxsize=1)
def _level_patterns() -> list[tuple[re.Pattern, str]]:
    patterns = [(re.compile(r"(?<![A-Za-z0-9])([ABC][12])(?![A-Za-z0-9])"), "")]
    for words, level in _LEVEL_WORDS:
        patterns.append((re.compile("|".join(_alias_regex(w) for w in words), re.IGNORECASE), level))
    return patterns


def _levels_in(text: str) -> list[tuple[int, str]]:
    found = []
    for pattern, level in _level_patterns():
        for match in pattern.finditer(text or ""):
            found.append((match.start(), level or match.group(1).upper()))
    return found


def parse_level(text: str) -> str | None:
    found = _levels_in(text)
    if not found:
        return None
    cefr = [lvl for _, lvl in found if lvl in LEVEL_RANK and lvl != "native" and len(lvl) == 2]
    return cefr[0] if cefr else min(found)[1]


def find_languages(text: str) -> list[tuple[str, str | None, str]]:
    """Find "<language> <level>" mentions on the same line, using the level word
    closest to each language name. Returns (code, level, line)."""
    results: dict[str, tuple[str, str | None, str]] = {}
    for line in (text or "").splitlines():
        mentions = []
        for code, names in LANGUAGE_NAMES.items():
            pattern = re.compile("|".join(_alias_regex(n) for n in names), re.IGNORECASE)
            for match in pattern.finditer(line):
                mentions.append((match.start(), match.end(), code))
        if not mentions:
            continue
        levels = _levels_in(line)
        for start, end, code in mentions:
            nearest = None
            if levels:
                pos, level = min(levels, key=lambda item: min(abs(item[0] - end), abs(item[0] - start)))
                other_closer = any(abs(pos - s2) < min(abs(pos - end), abs(pos - start))
                                   for s2, _, c2 in mentions if c2 != code)
                nearest = None if other_closer else level
            if code not in results or (nearest and not results[code][1]):
                results[code] = (code, nearest, line.strip()[:160])
    return list(results.values())
