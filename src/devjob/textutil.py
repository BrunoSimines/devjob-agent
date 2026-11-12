"""Small text helpers shared across modules."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "tr", "section", "article", "ul", "ol", "table", "header", "footer"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self._skip += 1
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in _HEADING_TAGS:
            self.parts.append("\n\n## ")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"}:
            self._skip = max(0, self._skip - 1)
        elif tag in _HEADING_TAGS or tag in _BLOCK_TAGS or tag == "li":
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: str | None) -> str:
    """Convert HTML (possibly entity-escaped, as Greenhouse returns) to plain text."""
    if not raw:
        return ""
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    text = "".join(parser.parts)
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line in {"-", "##"}:
            continue
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out).strip()


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm(text: str | None) -> str:
    """Lowercase, accent-free, punctuation collapsed to spaces."""
    if not text:
        return ""
    text = strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9+#]+", " ", text)
    return text.strip()


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", strip_accents(text).lower()).strip("-")
    return slug[:max_len].strip("-") or "item"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


_PT_WORDS = {"de", "para", "com", "que", "uma", "experiencia", "voce", "nao", "vaga", "requisitos",
             "conhecimento", "desenvolvimento", "sobre", "nos", "das", "dos", "em", "ou", "na", "no"}
_EN_WORDS = {"the", "and", "with", "you", "for", "experience", "our", "will", "we", "are",
             "requirements", "knowledge", "development", "about", "to", "of", "in", "or", "your"}


def detect_language(text: str) -> str | None:
    words = norm(text).split()
    if len(words) < 8:
        return None
    pt = sum(1 for w in words if w in _PT_WORDS)
    en = sum(1 for w in words if w in _EN_WORDS)
    if pt == en:
        return None
    return "pt" if pt > en else "en"


def token_set(text: str) -> set[str]:
    return {w for w in norm(text).split() if len(w) > 1}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)
