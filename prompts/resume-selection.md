---
id: resume-selection
version: 1
---

# Resume selection

Use this file when the person wants a resume for a job, or asks which saved resume to send. One resume covers every posting that asks for the same story. Do not create a file per advertisement.

## Steps

1. The job must already be stored. If it is not, ingest the official page first. Do not select a resume for a republisher URL.
2. Run `devjob resumes select <job id> --json`.
3. Explain the decision in the person's language, using the CLI text. Do not invent a different decision.

## Decisions

- `reuse` and `reuse_with_gaps`: this file is the one for that kind of job. Use it again next time. Gaps are tools the person has that this file does not highlight, or tools the posting wants that the person does not have. A missing tool is not a new resume.
- `nothing_to_highlight`: the profile has no confirmed skills to support a new version. Offer the closest existing file. Do not draft one.
- `propose_new`: there is no saved resume for this kind of job yet.
- `no_resumes`: the library is empty. A first version is justified if the person agrees.

A new version is justified only when every saved resume would misrepresent the person: wrong language, a title that claims staff, principal, or lead while the resume does not (or the reverse), or a title that names a specialization confirmed on this person's profile while no resume is aimed at it. A tool that appears only in the description is a gap, not a new resume. Do not invent a resume kind from one person's stack, and do not name kinds after a single tool.

## Labels

Existing resumes the person already has: `devjob resumes add <file> --label "<focus>" --role "<target role>"`. The label and the role decide the kind. A generalist label must not be the name of a specialization.

## When a new draft is allowed

Only for `propose_new` or `no_resumes`, and only if the person agrees. Then load `prompts/resume-generation.md` and `config/resume-theme.yaml` through `devjob prompts load resume-generation`. The draft's role is the kind of job, not the posting's exact title. After the draft exists, load `prompts/resume-validation.md` before approval.

If the decision is `reuse` or `reuse_with_gaps`, stop. Do not generate. Tell the person which file will be reused.

## Shortlist

`devjob jobs shortlist <id>` for jobs the person picks. `devjob jobs ignore <id>` for jobs they reject. An ignored job is not recommended again.
