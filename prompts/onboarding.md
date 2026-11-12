---
id: onboarding
version: 1
---

# Onboarding

Use this file for a first setup and whenever the profile or the preferences are missing facts the search needs. Ask only for gaps. Do not ask again about a fact the profile or the preferences already confirm.

## Order

1. Run `devjob doctor --json`. If it fails, the installer was not run. Point to `README.md` (`python scripts/install.py`) and stop.
2. If there is no profile, ask for the resume path and follow `prompts/profile-extraction.md`.
3. Read `devjob prefs show --json`. Translate what the person says into keys and set them with `devjob prefs set <key> '<yaml value>'`. The key list is `references/preferences.md`. Read that file from disk. Do not invent keys.
4. Confirm employment before the first personalized search, using the rules in `prompts/guardrails.md`.

## Questions to ask when the answer is not already stored

Ask in the person's language. Each question may be declined. Record a decline and move on. Do not fill the gap yourself.

- Target roles: the titles they want to be found for. Use their words. Do not rename a role into a more senior title.
- Areas they want to explore, and areas they want to leave out.
- Work model: remote, hybrid, onsite, or a combination. Ask whether each constraint is eliminatory.
- Locations, and where the list should focus: `location.focus` is `home` (only that country), `abroad` (no country quota), or `mixed`. For `mixed`, set `location.home_share` to the percent of results that should name `location.country`. Suggest 70 if they have no number. Leave `location.only_country` false when they want a mixed list, because `true` discards every job outside the country.
- Contract types they accept, and which are eliminatory.
- Compensation: currency, amount, period, and contract, only if they state a minimum. Never invent a salary.
- Companies to prioritize, companies to avoid, and whether a past employer may appear again.
- Languages they will work in, if the profile does not already say.

## What not to ask

- Do not ask them to restate the work history that is already confirmed in the profile.
- Do not ask them to name prompt files, theme files, or internal commands.
- Do not ask them to pay for a search API. Brave Search is optional and is used only when they set `search.discovery.provider: brave` and supply their own key.

## Done

Onboarding is done when a profile exists, employment is confirmed or the person is recorded as unemployed, and the person has had a chance to set or decline the preferences above. Then stop. Do not start a search inside this step unless they asked for jobs in the same message. If they did, continue with `prompts/search-planning.md`.
