#!/usr/bin/env python3
"""Install DevJob Agent: isolated runtime, local data directory and the skill.

Skill locations (official docs):
  Claude Code: ~/.claude/skills/<name>/SKILL.md  or  <project>/.claude/skills/<name>/SKILL.md
  Cursor:      ~/.cursor/skills/<name>/SKILL.md  or  <project>/.cursor/skills/<name>/SKILL.md
Cursor also loads skills from ~/.claude/skills and .claude/skills, so the default
target ("auto") installs once under .claude/skills and both tools see it.

Usage:
  python scripts/install.py                       # user scope, auto target
  python scripts/install.py --target cursor       # only ~/.cursor/skills
  python scripts/install.py --scope project --project-dir /path/to/repo
  python scripts/install.py --uninstall           # removes the skill, keeps your data
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_NAME = "devjob-agent"
MARK_START, MARK_END = "<!-- devjob:cmd -->", "<!-- /devjob:cmd -->"


def default_home() -> Path:
    env = os.environ.get("DEVJOB_HOME")
    return Path(env).expanduser().resolve() if env else (Path.home() / ".devjob-agent").resolve()


def skill_dirs(target: str, scope: str, project: Path | None) -> list[Path]:
    base = Path.home() if scope == "user" else project
    if base is None:
        raise SystemExit("--scope project exige --project-dir")
    dirs = {"claude": base / ".claude" / "skills" / SKILL_NAME, "cursor": base / ".cursor" / "skills" / SKILL_NAME}
    if target == "auto":
        return [dirs["claude"]]
    if target == "both":
        print("Aviso: o Cursor também lê .claude/skills; instalar nos dois pode exibir a skill duplicada.")
        return [dirs["claude"], dirs["cursor"]]
    return [dirs[target]]


def runtime_paths(runtime: Path) -> tuple[Path, Path]:
    bindir = runtime / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return bindir / f"python{suffix}", bindir / f"devjob{suffix}"


def run(cmd: list[str]) -> None:
    print("$", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)


def command_line(executable: Path, home: Path) -> str:
    exe = executable.as_posix()
    cmd = f'"{exe}"' if " " in exe else exe
    if home != (Path.home() / ".devjob-agent").resolve():
        cmd += f' --home "{home.as_posix()}"'
    return cmd


def render_skill(command: str) -> str:
    text = (REPO / "SKILL.md").read_text(encoding="utf-8")
    start, end = text.index(MARK_START) + len(MARK_START), text.index(MARK_END)
    block = f"\n`{command}`\n"
    if command.startswith('"'):
        block += "\n(PowerShell: prefix the quoted path with `&`.)\n"
    return text[:start] + block + text[end:]


def install_skill(dirs: list[Path], command: str) -> None:
    rendered = render_skill(command)
    for directory in dirs:
        if directory.exists():
            shutil.rmtree(directory)
        (directory / "references").mkdir(parents=True)
        (directory / "SKILL.md").write_text(rendered, encoding="utf-8")
        for ref in (REPO / "references").glob("*.md"):
            shutil.copy2(ref, directory / "references" / ref.name)
        print(f"Skill instalada em {directory}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Instala o DevJob Agent")
    parser.add_argument("--target", choices=["auto", "claude", "cursor", "both"], default="auto")
    parser.add_argument("--scope", choices=["user", "project"], default="user")
    parser.add_argument("--project-dir", type=Path)
    parser.add_argument("--home", type=Path, help="diretório de dados (padrão ~/.devjob-agent)")
    parser.add_argument("--no-venv", action="store_true", help="usa o Python atual (pacote já instalado)")
    parser.add_argument("--no-editable", action="store_true", help="instala uma cópia em vez de modo editável")
    parser.add_argument("--uninstall", action="store_true", help="remove a skill (mantém seus dados)")
    args = parser.parse_args()

    dirs = skill_dirs(args.target, args.scope, args.project_dir.resolve() if args.project_dir else None)
    if args.uninstall:
        for directory in dirs:
            if directory.exists():
                shutil.rmtree(directory)
                print(f"Removida {directory}")
        print("Seus dados pessoais não foram removidos.")
        return 0

    if sys.version_info < (3, 11):
        raise SystemExit(f"Python 3.11+ é necessário (atual: {sys.version.split()[0]}).")
    home = args.home.expanduser().resolve() if args.home else default_home()
    home.mkdir(parents=True, exist_ok=True)

    if args.no_venv:
        python = Path(sys.executable)
        found = shutil.which("devjob")
        executable = Path(found) if found else None
    else:
        runtime = home / "runtime" / "venv"
        if not runtime.exists():
            print(f"Criando ambiente Python isolado em {runtime}")
            venv.create(runtime, with_pip=True)
        python, executable = runtime_paths(runtime)
        run([python, "-m", "pip", "install", "--upgrade", "--quiet", "pip"])
        run([python, "-m", "pip", "install", "--quiet", *([] if args.no_editable else ["-e"]), REPO])

    run([python, "-m", "devjob", "--home", home, "init"])
    command = command_line(executable, home) if executable else f'{python.as_posix()} -m devjob'
    install_skill(dirs, command)

    info = {"version": "1.0.0", "repo": str(REPO), "python": str(python), "command": command,
            "skill_dirs": [str(d) for d in dirs], "home": str(home),
            "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (home / "install.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print("\nPronto. Abra o Claude Code ou o Cursor e use /devjob-agent setup")
    print(f"CLI: {command} --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
