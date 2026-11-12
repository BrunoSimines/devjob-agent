"""Check a rendered resume for real layout problems.

This does not claim that every applicant tracking system will parse the file.
It checks that this PDF is selectable text, stays inside the theme margins,
uses the theme's type sizes, and does not leave a heading stranded.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from devjob.resumes.theme import Theme

_DASHES = str.maketrans({"—": "-", "–": "-", "•": " "})


@dataclass
class LayoutReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pages: int = 0
    previews: list[str] = field(default_factory=list)
    note: str = "A validação não afirma compatibilidade universal com sistemas ATS."

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings, "pages": self.pages,
                "previews": self.previews, "note": self.note}


def _plain(text: str) -> str:
    text = text.translate(_DASHES).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _streams(data: bytes) -> list[bytes]:
    chunks = [data]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = match.group(1)
        try:
            chunks.append(zlib.decompress(raw))
        except zlib.error:
            chunks.append(raw)
    return chunks


def _font_sizes(data: bytes) -> set[float]:
    found: set[float] = set()
    for chunk in _streams(data):
        for size in re.finditer(rb"(\d+(?:\.\d+)?) Tf", chunk):
            found.add(round(float(size.group(1)), 2))
    return found


def _expected_phrases(markdown: str) -> list[str]:
    phrases = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            phrases.append(stripped[2:].strip())
        elif stripped.startswith("## "):
            phrases.append(stripped[3:].strip())
        elif stripped.startswith("### "):
            title, _, company = stripped[4:].partition(" — ")
            if title.strip():
                phrases.append(title.strip())
            if company.strip():
                phrases.append(company.strip())
    return [phrase for phrase in phrases if len(phrase) >= 2]


def check_pdf(path: Path, markdown: str, theme: Theme, preview_dir: Path | None = None) -> LayoutReport:
    report = LayoutReport(ok=True)
    if not path.is_file() or path.stat().st_size < 500:
        report.errors.append("o PDF não foi gerado ou está vazio")
        report.ok = False
        return report

    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    report.pages = len(document)
    if report.pages < 1:
        report.errors.append("o PDF não tem páginas")
        report.ok = False
        return report

    page_texts: list[str] = []
    margin_pt = theme.margins_cm / 2.54 * 72.0
    tolerance = 3.0
    for index in range(len(document)):
        page = document[index]
        width, height = page.get_size()
        textpage = page.get_textpage()
        page_texts.append(textpage.get_text_bounded() or "")
        count = textpage.count_rects()
        rects = [textpage.get_rect(item) for item in range(count)]
        for left, bottom, right, top in rects:
            if left < margin_pt - tolerance or bottom < margin_pt - tolerance:
                report.errors.append(f"texto fora da margem na página {index + 1}")
                break
            if right > width - margin_pt + tolerance or top > height - margin_pt + tolerance:
                report.errors.append(f"texto fora da margem na página {index + 1}")
                break
        for left_index, first in enumerate(rects):
            for second in rects[left_index + 1:]:
                overlap_w = min(first[2], second[2]) - max(first[0], second[0])
                overlap_h = min(first[3], second[3]) - max(first[1], second[1])
                if overlap_w > 8 and overlap_h > 4:
                    report.errors.append(f"texto sobreposto na página {index + 1}")
                    break
            else:
                continue
            break
        if preview_dir is not None and index < 3:
            preview_dir.mkdir(parents=True, exist_ok=True)
            image = preview_dir / f"preview-{index + 1}.png"
            page.render(scale=2).to_pil().save(image)
            report.previews.append(str(image))
        page.close()

    full = _plain("\n".join(page_texts))
    if len(full) < 20:
        report.errors.append("o PDF não tem texto selecionável")
    for phrase in _expected_phrases(markdown):
        if _plain(phrase) not in full:
            report.errors.append(f"texto ausente no PDF: {phrase}")

    headings = [line[3:].strip() for line in markdown.splitlines() if line.startswith("## ")]
    for index, text in enumerate(page_texts):
        folded = _plain(text)
        if len(folded) < 25:
            report.errors.append(f"página {index + 1} está quase vazia")
        if any(folded == _plain(heading) for heading in headings):
            report.errors.append(f"título de seção isolado na página {index + 1}")
        if index + 1 < len(page_texts):
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines and "—" in lines[-1] and _plain(page_texts[index + 1]).startswith(_plain(lines[-1][:12])):
                report.warnings.append(f"cabeçalho de experiência pode ter ficado separado na página {index + 1}")

    sizes = _font_sizes(path.read_bytes())
    allowed = {round(style.size_pt, 2) for style in theme.styles.values()}
    unexpected = sorted(size for size in sizes if not any(abs(size - item) < 0.2 for item in allowed))
    if unexpected:
        report.errors.append(f"tamanhos de fonte fora do tema: {unexpected}")
    raw = b" ".join(_streams(path.read_bytes()))
    if theme.resolved_font.encode("ascii", "ignore") not in raw and theme.resolved_font.encode() not in raw:
        report.errors.append(f"a fonte {theme.resolved_font} não aparece no PDF")

    if report.pages > 1:
        last = len(_plain(page_texts[-1]))
        fullest = max(len(_plain(text)) for text in page_texts)
        if fullest and last < fullest * 0.08 and last < 80:
            report.warnings.append("a última página tem pouco texto; isso não remove experiências para encurtar")

    report.errors = list(dict.fromkeys(report.errors))
    report.ok = not report.errors
    document.close()
    return report
