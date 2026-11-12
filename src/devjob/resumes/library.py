"""Resume library: reusable versions with metadata, stored under ``resumes/<id>/``."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from devjob import taxonomy
from devjob.config.settings import Paths
from devjob.profile.extract import extract_text
from devjob.profile.model import Profile
from devjob.storage.db import dumps, loads, now_iso
from devjob.textutil import detect_language, jaccard, norm, sha256_bytes, sha256_text, slugify


class ResumeError(Exception):
    pass


class DuplicateResumeError(ResumeError):
    def __init__(self, existing_id: str, similarity: float) -> None:
        super().__init__(f"Currículo quase idêntico a '{existing_id}' (similaridade {similarity:.0%}). "
                         "Reutilize a versão existente ou use --force para salvar mesmo assim.")
        self.existing_id = existing_id
        self.similarity = similarity


@dataclass
class ResumeRecord:
    id: str
    label: str
    origin: str
    language: str | None
    target_roles: list[str]
    highlighted_skills: list[str]
    experience_ids: list[str]
    content_hash: str
    dir: str
    source_profile_version: int | None = None
    source_profile_hash: str | None = None
    facts_fingerprint: str | None = None
    md_path: str | None = None
    text_path: str | None = None
    pdf_path: str | None = None
    docx_path: str | None = None
    original_path: str | None = None
    created_at: str = ""
    updated_at: str = ""
    locked: bool = False
    archived: bool = False
    _text: str | None = field(default=None, repr=False, compare=False)

    def text(self) -> str:
        if self._text is None:
            path = self.md_path or self.text_path
            self._text = Path(path).read_text(encoding="utf-8") if path and Path(path).exists() else ""
        return self._text

    def skills(self) -> set[str]:
        found = set(taxonomy.find_skills(self.text())) | set(self.highlighted_skills)
        return found | set(taxonomy.expand_implications(found))

    def document_path(self) -> str | None:
        return self.pdf_path or self.original_path or self.docx_path or self.md_path

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("_text", None)
        return data


_JSON_FIELDS = ("target_roles", "highlighted_skills", "experience_ids")


def _from_row(row: sqlite3.Row) -> ResumeRecord:
    data = dict(row)
    for key in _JSON_FIELDS:
        data[key] = loads(data.pop(f"{key}_json"), [])
    data["locked"], data["archived"] = bool(data["locked"]), bool(data["archived"])
    return ResumeRecord(**data)


def list_resumes(conn: sqlite3.Connection, include_archived: bool = False) -> list[ResumeRecord]:
    sql = "SELECT * FROM resumes" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY created_at"
    return [_from_row(r) for r in conn.execute(sql)]


def get_resume(conn: sqlite3.Connection, resume_id: str) -> ResumeRecord:
    row = conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
    if row is None:
        raise ResumeError(f"Currículo não encontrado: {resume_id}")
    return _from_row(row)


def insert(conn: sqlite3.Connection, record: ResumeRecord) -> None:
    data = record.to_dict()
    for key in _JSON_FIELDS:
        data[f"{key}_json"] = dumps(data.pop(key))
    data["locked"], data["archived"] = int(data["locked"]), int(data["archived"])
    columns = ", ".join(data)
    with conn:
        conn.execute(f"INSERT INTO resumes ({columns}) VALUES ({', '.join('?' for _ in data)})", list(data.values()))
    write_meta(record)


def write_meta(record: ResumeRecord) -> None:
    meta = {k: v for k, v in record.to_dict().items() if k != "dir"}
    Path(record.dir, "meta.yaml").write_text(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True),
                                             encoding="utf-8")


def next_id(conn: sqlite3.Connection, label: str, language: str | None) -> str:
    base = f"cv-{slugify(label, 30)}-{language or 'xx'}"
    existing = {r[0] for r in conn.execute("SELECT id FROM resumes WHERE id LIKE ?", (base + "-v%",))}
    version = 1
    while f"{base}-v{version}" in existing:
        version += 1
    return f"{base}-v{version}"


def _shingles(text: str, size: int = 3) -> set[tuple[str, ...]]:
    words = norm(text).split()
    return {tuple(words[i:i + size]) for i in range(max(1, len(words) - size + 1))}


def similarity(text_a: str, skills_a: set[str], text_b: str, skills_b: set[str]) -> float:
    """0..1 similarity combining wording (60%) and highlighted skills (40%)."""
    return 0.6 * jaccard(_shingles(text_a), _shingles(text_b)) + 0.4 * jaccard(skills_a, skills_b)


def most_similar(conn: sqlite3.Connection, text: str, skills: set[str]) -> tuple[ResumeRecord | None, float]:
    best, best_score = None, 0.0
    for record in list_resumes(conn):
        score = similarity(text, skills, record.text(), record.skills())
        if score > best_score:
            best, best_score = record, score
    return best, best_score


def import_file(conn: sqlite3.Connection, paths: Paths, config: dict, file: Path, label: str,
                target_roles: list[str] | None = None, language: str | None = None,
                force: bool = False) -> ResumeRecord:
    """Add an existing resume (PDF/DOCX/MD) to the library without modifying it."""
    data = file.read_bytes()
    content_hash = sha256_bytes(data)
    row = conn.execute("SELECT id FROM resumes WHERE content_hash = ?", (content_hash,)).fetchone()
    if row:
        raise DuplicateResumeError(row["id"], 1.0)
    text = extract_text(file)
    skills = set(taxonomy.find_skills(text))
    similar, score = most_similar(conn, text, skills)
    if similar and score >= config["resumes"]["duplicate_similarity"] and not force:
        raise DuplicateResumeError(similar.id, score)
    language = language or detect_language(text)
    resume_id = next_id(conn, label, language)
    folder = paths.resumes / resume_id
    folder.mkdir(parents=True, exist_ok=False)
    original = folder / f"original{file.suffix.lower()}"
    shutil.copy2(file, original)
    text_path = folder / "resume.txt"
    text_path.write_text(text, encoding="utf-8")
    now = now_iso()
    record = ResumeRecord(
        id=resume_id, label=label, origin="imported", language=language, target_roles=target_roles or [],
        highlighted_skills=sorted(skills), experience_ids=[], content_hash=content_hash, dir=str(folder),
        text_path=str(text_path), original_path=str(original),
        md_path=str(original) if file.suffix.lower() == ".md" else None,
        pdf_path=str(original) if file.suffix.lower() == ".pdf" else None,
        docx_path=str(original) if file.suffix.lower() == ".docx" else None,
        created_at=now, updated_at=now,
    )
    insert(conn, record)
    return record


def facts_fingerprint(profile: Profile, experience_ids: list[str], skills: list[str]) -> str:
    """Hash of the profile facts a generated resume was built from."""
    parts = []
    for exp in profile.experiences:
        if exp.id in experience_ids:
            parts.append("|".join([exp.id, exp.title, exp.company, exp.start or "", exp.end or "",
                                   ",".join(exp.technologies)] + [h.value for h in exp.highlights if h.confirmed]))
    confirmed = profile.confirmed_hard_skills()
    parts.append(",".join(sorted(s for s in skills if s in confirmed)))
    return sha256_text("\n".join(parts))


def outdated(conn: sqlite3.Connection, profile: Profile) -> list[dict]:
    """Resumes that may no longer reflect profile.md."""
    report = []
    confirmed = profile.confirmed_hard_skills()
    current_ids = {e.id for e in profile.experiences}
    for record in list_resumes(conn):
        reasons: list[str] = []
        if record.origin == "generated":
            if facts_fingerprint(profile, record.experience_ids, record.highlighted_skills) != record.facts_fingerprint:
                missing = [i for i in record.experience_ids if i not in current_ids]
                reasons.append("experiências usadas foram removidas do perfil: " + ", ".join(missing) if missing
                               else "fatos usados (experiências ou skills) mudaram no perfil")
        else:
            text = norm(record.text())
            for exp in profile.confirmed_experiences():
                if norm(exp.company) and norm(exp.company) not in text:
                    reasons.append(f"não menciona a experiência '{exp.title} @ {exp.company}'")
        new_skills = sorted((confirmed - record.skills()) & _related_skills(record))
        if new_skills:
            reasons.append("skills confirmadas no perfil e ausentes no currículo: " + ", ".join(new_skills[:8]))
        if reasons:
            report.append({"resume_id": record.id, "label": record.label, "locked": record.locked,
                           "reasons": reasons})
    return report


def _related_skills(record: ResumeRecord) -> set[str]:
    categories = {taxonomy.category_of(s) for s in record.highlighted_skills}
    return {s.name for s in taxonomy.SKILLS if s.category in categories}


def lock(conn: sqlite3.Connection, resume_id: str) -> None:
    with conn:
        conn.execute("UPDATE resumes SET locked = 1, updated_at = ? WHERE id = ?", (now_iso(), resume_id))


def archive(conn: sqlite3.Connection, resume_id: str) -> None:
    get_resume(conn, resume_id)
    with conn:
        conn.execute("UPDATE resumes SET archived = 1, updated_at = ? WHERE id = ?", (now_iso(), resume_id))
