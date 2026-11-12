---
id: search-planning
version: 1
---

# Search planning

Use this file to decide which queries to run. Discovery and matching are separate. Do not stop after the first results. Do not scrape a general web search engine's result page by hand. The host's web search tool runs the queries. The Python program cannot call that tool.

## Before any query

1. Employment must be confirmed. If `devjob employment show` still says unknown, stop and follow the employment rules in `prompts/guardrails.md`.
2. Run `devjob discover context --json`. That JSON is the only personal context you may use to write queries. It omits the person's name, e-mail, and phone.
3. Write related titles yourself from that JSON and from the target roles in preferences. The program does not invent professions. Save the plan with `devjob discover save-plan <file>`.
4. `devjob discover plan --json` returns the saved plan, or a literal plan made only from the person's own words.

## How to write a query

- Use role, skills, and location only. Never include the person's name, e-mail, phone, or any employer listed in `do_not_query_companies`.
- Priority companies come from `companies.priority`. They add company queries. They never replace the general search.
- Cover more than one wording of the target role when the profile and preferences support it. Do not invent a profession the person did not claim and that the context does not support.
- Stay inside the query budget the CLI reports. Cached queries can be skipped. A cache hit is not a source failure.
- A failed query is recorded as `"status": "failed"` with the reason. Do not drop it silently and do not invent results for it.

## Running the search

Run each query that is not marked `cached` with the host web search. In Cursor that tool is WebSearch. In Claude Code use its WebSearch tool. If web search is unavailable, say so and continue with the boards already registered. That is a missing search, not a source failure.

Write the host results to a JSON file inside the data directory and run `devjob discover ingest <file> --json`. Shape:

```json
{"queries": [{"id": "", "text": "", "strategy": "", "company": null, "status": "completed", "error": null, "results": [{"title": "", "url": "", "snippet": ""}]}]}
```

Copy titles and URLs from the results. Do not invent salary, company, or URL. A careers home page is a lead, not a fake job. `status` is `completed` or `failed`.

## Republished ads

A republisher is stored only as a clue (`reposts`: company and title, no URL). For each item in `reposts`, search for that title on the employer's site and on the official boards named in `prompts/guardrails.md`. Priority companies come first. Stop after 8 of these follow-up queries. Ingest only the official page. Do not ingest the republisher again. If the official page is not found, say so. Do not show the republisher's URL.

## After ingest

Run `devjob search --json`. It ranks what was stored and refreshes registered Greenhouse, Lever, and InHire boards. Flags such as `--remote` apply only to this search. Offer to save them as preferences if the person wants them kept.

Then follow `prompts/job-analysis.md` for postings whose extracted requirements look wrong, and `prompts/job-matching.md` to explain the ranking. Show the CLI tables. Do not add jobs to reach a round number.
