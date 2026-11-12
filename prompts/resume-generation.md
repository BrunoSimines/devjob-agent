---
id: resume-generation
version: 2
---

# Resume generation

Use this file only after `prompts/resume-selection.md` returned `propose_new` or `no_resumes` and the person agreed. The program builds a draft from confirmed profile facts. You may edit wording. You may not edit the design system.

## Content

Run `devjob resumes generate --job <id> [--language en] --json` unless a focus and a role were already agreed without a stored job. The draft's target role is the kind of job, not the posting title.

You may improve clarity, order, and a faithful translation of the summary and the highlights in the draft `resume.md`. You may not add facts. Keep job titles, company names, dates, and the `### Role — Company` headers exactly as written. The verifier matches those headers against the profile.

Write in the draft's language. A translation stays faithful: no new facts, numbers, or tools. Omit a section that has no confirmed facts. Do not add a photo, a logo, an icon, a chart, a skill bar, or a table. Do not add color, font, or size markup.

Include a professional-title line under the name only when a confirmed target role or a headline already stored for this person supplies it. Otherwise omit that line. The contact line is the confirmed contact fields, joined, and nothing else.

Highlights stay traceable to a confirmed highlight. You may fix grammar. You may not merge two achievements into a new claim or introduce a metric that was not stored.

## Markdown the renderer understands

The body is plain Markdown. The renderer, not you, maps it to the theme. Default section order:

1. Name and professional title.
2. Contacts and professional links, in the body of the document, never only in a header or footer.
3. Professional summary.
4. Technical skills.
5. Experience.
6. Education.
7. Certifications and relevant projects, when the profile has them. Languages stay with the other factual sections.

You may reorder sections when the person's profile justifies it. Do not change the visual system to do that.

```
# Full name
Professional title
email · phone · location

## Section
paragraph

### Role — Company
start – end · location
- highlight
```

`#` is the name. The first plain line after the name is the professional title when it is not a contact line. The contact line contains the contact fields. `##` is a section. `### Role — Company` is one experience: the role and the company are separated by ` — `. The next plain line is the date and the location. Lines that start with `-` are bullets. Any other plain line is body text. Do not add HTML, images, emoji, or style attributes.

## Pages

Do not force the resume onto one page. Early-career profiles are often one page. Longer careers are often one or two, and a long history may take more. Do not delete a confirmed experience, shrink type, or tighten spacing to save a page. The renderer keeps a heading with the block that follows it and does not shrink the body below the theme's minimum.

## Presentation

Presentation is not part of the draft. The renderer reads `config/resume-theme.yaml` and applies it deterministically. If this prose and that file ever disagree, the file wins for rendering, and you still must not invent a third set of values. Do not invent fonts, sizes, colors, or spacing. One family is used for the whole document.

The current design system, which the theme file also stores, is:

- Template `minimal-professional`. Default page A4, portrait. US Letter is allowed only when the person's config sets `resumes.page_format` to `Letter`. One column. White background `#FFFFFF`. Margins 1.8 cm on every side. No images, icons, charts, skill bars, gradients, or shadows.
- Font Arial. If Arial is not installed, the renderer tries Calibri, then Aptos, then Liberation Sans, and stops. It does not mix families and it does not pick any other face.
- Full name 20 pt, bold.
- Professional title 11 pt, regular.
- Section titles 11.5 pt, bold.
- Company 11 pt, bold.
- Role 10.5 pt, regular.
- Body and bullets 10.5 pt, regular. Technical skills 10 pt. Education 10.5 pt.
- Contacts 9 pt. Dates and the job location 9.5 pt.
- Line height 1.15.
- Space after the name 4 pt. After contacts 12 pt. Before sections 12 pt. After section titles 5 pt. Between experiences 9 pt. Between bullets 2 pt. Between paragraphs 5 pt.
- Primary text and titles `#202020`. Secondary text `#555555`. Dividers `#D9D9D9`. Background `#FFFFFF`.

Do not write those numbers into the Markdown. Do not bold a whole paragraph. Do not ask for a different font because a posting prefers one. A global scale, if it exists, lives in the theme file and cannot push body text below 10 pt.

## Traceability

The draft records the prompt version and the theme version that were current when it was created. Approval renders the PDF with the theme that is current at approval time and writes that identity next to the new resume. Older resumes and files already copied into applications are left as they are. The person may ask for a regeneration, which creates a new version with the current theme. It does not overwrite a sent document.

## After the draft

Load `prompts/resume-validation.md`. Run `devjob resumes check <draft>`. Show the draft to the person. `devjob resumes approve <draft> [--docx]` only after they approve. A near-duplicate of an existing version is refused. Reuse that version instead.
