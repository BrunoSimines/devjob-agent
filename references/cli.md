# CLI reference

Global options: `--home <dir>` (or `DEVJOB_HOME`), `--json`.

| Command | Purpose |
|---|---|
| `help [group]` | list every command with a one-line description (generated from the CLI itself) |
| `prompts list` | list flows and the versioned prompt files each one loads |
| `prompts load <flow>` | load those prompt files from disk for this run |
| `init` | create data dir, database, `config.yaml`, `preferences.yaml` |
| `doctor` | check installation and preferences |
| `profile import <file> [--text-only] [--structured <json>] [--force]` | resume to draft profile |
| `profile review` / `accept` / `discard` | review and consolidate the draft |
| `profile show` / `status` | show profile; register manual edits; list outdated resumes |
| `profile confirm <value>` / `reject <value>` | resolve inferred facts |
| `profile add <kind> <value> [--level]` | user-declared fact |
| `prefs show` / `prefs set <key> <yaml>` | preferences |
| `companies add <url or slug> [--provider] [--name] [--region eu] [--no-verify]` | register a board |
| `companies list [--all]` / `remove <provider> <slug>` | manage boards |
| `companies detect <careers url> [--add]` | find boards embedded in a careers page |
| `companies import <file.yaml>` | bulk add (see `examples/companies.example.yaml`) |
| `discover plan [--refresh]` | build web queries for the host to run |
| `discover ingest <file.json>` | normalize, dedupe and verify host search results, without matching |
| `discover show [--detail]` | compact diagnosis, or the technical log |
| `discover fetch [--refresh]` | optional Brave Search when the user configured a key |
| `search [--query] [--limit] [--refresh] [--remote] [--seniority ...] [--min-salary --currency --period --contract] [--provider] [--company] [--include-seen]` | refresh registered boards, then match and present |
| `match [job ids...]` | recompute compatibility |
| `jobs list [--status] [--all]` / `show <id>` / `history <id>` | saved jobs |
| `jobs add-url <url>` / `import <file.json>` | add jobs found elsewhere |
| `jobs annotate <id> <file.json>` | replace extracted requirements with a reviewed analysis |
| `jobs shortlist <id>` / `ignore <id> [--undo]` | select or hide jobs |
| `resumes list` / `show <id>` / `add <file> --label [--role] [--language]` | library |
| `resumes select <job id>` | best saved resume for a job |
| `resumes generate (--job <id> \| --focus ... --role ...) [--language] [--force]` | draft a new version |
| `resumes drafts` / `check <draft>` / `approve <draft> [--docx] [--force]` / `discard <draft>` | draft lifecycle |
| `resumes outdated` / `archive <id>` | maintenance |
| `prepare <job id> [--resume <id>] [--again]` | prepared application package (nothing sent) |
| `applications list` / `show <id>` / `status <id> <status> [--evidence] [--note]` | tracking |
| `apply <id>` | not available in this version (modes 2 and 3) |

Job ids look like `greenhouse:<token>:<id>`, `lever:<site>:<id>`, `inhire:<tenant>:<id>`, `web:<company>:<hash>`. Any unique fragment of the id, or the job URL, is accepted.

Statuses: `discovered`, `shortlisted`, `prepared`, `submitted`, `interviewing`, `rejected`, `offer`, `closed`.
