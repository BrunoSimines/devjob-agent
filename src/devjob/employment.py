"""Who the person works for, and which employers a search must hide.

Names come from confirmed preferences. The last line of a resume is not treated
as the current job. The current employer cannot be turned back on.
"""

from __future__ import annotations

import re
import unicodedata

_LEGAL = {"ltda", "sa", "inc", "llc", "gmbh", "corp", "corporation", "limited", "ltd", "eireli"}


class EmploymentError(ValueError):
    """The employment record cannot be saved as requested."""


def compact(name: str | None) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _tokens(name: str | None) -> list[str]:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = text.split()
    while tokens and tokens[-1] in _LEGAL:
        tokens.pop()
    if len(tokens) >= 2 and tokens[-2:] == ["s", "a"]:
        tokens = tokens[:-2]
    return tokens


def same_employer(left: str | None, right: str | None) -> bool:
    """Same confirmed name, spelling aside. A shared first word is not enough."""
    if not compact(left) or not compact(right):
        return False
    if compact(left) == compact(right):
        return True
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    return bool(left_tokens) and left_tokens == right_tokens


def _entry(value) -> tuple[str, list[str]]:
    if isinstance(value, str):
        return value.strip(), []
    if isinstance(value, dict):
        aliases = [str(item).strip() for item in (value.get("aliases") or []) if str(item).strip()]
        return str(value.get("name") or "").strip(), aliases
    return "", []


def _names(entry: tuple[str, list[str]]) -> list[str]:
    name, aliases = entry
    return [item for item in (name, *aliases) if item]


def matches_employer(company: str | None, entry) -> bool:
    return any(same_employer(company, name) for name in _names(_entry(entry)))


def exclusion_label(company: str | None, prefs: dict) -> str | None:
    """Why this posting stays out. None when it may be recommended."""
    employment = prefs.get("employment") or {}
    current = employment.get("current") or {}
    if matches_employer(company, current):
        return f"empregador atual: {company}"
    allowed = employment.get("allowed_past") or []
    past_open = employment.get("exclude_past", True) is not False
    if past_open and not any(matches_employer(company, name) for name in allowed):
        for previous in employment.get("previous") or []:
            if matches_employer(company, previous):
                return f"ex-empregador: {company}"
    for blocked in (prefs.get("companies") or {}).get("blocked") or []:
        if same_employer(company, str(blocked)):
            return f"empresa bloqueada: {company}"
    return None


def ready_message(prefs: dict) -> str | None:
    status = str((prefs.get("employment") or {}).get("status") or "unknown")
    if status == "unknown":
        return ("Confirme o empregador atual antes de buscar. "
                "Use `devjob employment confirm --current \"Empresa\"` ou `--unemployed`. "
                "A última experiência do currículo não é tratada como emprego atual.")
    return None


def confirm_current(prefs: dict, name: str, aliases: list[str] | None = None) -> dict:
    label = name.strip()
    if not label:
        raise EmploymentError("Informe o nome do empregador atual.")
    updated = _copy(prefs)
    employment = updated["employment"]
    _archive_current(employment)
    employment["previous"] = [item for item in employment.get("previous") or []
                              if not matches_employer(label, item)]
    employment["allowed_past"] = [item for item in employment.get("allowed_past") or []
                                  if not same_employer(item, label)]
    employment["current"] = {"name": label, "aliases": [item.strip() for item in (aliases or []) if item.strip()]}
    employment["status"] = "employed"
    employment["exclude_current"] = True
    return updated


def confirm_unemployed(prefs: dict) -> dict:
    updated = _copy(prefs)
    employment = updated["employment"]
    _archive_current(employment)
    employment["current"] = {"name": "", "aliases": []}
    employment["status"] = "unemployed"
    employment["exclude_current"] = True
    return updated


def allow_past(prefs: dict, name: str) -> dict:
    label = name.strip()
    if not label:
        raise EmploymentError("Informe a empresa anterior que pode voltar à busca.")
    current = (prefs.get("employment") or {}).get("current") or {}
    if matches_employer(label, current):
        raise EmploymentError("O empregador atual continua fora da busca.")
    updated = _copy(prefs)
    allowed = updated["employment"].setdefault("allowed_past", [])
    if not any(same_employer(label, item) for item in allowed):
        allowed.append(label)
    return updated


def add_previous(prefs: dict, name: str, aliases: list[str] | None = None) -> dict:
    label = name.strip()
    if not label:
        raise EmploymentError("Informe o nome da empresa anterior.")
    current = (prefs.get("employment") or {}).get("current") or {}
    if matches_employer(label, current):
        raise EmploymentError("Essa empresa é o empregador atual.")
    updated = _copy(prefs)
    previous = updated["employment"].setdefault("previous", [])
    if not any(matches_employer(label, item) for item in previous):
        previous.append({"name": label, "aliases": [item.strip() for item in (aliases or []) if item.strip()]})
    return updated


def excluded_names(prefs: dict) -> list[str]:
    """Names the query plan must not target. The current employer is always included."""
    employment = prefs.get("employment") or {}
    names = list(_names(_entry(employment.get("current") or {})))
    if employment.get("exclude_past", True) is not False:
        allowed = employment.get("allowed_past") or []
        for previous in employment.get("previous") or []:
            if any(matches_employer(name, item) for name in _names(_entry(previous)) for item in allowed):
                continue
            names.extend(_names(_entry(previous)))
    names.extend(str(item) for item in (prefs.get("companies") or {}).get("blocked") or [])
    unique: list[str] = []
    for name in names:
        if name and not any(same_employer(name, kept) for kept in unique):
            unique.append(name)
    return unique


_QUERY_NOISE = {"vaga", "vagas", "career", "careers", "job", "jobs", "carreira", "carreiras",
                 "remoto", "remote"}


def mentions_excluded(text: str, prefs: dict) -> bool:
    """True when the query names an excluded employer, not merely a similar company."""
    tokens = _tokens(text)
    focused = [token for token in tokens if token not in _QUERY_NOISE]
    for name in excluded_names(prefs):
        wanted = _tokens(name)
        if not wanted:
            continue
        if len(wanted) >= 2 and _contains(tokens, wanted):
            return True
        if focused == wanted:
            return True
    return False


def _contains(tokens: list[str], wanted: list[str]) -> bool:
    width = len(wanted)
    return any(tokens[index:index + width] == wanted for index in range(len(tokens) - width + 1))


def _archive_current(employment: dict) -> None:
    name, aliases = _entry(employment.get("current") or {})
    if not name:
        return
    previous = employment.setdefault("previous", [])
    if not any(matches_employer(name, item) for item in previous):
        previous.append({"name": name, "aliases": aliases})


def _copy(prefs: dict) -> dict:
    import copy
    updated = copy.deepcopy(prefs)
    updated.setdefault("employment", {})
    updated["employment"].setdefault("current", {"name": "", "aliases": []})
    updated["employment"].setdefault("previous", [])
    updated["employment"].setdefault("allowed_past", [])
    updated["employment"]["exclude_current"] = True
    return updated
