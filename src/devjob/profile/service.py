"""Profile workflows: import -> draft -> human review -> accept."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from devjob import taxonomy
from devjob.config.settings import Paths
from devjob.profile import markdown
from devjob.profile.extract import extract_text
from devjob.profile.model import Fact, Language, Profile, merge_profiles
from devjob.profile.parser import parse_resume
from devjob.profile.structured import profile_from_structured
from devjob.storage.db import now_iso
from devjob.textutil import norm, sha256_bytes, sha256_text


class ProfileError(Exception):
    pass


@dataclass
class ImportResult:
    file_hash: str
    text_path: Path
    already_accepted: bool = False
    draft_path: Path | None = None
    changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    pending_inferences: list[tuple[str, str]] = field(default_factory=list)


def load_profile(paths: Paths) -> Profile | None:
    if not paths.profile.exists():
        return None
    profile, _ = markdown.parse(paths.profile.read_text(encoding="utf-8"))
    return profile


def require_profile(paths: Paths) -> Profile:
    profile = load_profile(paths)
    if profile is None:
        raise ProfileError("Nenhum perfil encontrado. Importe um currículo: devjob profile import <arquivo>")
    return profile


def profile_hash(paths: Paths) -> str | None:
    if not paths.profile.exists():
        return None
    return sha256_text(paths.profile.read_text(encoding="utf-8"))


def current_version(conn: sqlite3.Connection) -> tuple[int, str | None]:
    row = conn.execute("SELECT version, content_hash FROM profile_versions ORDER BY version DESC LIMIT 1").fetchone()
    return (row["version"], row["content_hash"]) if row else (0, None)


def sync_version(conn: sqlite3.Connection, paths: Paths, note: str = "edição manual detectada") -> tuple[int, bool]:
    """Register a new profile version if profile.md changed. Returns (version, changed)."""
    digest = profile_hash(paths)
    version, last_hash = current_version(conn)
    if digest is None or digest == last_hash:
        return version, False
    version += 1
    with conn:
        conn.execute("INSERT INTO profile_versions (version, content_hash, created_at, note) VALUES (?, ?, ?, ?)",
                     (version, digest, now_iso(), note))
    return version, True


def write_profile(conn: sqlite3.Connection, paths: Paths, profile: Profile, note: str) -> int:
    version, _ = current_version(conn)
    profile.version = version + 1
    profile.updated_at = now_iso()
    paths.profile.write_text(markdown.render(profile), encoding="utf-8")
    new_version, _ = sync_version(conn, paths, note)
    return new_version


def extract_resume_text(conn: sqlite3.Connection, paths: Paths, file: Path) -> tuple[str, str, Path]:
    """Extract (and cache) the resume text. Returns (hash, text, cached text path)."""
    file_hash = sha256_bytes(file.read_bytes())
    text_path = paths.imports / f"{file_hash[:16]}.txt"
    if text_path.exists():
        return file_hash, text_path.read_text(encoding="utf-8"), text_path
    text = extract_text(file)
    text_path.write_text(text, encoding="utf-8")
    return file_hash, text, text_path


def import_resume(conn: sqlite3.Connection, paths: Paths, file: Path, structured: dict | None = None,
                  force: bool = False) -> ImportResult:
    file_hash, text, text_path = extract_resume_text(conn, paths, file)
    result = ImportResult(file_hash=file_hash, text_path=text_path)
    row = conn.execute("SELECT status FROM resume_imports WHERE file_hash = ?", (file_hash,)).fetchone()
    if row and row["status"] == "accepted" and not force and structured is None:
        result.already_accepted = True
        result.notes.append("Este arquivo já foi importado e aceito; nada a reprocessar (use --force para refazer).")
        return result

    if structured is not None:
        incoming, notes = profile_from_structured(structured, text)
    else:
        incoming, notes = parse_resume(text)
        notes.append("extração heurística: revise cargos, empresas e datas antes de aceitar")
    current = load_profile(paths) or Profile()
    merged, changes = merge_profiles(current, incoming)
    merged.version = current.version
    paths.profile_draft.write_text(markdown.render(merged), encoding="utf-8")
    with conn:
        conn.execute(
            "INSERT INTO resume_imports (file_hash, file_name, imported_at, text_path, status) VALUES (?, ?, ?, ?, 'draft') "
            "ON CONFLICT(file_hash) DO UPDATE SET imported_at = excluded.imported_at, status = 'draft'",
            (file_hash, file.name, now_iso(), str(text_path)),
        )
    result.draft_path = paths.profile_draft
    result.changes = changes
    result.notes = notes
    result.pending_inferences = merged.pending_inferences()
    return result


def review(paths: Paths) -> dict:
    if not paths.profile_draft.exists():
        raise ProfileError("Não há rascunho pendente. Rode: devjob profile import <arquivo>")
    draft, warnings = markdown.parse(paths.profile_draft.read_text(encoding="utf-8"))
    current = load_profile(paths) or Profile()
    _, changes = merge_profiles(current, draft)
    return {"draft_path": str(paths.profile_draft), "changes": changes, "warnings": warnings,
            "pending_inferences": draft.pending_inferences()}


def accept_draft(conn: sqlite3.Connection, paths: Paths) -> int:
    if not paths.profile_draft.exists():
        raise ProfileError("Não há rascunho pendente para aceitar.")
    draft, warnings = markdown.parse(paths.profile_draft.read_text(encoding="utf-8"))
    broken = [w for w in warnings if "sem cargo ou empresa" in w]
    if broken:
        raise ProfileError("Corrija o rascunho antes de aceitar: " + "; ".join(broken))
    version = write_profile(conn, paths, draft, "rascunho aceito pelo usuário")
    paths.profile_draft.unlink()
    with conn:
        conn.execute("UPDATE resume_imports SET status = 'accepted' WHERE status = 'draft'")
    return version


def discard_draft(conn: sqlite3.Connection, paths: Paths) -> None:
    if paths.profile_draft.exists():
        paths.profile_draft.unlink()
    with conn:
        conn.execute("UPDATE resume_imports SET status = 'discarded' WHERE status = 'draft'")


def _matching_facts(profile: Profile, value: str) -> list[object]:
    key = norm(value)
    hits: list[object] = []
    for section in Profile.LIST_SECTIONS:
        hits += [f for f in getattr(profile, section) if f.key() == key]
    for exp in profile.experiences:
        hits += [h for h in exp.highlights if h.key() == key or (len(key) > 12 and key in h.key())]
        if norm(f"{exp.title} @ {exp.company}") == key or exp.id == value:
            hits.append(exp)
    hits += [lang for lang in profile.languages if lang.code == (taxonomy.language_code(value) or value)]
    return hits


def confirm_fact(conn: sqlite3.Connection, paths: Paths, value: str) -> int:
    profile = require_profile(paths)
    hits = [h for h in _matching_facts(profile, value) if getattr(h, "source", None) == "inferred"]
    if not hits:
        raise ProfileError(f"Nenhuma informação inferida corresponde a '{value}'.")
    for hit in hits:
        hit.source = "user"
    return write_profile(conn, paths, profile, f"confirmado pelo usuário: {value}")


def reject_fact(conn: sqlite3.Connection, paths: Paths, value: str) -> int:
    profile = require_profile(paths)
    hits = [h for h in _matching_facts(profile, value) if getattr(h, "source", None) == "inferred"]
    if not hits:
        raise ProfileError(f"Nenhuma informação inferida corresponde a '{value}'.")
    ids = {id(h) for h in hits}
    for section in Profile.LIST_SECTIONS:
        setattr(profile, section, [f for f in getattr(profile, section) if id(f) not in ids])
    profile.languages = [lang for lang in profile.languages if id(lang) not in ids]
    profile.experiences = [e for e in profile.experiences if id(e) not in ids]
    for exp in profile.experiences:
        exp.highlights = [h for h in exp.highlights if id(h) not in ids]
    return write_profile(conn, paths, profile, f"rejeitado pelo usuário: {value}")


def add_fact(conn: sqlite3.Connection, paths: Paths, kind: str, value: str, level: str | None = None) -> int:
    """Facts declared directly by the user (source ``user``)."""
    profile = load_profile(paths) or Profile()
    if kind == "skill":
        name = taxonomy.canonical_skill(value) or value
        profile.hard_skills = [f for f in profile.hard_skills if f.key() != norm(name)]
        profile.hard_skills.append(Fact(name, "user", None, taxonomy.category_of(name)))
    elif kind == "soft-skill":
        name = taxonomy.canonical_soft_skill(value) or value
        profile.soft_skills = [f for f in profile.soft_skills if f.key() != norm(name)]
        profile.soft_skills.append(Fact(name, "user"))
    elif kind == "specialization":
        profile.specializations = [f for f in profile.specializations if f.key() != norm(value)]
        profile.specializations.append(Fact(value, "user"))
    elif kind == "certification":
        profile.certifications.append(Fact(value, "user"))
    elif kind == "language":
        code = taxonomy.language_code(value)
        if not code:
            raise ProfileError(f"Idioma não reconhecido: {value}")
        profile.languages = [lang for lang in profile.languages if lang.code != code]
        profile.languages.append(Language(code, taxonomy.parse_level(level or "") or level, "user"))
    else:
        raise ProfileError(f"Tipo desconhecido: {kind}")
    return write_profile(conn, paths, profile, f"declarado pelo usuário: {kind} {value}")


def status(conn: sqlite3.Connection, paths: Paths) -> dict:
    profile = load_profile(paths)
    if profile is None:
        return {"exists": False}
    version, changed = sync_version(conn, paths)
    _, warnings = markdown.parse(paths.profile.read_text(encoding="utf-8"))
    return {
        "exists": True,
        "version": version,
        "changed_since_last_check": changed,
        "warnings": warnings,
        "pending_inferences": profile.pending_inferences(),
        "experiences": len(profile.experiences),
        "confirmed_hard_skills": sorted(profile.confirmed_hard_skills()),
        "draft_pending": paths.profile_draft.exists(),
    }


def structured_from_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"JSON inválido em {path}: {exc}") from exc
