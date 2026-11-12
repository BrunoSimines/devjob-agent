# Discovering job sources

Discovery is a separate pipeline from matching:

`discover → fetch → normalize → deduplicate → verify`, then `match → present`.

The program writes the queries (`devjob discover plan`). The host runs them with its own web search (Cursor WebSearch or Claude Code WebSearch) and returns the hits (`devjob discover ingest`). Python does not call those tools and does not scrape Google. Brave Search is optional: set `search.discovery.provider` to `brave` and the user's key in `DEVJOB_BRAVE_API_KEY`. Without that key, `devjob discover fetch` reports `native_required` and the rest of the search still runs.

`companies.priority` adds career-page queries. It does not limit the search to those companies. The search tries to show 20 jobs and merges priority companies with the other companies that already passed the bar. A result is shown only when the link is the employer's own site or a board that employer runs (Greenhouse, Lever, Ashby, InHire, Gupy, SmartRecruiters, Workday). A page that republishes the ad is a clue: the program keeps the company and the title, not the URL. The host then searches that title on the employer's site and official boards, and only that page is imported. If the company's page is not found, the report says so and the other site is not given to the person. After the tables, each priority company is reported from the jobs themselves: in the list, found and left out, discarded by the candidate's rules, seen only on another site, none found, source inaccessible, or query not finished.

Supported public APIs still query **one company at a time**. Other career sites are discovered from the web results; a dedicated connector is only worth adding when a documented public API covers more than the page itself.

| Provider | Board URL pattern | API used by the CLI (documented, public, read-only) |
|---|---|---|
| Greenhouse | `https://job-boards.greenhouse.io/<token>` (or `boards.greenhouse.io`) | `GET https://boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true` |
| Lever | `https://jobs.lever.co/<site>` (EU: `jobs.eu.lever.co`) | `GET https://api.lever.co/v0/postings/<site>?mode=json` |
| InHire | `https://<tenant>.inhire.app/vagas` | `GET https://api.inhire.app/job-posts/public/pages` with header `X-Tenant: <tenant>` |

## Finding boards with web search

Use the web search tool of the host (Claude Code / Cursor). Queries contain only role, skills and location. Examples:

- `site:job-boards.greenhouse.io java backend remote brazil`
- `site:jobs.lever.co "senior backend" java remote latam`
- `site:inhire.app vagas desenvolvedor java remoto`
- `"<company name>" careers` to find a known company's careers page

For each result:
- Board or job URL on a supported host: `devjob companies add <url>` (the CLI validates the board through the API).
- A company careers page on its own domain: `devjob companies detect <url> --add` (looks for embedded Greenhouse/Lever/InHire boards).
- A single job on a supported host: `devjob jobs add-url <url>` (fetched through the API, verified).
- A single job page elsewhere: `devjob jobs add-url <url>` reads schema.org `JobPosting` data when the page has it; otherwise import it as below.

Respect each site's terms. Do not scrape pages that require login and do not retry blocked requests.

## Importing postings found on the web

Write a JSON list and run `devjob jobs import <file>`. Required: `title`, `company`, `url`. Copy values verbatim from the page; leave out anything the page doesn't state.

```json
[
  {
    "title": "Senior Backend Engineer",
    "company": "Example Co",
    "url": "https://example.com/careers/123",
    "location": "Remote - Brazil",
    "work_model": "remote",
    "description": "Full text copied from the page",
    "salary": {"min": 18000, "max": 22000, "currency": "BRL", "period": "month", "evidence": "R$ 18.000 a R$ 22.000/mês"},
    "posted_at": "2026-11-01",
    "posted_at_evidence": "Publicada em 01/11/2026",
    "found_via": "web search"
  }
]
```

Imported postings stay `unverified`. If the same job is later found through an official API, the records are merged and the verified data wins.
