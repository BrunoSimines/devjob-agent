"""Load versioned prompt files from ``prompts/``.

Flows name files. They never embed the instruction text, and a missing or
invalid file is an error. No substitute instructions are invented.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from devjob.resumes.theme import Theme, ThemeError, load_theme, product_root
from devjob.textutil import sha256_bytes

REQUIRED_PROMPTS = (
    "guardrails",
    "profile-extraction",
    "profile-update",
    "onboarding",
    "search-planning",
    "job-analysis",
    "job-matching",
    "resume-selection",
    "resume-generation",
    "resume-validation",
    "application-preparation",
)

# Operation -> prompt ids, in the order the agent applies them.
# guardrails.md is prepended to every load and is not repeated here.
FLOWS: dict[str, list[str]] = {
    "profile-extraction": ["profile-extraction"],
    "profile-update": ["profile-update"],
    "onboarding": ["onboarding"],
    "setup": ["onboarding", "profile-extraction"],
    "search": ["search-planning", "job-analysis", "job-matching"],
    "job-analysis": ["job-analysis"],
    "job-matching": ["job-matching"],
    "resume-selection": ["resume-selection"],
    "resume-generation": ["resume-generation"],
    "resume-validation": ["resume-validation"],
    "application-preparation": ["application-preparation"],
    "prepare-resume": ["resume-selection", "resume-generation", "resume-validation"],
}

# Conditional steps for flows that must not always generate a document.
SEQUENCES: dict[str, list[dict]] = {
    "prepare-resume": [
        {"id": "resume-selection", "when": "always"},
        {"id": "resume-generation", "when": "decision is propose_new or no_resumes and the user agrees",
         "theme": True},
        {"id": "resume-validation", "when": "a draft exists and before approval"},
    ],
}

_THEMED_FLOWS = {"resume-generation", "prepare-resume"}
_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MIN_BODY = 400


class PromptError(RuntimeError):
    """A prompt file or a flow name cannot be loaded. Nothing was invented in its place."""


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    sha256: str
    path: str
    body: str

    def identity(self) -> dict:
        return {"id": self.id, "version": self.version, "sha256": self.sha256, "path": self.path}


@dataclass(frozen=True)
class LoadedFlow:
    flow: str
    prompts: tuple[Prompt, ...]
    steps: tuple[dict, ...] | None
    theme: Theme | None

    def to_dict(self) -> dict:
        when = {step["id"]: step["when"] for step in self.steps} if self.steps else {}
        data = {
            "flow": self.flow,
            "source": "files",
            "prompts": [
                {**prompt.identity(), "when": when.get(prompt.id, "always"), "body": prompt.body}
                for prompt in self.prompts
            ],
            "theme": self.theme.identity() if self.theme else None,
        }
        if self.steps:
            data["steps"] = list(self.steps)
        return data


def prompts_dir():
    try:
        return product_root() / "prompts"
    except ThemeError as exc:
        raise PromptError(str(exc)) from exc


def load_prompt(prompt_id: str) -> Prompt:
    """Read one prompt from ``prompts/<id>.md``. Rejects paths and unknown ids."""
    if not isinstance(prompt_id, str) or not _ID.fullmatch(prompt_id):
        raise PromptError(
            f"Prompt inválido: {prompt_id!r}. Nenhum arquivo fora de prompts/ foi lido "
            "e nenhuma instrução substituta foi usada.")
    directory = prompts_dir().resolve()
    path = (directory / f"{prompt_id}.md").resolve()
    if path.parent != directory:
        raise PromptError(
            f"Prompt inválido: {prompt_id}. O carregador só lê arquivos em {directory}. "
            "Nenhuma instrução substituta foi usada.")
    if not path.is_file():
        raise PromptError(
            f"Prompt ausente: {prompt_id} (esperado em {path}). Nenhuma instrução substituta foi usada.")
    return _parse(path, prompt_id)


def _parse(path, prompt_id: str) -> Prompt:
    raw = path.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---"):
        raise PromptError(
            f"Prompt inválido: {path} não tem metadados YAML no início. "
            "Nenhuma instrução substituta foi usada.")
    parts = text.split("---", 2)
    if len(parts) < 3 or not parts[1].strip():
        raise PromptError(f"Prompt inválido: {path} não fecha o bloco de metadados. "
                          "Nenhuma instrução substituta foi usada.")
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise PromptError(f"Prompt inválido: {path} tem YAML ilegível. "
                          "Nenhuma instrução substituta foi usada.") from exc
    if not isinstance(meta, dict):
        raise PromptError(f"Prompt inválido: os metadados de {path} precisam ser um mapeamento.")
    if meta.get("id") != prompt_id:
        raise PromptError(
            f"Prompt inválido: {path} declara id {meta.get('id')!r}, mas o arquivo é {prompt_id}.md.")
    version = meta.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PromptError(f"Prompt inválido: {path} precisa de version inteira maior que zero.")
    body = parts[2].strip()
    if len(body) < _MIN_BODY:
        raise PromptError(
            f"Prompt inválido: {path} não contém instruções funcionais. "
            "Nenhuma instrução substituta foi usada.")
    return Prompt(id=prompt_id, version=version, sha256=sha256_bytes(raw), path=str(path), body=body)


def load_flow(flow: str) -> LoadedFlow:
    """Load guardrails plus the files for one operation. Reads the disk every time."""
    if flow not in FLOWS:
        known = ", ".join(sorted(FLOWS))
        raise PromptError(
            f"Fluxo desconhecido: {flow!r}. Fluxos: {known}. Nenhuma instrução substituta foi usada.")
    prompts = [load_prompt("guardrails")]
    prompts.extend(load_prompt(prompt_id) for prompt_id in FLOWS[flow])
    theme = None
    if flow in _THEMED_FLOWS:
        try:
            theme = load_theme()
        except ThemeError as exc:
            raise PromptError(str(exc)) from exc
    steps = tuple(SEQUENCES[flow]) if flow in SEQUENCES else None
    return LoadedFlow(flow=flow, prompts=tuple(prompts), steps=steps, theme=theme)


def list_catalog() -> dict:
    """Verify every required prompt and return the flow map. Does not include instruction text."""
    prompts = [load_prompt(prompt_id).identity() for prompt_id in REQUIRED_PROMPTS]
    theme = load_theme().identity()
    theme.pop("parameters", None)
    return {"prompts": prompts, "flows": {name: ["guardrails", *ids] for name, ids in FLOWS.items()},
            "sequences": SEQUENCES, "theme": theme}


def prompt_health() -> dict:
    try:
        catalog = list_catalog()
    except (PromptError, ThemeError) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "prompts": [f"{item['id']}@{item['version']}" for item in catalog["prompts"]],
        "theme": f"{catalog['theme']['id']}@{catalog['theme']['version']}",
    }
