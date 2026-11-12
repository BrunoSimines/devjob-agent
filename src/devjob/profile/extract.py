"""Text extraction from PDF and DOCX resumes."""

from __future__ import annotations

from pathlib import Path

SUPPORTED = {".pdf", ".docx", ".md", ".txt"}


class ExtractionError(Exception):
    pass


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ExtractionError(f"Formato não suportado: {suffix}. Use PDF, DOCX, MD ou TXT.")
    if not path.exists():
        raise ExtractionError(f"Arquivo não encontrado: {path}")
    if suffix == ".pdf":
        text = _pdf(path)
    elif suffix == ".docx":
        text = _docx(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ExtractionError(
            "Nenhum texto extraído. O arquivo pode ser uma imagem escaneada; OCR não é suportado no MVP."
        )
    return text


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # pypdf raises several unrelated exception types
        raise ExtractionError(f"Não foi possível ler o PDF: {exc}") from exc
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ExtractionError("PDF protegido por senha.") from exc
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _docx(path: Path) -> str:
    import docx

    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ExtractionError(f"Não foi possível ler o DOCX: {exc}") from exc
    lines = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                lines.append(" | ".join(dict.fromkeys(cells)))
    return "\n".join(lines)
