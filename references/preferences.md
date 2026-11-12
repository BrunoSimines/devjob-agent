# preferences.yaml keys

Set with `devjob prefs set <key> '<yaml value>'`. Show with `devjob prefs show --json`.

| Key | Example | Notes |
|---|---|---|
| `target_roles` | `[Backend Engineer, Engenheiro de Software Backend]` | compared with job titles |
| `seniority.levels` | `[senior, staff]` | intern, junior, mid, senior, staff, principal, lead, manager |
| `seniority.eliminatory` | `false` | |
| `primary_stack` | `[Java, Spring Boot]` | |
| `specializations` | `[IAM]` | |
| `hard_skills_to_use` | `[Kafka, Kubernetes]` | |
| `soft_skills` | `[Mentoria]` | |
| `location.country` / `location.city` | `BR` / `São Paulo` | used for remote region checks and on-site jobs. The city comes from this file: a remote job that names it counts as that country |
| `location.accept_relocation` | `false` | |
| `location.only_country` | `false` | when `true`, a remote job that does not indicate `location.country` is eliminated. Default keeps jobs in other countries as uncertain |
| `location.focus` | `mixed` | `home` keeps the list in `location.country`. `abroad` does not reserve space by country. `mixed` splits the list |
| `location.home_share` | `70` | with `focus: mixed`, percent of the list that names that country. The rest may be elsewhere, and an empty side is not filled by the other |
| `location.eliminatory` | `true` | on-site/hybrid elsewhere is eliminated |
| `work_model.accepted` | `[remote, hybrid]` | remote, hybrid, onsite |
| `work_model.eliminatory` | `true` | |
| `contract_types.accepted` | `[clt, pj, international]` | clt, pj, international, contractor |
| `contract_types.eliminatory` | `false` | |
| `salary.minimums` | `[{contract: clt, currency: BRL, amount: 18000, period: month}]` | one entry per contract type/currency; no FX conversion |
| `salary.eliminatory` | `true` | only when the job states a salary below the minimum |
| `languages.working` | `[{language: en, level: C1}]` | fallback when the profile has no level |
| `languages.eliminatory` | `false` | only explicit language requirements eliminate |
| `employment.status` / `employment.current` / `employment.previous` | confirmed by the person | `unknown` blocks a personalized search. The last resume job is not assumed current. `exclude_current: false` is rejected |
| `employment.exclude_past` / `employment.allowed_past` | `true` / `[]` | past employers are hidden until one name is allowed back. The current employer cannot be allowed |
| `companies.desired` / `companies.blocked` / `companies.priority` | `[Acme]` | `blocked` adds exclusions beyond the employment history. `priority` adds career-page queries and does not limit the search |
| `sources.priority` | `[inhire, greenhouse]` | these boards fill the list before the others. `[]` keeps score order only. The default prefers InHire and Greenhouse |
| `dealbreakers.keywords` | `["security clearance"]` | any occurrence eliminates |
| `nice_to_have.keywords` | `[kafka, event-driven]` | adds to the preferences score |

Eliminatory rules never apply to missing information: an unknown salary or work model becomes an "uncertain" item, not an elimination.

Per-search overrides that don't change the file: `--remote`, `--seniority`, `--min-salary/--currency/--period/--contract`.
