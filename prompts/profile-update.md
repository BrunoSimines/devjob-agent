---
id: profile-update
version: 1
---

# Incremental profile update

Use this file when the person adds or corrects professional history: a new job, a new skill, a finished role, a certification, a language, or a fix to something already stored. This updates `profile.md`. It does not rewrite prompt files, the theme, or a resume that was already copied into an application.

## What this operation is

Take the new facts the person states, or the new resume they provide, and merge them into the existing profile. Do not rebuild the profile from memory of an earlier chat. Read the current profile with `devjob profile show --json` or `devjob profile status --json` first.

## A new experience stated in conversation

1. Repeat the fact back: title, company, dates, location, and the achievements the person actually said.
2. Ask for anything required that they did not say (at least start date and whether the role is current). Do not invent the rest.
3. If they hand you a new resume file, switch to `prompts/profile-extraction.md` for that file and let the CLI merge it. Do not paste the old profile over the new file.
4. If they are only adding a skill, language, specialization, or certification, use `devjob profile add <kind> "<value>"`. That records source `user`.
5. Show the proposed change and wait for approval before `devjob profile accept` when a draft was produced.
6. Confirm or reject each pending inference. Do not leave an inference in the confirmed set.

## A correction

If the person says a stored company, title, date, or tool is wrong, update that fact. Do not keep the previous wording because it was already in the profile. Show the before and after.

## Employment

Changing a job does not by itself change the current employer. Ask. A new role with an open end date is a question: is this the current employer, or is the person unemployed? Use the employment commands in `prompts/guardrails.md`. Do not start a search while employment status is `unknown`.

## Resumes already stored

`devjob profile status --json` lists generated resumes that may no longer match the profile. Tell the person which ones look outdated. Do not edit a resume that was used in a prepared or submitted application. Those files stay as sent. A new document, if the person wants one, is a new library version produced later by the resume flow, using the current prompts and the current theme.

## Boundaries

- Do not add employers, titles, dates, numbers, or tools the person did not state and that are not in a resume file they just provided.
- Do not modify `prompts/`, `config/resume-theme.yaml`, or program files. Dissatisfaction with the profile is not developer mode.
- Do not put this person's employers or tools into the prompt files.
- Preferences (target roles, salary, location, work model) are `preferences.yaml`, updated with `devjob prefs set`. They are not profile facts.
