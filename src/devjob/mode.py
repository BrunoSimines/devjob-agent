"""User mode is the default. Developer mode starts only with an explicit confirmation.

This stops the CLI from writing product files during a job search. It does not
sandbox the editor: Claude Code and Cursor can still edit files if the person
driving the session chooses to. The skill instructions are what keep a job
search from doing that.
"""

from __future__ import annotations

from pathlib import Path

import yaml

MODES = ("user", "developer")


class UserModeError(RuntimeError):
    """A user-mode session tried to change the product."""


def mode_path(paths) -> Path:
    return paths.home / "mode.yaml"


def current_mode(paths) -> str:
    file = mode_path(paths)
    if not file.exists():
        return "user"
    data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    mode = str((data or {}).get("mode") or "user")
    return mode if mode in MODES else "user"


def set_mode(paths, mode: str, *, confirm: bool = False) -> str:
    if mode not in MODES:
        raise UserModeError(f"Modo desconhecido: {mode}.")
    if mode == "developer" and not confirm:
        raise UserModeError(
            "O modo desenvolvedor só liga com confirmação explícita do mantenedor. "
            "Uma busca fraca não muda o modo.")
    mode_path(paths).write_text(yaml.safe_dump({"mode": mode}, allow_unicode=True), encoding="utf-8")
    return mode


def refuse_product_edit(paths, target: Path) -> None:
    """User mode may write only inside the data directory."""
    if current_mode(paths) == "developer":
        return
    home = paths.home.resolve()
    resolved = Path(target).resolve()
    if resolved == home or home in resolved.parents:
        return
    raise UserModeError(
        f"Modo usuário: {resolved} fica fora dos dados locais. "
        "O código, os testes e o SKILL.md não são alterados durante uma busca.")


def describe(paths) -> dict:
    mode = current_mode(paths)
    return {
        "mode": mode,
        "default": "user",
        "data_dir": str(paths.home),
        "product_edits": mode == "developer",
        "limitation": "A CLI recusa gravar fora do diretório de dados no modo usuário. "
                      "Isso não impede que o editor altere arquivos se a sessão ignorar a skill.",
    }
