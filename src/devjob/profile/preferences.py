"""``preferences.yaml``: what the user wants, split into eliminatory rules and
negotiable preferences."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from devjob.config.settings import builtin_template, deep_merge

SENIORITY_LEVELS = ("intern", "junior", "mid", "senior", "staff", "principal", "lead", "manager")
WORK_MODELS = ("remote", "hybrid", "onsite")
CONTRACT_TYPES = ("clt", "pj", "international", "contractor")
PERIODS = ("month", "year", "hour")
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2", "native")


def defaults() -> dict[str, Any]:
    return yaml.safe_load(builtin_template("preferences.yaml"))


def load_preferences(path: Path) -> dict[str, Any]:
    if not path.exists():
        return defaults()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} deve conter um mapeamento YAML.")
    return deep_merge(defaults(), data)


def save_preferences(path: Path, prefs: dict[str, Any]) -> None:
    header = "".join(line + "\n" for line in builtin_template("preferences.yaml").splitlines()
                     if line.startswith("#"))
    path.write_text(header + "\n" + yaml.safe_dump(prefs, sort_keys=False, allow_unicode=True), encoding="utf-8")


def validate(prefs: dict[str, Any]) -> list[str]:
    problems: list[str] = []

    def check_list(value, allowed, label):
        if not isinstance(value, list):
            problems.append(f"{label} deve ser uma lista")
            return
        for item in value:
            if str(item).lower() not in allowed:
                problems.append(f"{label}: valor '{item}' inválido (aceitos: {', '.join(allowed)})")

    check_list(prefs["seniority"]["levels"], SENIORITY_LEVELS, "seniority.levels")
    check_list(prefs["work_model"]["accepted"], WORK_MODELS, "work_model.accepted")
    check_list(prefs["contract_types"]["accepted"], CONTRACT_TYPES, "contract_types.accepted")
    for i, item in enumerate(prefs["salary"].get("minimums") or []):
        if not isinstance(item, dict):
            problems.append(f"salary.minimums[{i}] deve ser um objeto")
            continue
        if not isinstance(item.get("amount"), (int, float)) or item["amount"] <= 0:
            problems.append(f"salary.minimums[{i}].amount deve ser um número positivo")
        if not item.get("currency"):
            problems.append(f"salary.minimums[{i}].currency é obrigatório (ex.: BRL, USD)")
        if item.get("period", "month") not in PERIODS:
            problems.append(f"salary.minimums[{i}].period deve ser um de {PERIODS}")
        if item.get("contract") and item["contract"] not in CONTRACT_TYPES:
            problems.append(f"salary.minimums[{i}].contract inválido: {item['contract']}")
    for i, item in enumerate(prefs["languages"].get("working") or []):
        if not isinstance(item, dict) or not item.get("language"):
            problems.append(f"languages.working[{i}] precisa de 'language'")
        elif item.get("level") and str(item["level"]) not in LEVELS:
            problems.append(f"languages.working[{i}].level inválido: {item['level']}")
    for key in ("target_roles", "primary_stack", "specializations", "hard_skills_to_use", "soft_skills"):
        if not isinstance(prefs.get(key), list):
            problems.append(f"{key} deve ser uma lista")
    employment = prefs.get("employment") or {}
    if str(employment.get("status") or "unknown") not in {"unknown", "employed", "unemployed"}:
        problems.append("employment.status deve ser unknown, employed ou unemployed")
    if employment.get("exclude_current") is False:
        problems.append("employment.exclude_current não pode ser desativado")
    if "exclude_past" in employment and not isinstance(employment.get("exclude_past"), bool):
        problems.append("employment.exclude_past deve ser verdadeiro ou falso")
    current = employment.get("current") or {}
    if not isinstance(current, dict):
        problems.append("employment.current deve informar name e aliases")
    elif employment.get("status") == "employed" and not str(current.get("name") or "").strip():
        problems.append("employment.current.name é obrigatório quando a pessoa está empregada")
    priority_companies = (prefs.get("companies") or {}).get("priority") or []
    if not isinstance(priority_companies, list) or not all(isinstance(item, str) for item in priority_companies):
        problems.append("companies.priority deve ser uma lista de nomes de empresas")
    priority = (prefs.get("sources") or {}).get("priority") or []
    if not isinstance(priority, list) or not all(isinstance(item, str) and item.strip() for item in priority):
        problems.append("sources.priority deve ser uma lista de fontes, ex.: [inhire, greenhouse]")
    share = (prefs.get("location") or {}).get("home_share")
    if not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 <= share <= 100:
        problems.append("location.home_share deve ser um percentual de 0 a 100")
    focus = str((prefs.get("location") or {}).get("focus") or "").lower()
    if focus not in ("home", "abroad", "mixed"):
        problems.append("location.focus deve ser home, abroad ou mixed")
    return problems


def set_value(prefs: dict[str, Any], dotted_key: str, raw_value: str) -> dict[str, Any]:
    """Set ``a.b.c`` to a YAML-parsed value (so ``[remote, hybrid]`` becomes a list)."""
    updated = copy.deepcopy(prefs)
    keys = dotted_key.split(".")
    node = updated
    for key in keys[:-1]:
        if not isinstance(node.get(key), dict):
            raise KeyError(f"Chave inexistente: {dotted_key}")
        node = node[key]
    if keys[-1] not in node:
        raise KeyError(f"Chave inexistente: {dotted_key}")
    node[keys[-1]] = yaml.safe_load(raw_value) if raw_value.strip() else None
    return updated


def apply_overrides(prefs: dict[str, Any], *, remote: bool = False, seniority: list[str] | None = None,
                    min_salary: float | None = None, currency: str | None = None,
                    period: str = "month", contract: str | None = None) -> dict[str, Any]:
    """Per-search overrides that do not touch preferences.yaml."""
    updated = copy.deepcopy(prefs)
    if remote:
        updated["work_model"]["accepted"] = ["remote"]
        updated["work_model"]["eliminatory"] = True
    if seniority:
        updated["seniority"]["levels"] = seniority
    if min_salary:
        if not currency:
            raise ValueError("Informe a moeda do salário mínimo (ex.: --currency BRL).")
        updated["salary"]["minimums"] = [{"currency": currency.upper(), "amount": float(min_salary),
                                          "period": period, "contract": contract}]
        updated["salary"]["eliminatory"] = True
    return updated
