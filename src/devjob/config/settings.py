"""Local paths and configuration (``config.yaml`` inside the data directory)."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

ENV_HOME = "DEVJOB_HOME"

DEFAULT_CONFIG: dict[str, Any] = {
    "matching": {
        # Pesos relativos de cada critério. Critérios sem informação suficiente
        # são excluídos do cálculo e o peso restante é renormalizado.
        "weights": {
            "required_skills": 0.30,
            "experience": 0.15,
            "preferred_skills": 0.10,
            "seniority": 0.10,
            "languages": 0.05,
            "location": 0.10,
            "compensation": 0.10,
            "preferences": 0.10,
        },
        "bands": {"strong": 75, "moderate": 55},
        # Abaixo desta cobertura de requisitos obrigatórios a vaga não é "recomendada".
        "min_required_coverage": 0.5,
        # Fração mínima do peso total com informação conhecida para recomendar.
        "min_confidence": 0.6,
    },
    "resumes": {
        "reuse_threshold": 0.85,
        "new_version_min_gain": 0.15,
        "duplicate_similarity": 0.90,
        "default_template": "ats-classic",
        "export_docx": False,
        "max_skills_listed": 18,
        # A4 ou Letter. Não altera fonte, tamanho ou margem.
        "page_format": "A4",
    },
    "http": {
        "timeout_seconds": 20,
        "min_interval_seconds": 1.0,
        "max_retries": 2,
        "user_agent": "devjob-agent/1.0 (local personal job search assistant)",
    },
    "search": {
        "cache_ttl_hours": 6,
        "default_limit": 20,
        "discovery": {
            "max_queries": 16,
            "max_results_per_query": 10,
            "max_pages": 1,
            "max_source_share": 0.4,
            # native: the host agent runs the web search. brave: optional, only with the user's own key.
            "provider": "native",
            "brave_api_key_env": "DEVJOB_BRAVE_API_KEY",
        },
    },
}


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def config(self) -> Path:
        return self.home / "config.yaml"

    @property
    def profile(self) -> Path:
        return self.home / "profile.md"

    @property
    def profile_draft(self) -> Path:
        return self.home / "profile.draft.md"

    @property
    def preferences(self) -> Path:
        return self.home / "preferences.yaml"

    @property
    def db(self) -> Path:
        return self.home / "devjob.db"

    @property
    def imports(self) -> Path:
        return self.home / "imports"

    @property
    def resumes(self) -> Path:
        return self.home / "resumes"

    @property
    def drafts(self) -> Path:
        return self.home / "resumes" / "drafts"

    @property
    def applications(self) -> Path:
        return self.home / "applications"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def templates(self) -> Path:
        return self.home / "templates"


def resolve_home(override: str | os.PathLike[str] | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    env = os.environ.get(ENV_HOME)
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".devjob-agent").resolve()


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(paths: Paths) -> dict[str, Any]:
    if not paths.config.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    data = yaml.safe_load(paths.config.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{paths.config} deve conter um mapeamento YAML.")
    return deep_merge(DEFAULT_CONFIG, data)


def builtin_template(name: str) -> str:
    return resources.files("devjob").joinpath("templates", name).read_text(encoding="utf-8")


def find_git_root(path: Path) -> Path | None:
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def ensure_layout(paths: Paths) -> list[str]:
    """Create the data directory structure. Returns human-readable notes."""
    notes: list[str] = []
    for directory in (paths.home, paths.imports, paths.resumes, paths.drafts,
                      paths.applications, paths.logs, paths.templates):
        directory.mkdir(parents=True, exist_ok=True)
    if not paths.config.exists():
        paths.config.write_text(
            "# Configuração do DevJob Agent. Valores ausentes usam os padrões internos.\n"
            + yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        notes.append(f"Criado {paths.config}")
    if not paths.preferences.exists():
        paths.preferences.write_text(builtin_template("preferences.yaml"), encoding="utf-8")
        notes.append(f"Criado {paths.preferences}")
    git_root = find_git_root(paths.home)
    if git_root is not None:
        notes.append(
            f"ATENÇÃO: o diretório de dados está dentro do repositório Git {git_root}. "
            "Dados pessoais podem ser versionados por engano; prefira ~/.devjob-agent."
        )
    return notes
