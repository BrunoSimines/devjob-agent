---
id: resume-validation
version: 2
---

# Resume validation

Use this file after a draft exists and before `devjob resumes approve`. Also use it when the person asks whether a draft is safe to keep. The CLI verifier is authoritative for facts. This file says what else to reject. Do not approve a draft that fails either check.

## Fact check

Run `devjob resumes check <draft> --json`. Approval also renders the PDF and checks layout against `config/resume-theme.yaml`: selectable text, margins, type sizes, stranded headings, and missing sections. A passing check is not a claim that every applicant tracking system will accept the file.

Errors block approval. The verifier rejects:

- A `### Role — Company` header whose title and company are not a confirmed experience.
- Years on the date line that are not the start or end year stored for that experience.
- A number in the body that does not appear in any confirmed profile fact.
- A technology the taxonomy finds in the draft that is not confirmed on the profile. An inferred-only skill is not enough.

Warnings do not block approval. Tell the person about them. A skill repeated more than eight times is a warning about keyword stuffing. Remove the repetition if they agree, without deleting true uses.

If you edited wording, run check again after the edit. Do not assume an earlier check still applies.

## Structure check

Read `resume.md` and reject the draft yourself when:

- It contains an image, a logo, an icon, a chart, or a skill bar.
- It sets a font, a point size, a color, or a margin. Those belong only to `config/resume-theme.yaml`.
- A section heading is not a `##` line, or an experience is not a `### Role — Company` line, so the renderer cannot apply the theme.
- The contact line adds an e-mail, phone, or link that is not confirmed.
- The professional title claims a level or a specialty the profile and the preferences do not support.
- The language of the draft is not the language requested for this version.
- Empty sections were left in with placeholder text such as "available upon request" or a fabricated sentence.

## What you tell the person

Show the errors, the warnings, and the draft path. Say whether it can be approved. Do not approve it in the same turn you found an error. After they approve and check is clean, run `devjob resumes approve <draft>`. The program renders the PDF and, if requested, the DOCX, using the theme file. You do not format the PDF by hand.

## What validation does not do

It does not update the profile. It does not change prompts or the theme. It does not send the resume. It does not rewrite a resume that is already in the library or already attached to an application. A failed draft is fixed or discarded with `devjob resumes discard <draft>`.
