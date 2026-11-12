"""Load ``config/resume-theme.yaml`` and refuse any font or size it does not name.

The renderer is the only consumer of these values. A missing or invalid file is
an error. Nothing in this module invents a substitute family, size, or color.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from devjob.textutil import sha256_bytes

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_STYLE_ROLES = (
    "name", "professional_title", "section_title", "company", "role", "body", "skills", "education",
    "contact", "date",
)
_BODY_FLOOR = ("body", "skills", "education")
_PAGE_MM = {"A4": (210.0, 297.0), "Letter": (215.9, 279.4)}
_SPACING = (
    "after_name", "after_contacts", "before_sections", "after_titles",
    "between_experiences", "between_bullets", "between_paragraphs",
)
_COLORS = ("primary", "secondary", "divider", "background")
# Only the families the design system names. No third family is ever selected.
_FONT_FILES: dict[str, list[tuple[str, str]]] = {
    "Arial": [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
         "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"),
    ],
    "Liberation Sans": [
        ("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        ("/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/liberation/LiberationSans-Bold.ttf"),
        ("C:/Windows/Fonts/LiberationSans-Regular.ttf", "C:/Windows/Fonts/LiberationSans-Bold.ttf"),
    ],
    "Calibri": [
        ("C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/calibrib.ttf"),
        ("/Library/Fonts/Calibri.ttf", "/Library/Fonts/Calibri Bold.ttf"),
        ("/System/Library/Fonts/Supplemental/Calibri.ttf", "/System/Library/Fonts/Supplemental/Calibri Bold.ttf"),
    ],
    "Aptos": [
        ("C:/Windows/Fonts/Aptos.ttf", "C:/Windows/Fonts/Aptos-Bold.ttf"),
        ("C:/Windows/Fonts/aptos.ttf", "C:/Windows/Fonts/aptos-bold.ttf"),
    ],
}


class ThemeError(RuntimeError):
    """The theme file is missing, invalid, or names a font that is not installed."""


@dataclass(frozen=True)
class TextStyle:
    size_pt: float
    bold: bool


@dataclass(frozen=True)
class Theme:
    id: str
    version: int
    sha256: str
    path: str
    template: str
    page_format: str
    columns: int
    margins_cm: float
    images: bool
    icons: bool
    charts: bool
    skill_bars: bool
    font: str
    fallback: str
    fallbacks: tuple[str, ...]
    line_height: float
    scale: float
    min_body_pt: float
    styles: dict[str, TextStyle]
    spacing_pt: dict[str, float]
    colors: dict[str, str]
    section_styles: dict[str, str]
    dividers: bool
    allowed_formats: tuple[str, ...]
    resolved_font: str
    regular_file: str
    bold_file: str

    def style(self, role: str) -> TextStyle:
        try:
            return self.styles[role]
        except KeyError as exc:
            raise ThemeError(f"O tema não define o estilo '{role}'. Nenhum tamanho substituto foi usado.") from exc

    def rgb(self, name: str) -> tuple[int, int, int]:
        return hex_rgb(self.colors[name])

    def page_mm(self) -> tuple[float, float]:
        try:
            return _PAGE_MM[self.page_format]
        except KeyError as exc:
            raise ThemeError(f"Formato '{self.page_format}' não tem tamanho de página.") from exc

    def with_page_format(self, page_format: str) -> Theme:
        """Troca só o papel. Fontes, tamanhos e margens permanecem os do tema."""
        if page_format not in self.allowed_formats:
            allowed = ", ".join(self.allowed_formats)
            raise ThemeError(
                f"Formato '{page_format}' não é permitido ({allowed}). "
                "Fontes e tamanhos não são alterados para caber na página.")
        if page_format == self.page_format:
            return self
        return replace(self, page_format=page_format)

    def gap_mm(self, name: str) -> float:
        return self.spacing_pt[name] * 25.4 / 72.0

    def leading_mm(self, size_pt: float) -> float:
        return size_pt * self.line_height * 25.4 / 72.0

    def parameters(self) -> dict:
        return {
            "template": self.template,
            "format": self.page_format,
            "columns": self.columns,
            "margins_cm": self.margins_cm,
            "images": self.images,
            "icons": self.icons,
            "charts": self.charts,
            "skill_bars": self.skill_bars,
            "font": self.font,
            "fallback": self.fallback,
            "fallbacks": list(self.fallbacks),
            "scale": self.scale,
            "line_height": self.line_height,
            "styles": {role: {"size_pt": style.size_pt, "bold": style.bold} for role, style in self.styles.items()},
            "spacing_pt": dict(self.spacing_pt),
            "colors": dict(self.colors),
        }

    def identity(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "sha256": self.sha256,
            "path": self.path,
            "resolved_font": self.resolved_font,
            "parameters": self.parameters(),
        }


def hex_rgb(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not _HEX.match(value):
        raise ThemeError(f"Cor inválida no tema: {value!r}. Nenhuma cor substituta foi usada.")
    number = int(value[1:], 16)
    return (number >> 16) & 255, (number >> 8) & 255, number & 255


def product_root() -> Path:
    """Directory that contains ``prompts/`` and ``config/resume-theme.yaml``."""
    override = os.environ.get("DEVJOB_PRODUCT_ROOT")
    if override:
        root = Path(override).expanduser().resolve()
        if not (root / "prompts").is_dir() or not (root / "config" / "resume-theme.yaml").is_file():
            raise ThemeError(
                f"Diretório do produto inválido: {root}. "
                "Faltam prompts/ ou config/resume-theme.yaml. Nenhuma instrução substituta foi usada.")
        return root
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "prompts" / "profile-extraction.md").is_file() and (
                candidate / "config" / "resume-theme.yaml").is_file():
            return candidate
    raise ThemeError(
        "config/resume-theme.yaml não foi encontrado junto do produto. "
        "Nenhuma instrução substituta foi usada.")


def resolve_font(preferred: str, fallbacks: list[str]) -> tuple[str, Path, Path]:
    """Use the preferred family, then each listed fallback. Never a family outside that list."""
    names = [preferred, *fallbacks]
    if not any(name in _FONT_FILES for name in names):
        raise ThemeError(
            f"Fontes {', '.join(names)} não fazem parte do design system. "
            "Nenhuma outra família foi escolhida.")
    for name in names:
        pairs = _FONT_FILES.get(name)
        if not pairs:
            continue
        for regular, bold in pairs:
            if Path(regular).is_file() and Path(bold).is_file():
                return name, Path(regular), Path(bold)
    raise ThemeError(
        f"Nenhum arquivo de fonte encontrado para {', '.join(names)}. "
        "O renderizador não substitui por outra família.")


def _number(value, label: str, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ThemeError(f"Tema inválido: '{label}' precisa ser um número. Nenhum valor substituto foi usado.")
    number = float(value)
    if positive and number <= 0:
        raise ThemeError(f"Tema inválido: '{label}' precisa ser maior que zero.")
    if not positive and number < 0:
        raise ThemeError(f"Tema inválido: '{label}' não pode ser negativo.")
    return number


def _flag(value, label: str) -> bool:
    if not isinstance(value, bool):
        raise ThemeError(f"Tema inválido: '{label}' precisa ser verdadeiro ou falso.")
    return value


def load_theme(path: Path | str | None = None) -> Theme:
    """Read the theme from disk. There is no cached copy and no built-in fallback theme."""
    file = Path(path).expanduser().resolve() if path else product_root() / "config" / "resume-theme.yaml"
    if not file.is_file():
        raise ThemeError(f"Tema ausente: {file}. Nenhum visual substituto foi aplicado.")
    raw = file.read_bytes()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise ThemeError(f"Tema inválido em {file}: YAML ilegível. Nenhum visual substituto foi aplicado.") from exc
    if not isinstance(data, dict):
        raise ThemeError(f"Tema inválido em {file}: o arquivo precisa ser um mapeamento YAML.")

    layout = data.get("layout")
    typography = data.get("typography")
    spacing = data.get("spacing_pt")
    colors = data.get("colors")
    if not all(isinstance(part, dict) for part in (layout, typography, spacing, colors)):
        raise ThemeError(
            f"Tema inválido em {file}: faltam layout, typography, spacing_pt ou colors. "
            "Nenhum visual substituto foi aplicado.")

    for key in ("template", "format"):
        if not isinstance(layout.get(key), str) or not layout[key].strip():
            raise ThemeError(f"Tema inválido: layout.{key} está ausente.")
    allowed = layout.get("formats") or [layout["format"]]
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise ThemeError("Tema inválido: layout.formats precisa ser uma lista de formatos.")
    if layout["format"] not in _PAGE_MM or any(item not in _PAGE_MM for item in allowed):
        known = ", ".join(sorted(_PAGE_MM))
        raise ThemeError(f"Formato não suportado. Use {known}. Nada foi renderizado.")
    if layout.get("orientation", "portrait") != "portrait":
        raise ThemeError("O tema só usa orientação retrato. Nada foi renderizado.")
    columns = layout.get("columns")
    if columns != 1:
        raise ThemeError("O tema precisa ter uma coluna. O renderizador não inventa outro layout.")
    for flag in ("images", "icons", "charts", "skill_bars"):
        if _flag(layout.get(flag), f"layout.{flag}"):
            raise ThemeError(
                f"O tema ligou '{flag}', e este renderizador não desenha isso. "
                "Nenhum visual substituto foi aplicado.")
    background = layout.get("background")
    hex_rgb(background)
    if colors.get("background") != background:
        raise ThemeError("layout.background e colors.background divergem. Nenhum dos dois foi ignorado.")
    for name in _COLORS:
        hex_rgb(colors.get(name))

    scale = _number(typography.get("scale", 1), "typography.scale")
    floor = _number(typography.get("min_body_pt", 10), "typography.min_body_pt")
    styles: dict[str, TextStyle] = {}
    for role in _STYLE_ROLES:
        block = typography.get(role)
        if not isinstance(block, dict):
            raise ThemeError(f"Tema inválido: typography.{role} está ausente.")
        size = _number(block.get("size_pt"), f"typography.{role}.size_pt") * scale
        if role in _BODY_FLOOR and size < floor - 1e-6:
            raise ThemeError(
                f"O corpo não pode ficar abaixo de {floor:g} pt (typography.{role} ficaria {size:g} pt). "
                "O renderizador não reduz a fonte para caber na página.")
        styles[role] = TextStyle(size, _flag(block.get("bold"), f"typography.{role}.bold"))
    if styles["body"].bold or styles["skills"].bold or styles["education"].bold:
        raise ThemeError("Parágrafos, competências e formação não usam negrito em bloco.")
    gaps = {key: _number(spacing.get(key), f"spacing_pt.{key}", positive=False) for key in _SPACING}
    font = typography.get("font")
    if not isinstance(font, str) or not font.strip():
        raise ThemeError("Tema inválido: typography.font é obrigatório.")
    listed = typography.get("fallbacks")
    chain: list[str] = []
    if listed is not None:
        if not isinstance(listed, list) or not all(isinstance(item, str) and item.strip() for item in listed):
            raise ThemeError("Tema inválido: typography.fallbacks precisa ser uma lista de fontes.")
        chain.extend(listed)
    single = typography.get("fallback")
    if isinstance(single, str) and single.strip() and single not in chain:
        chain.append(single)
    if not chain:
        raise ThemeError("Tema inválido: informe typography.fallback ou typography.fallbacks.")
    resolved, regular, bold = resolve_font(font, chain)
    section_styles: dict[str, str] = {}
    raw_sections = data.get("section_styles") or {}
    if not isinstance(raw_sections, dict):
        raise ThemeError("Tema inválido: section_styles precisa ser um mapeamento.")
    for style_name, titles in raw_sections.items():
        if style_name not in styles or not isinstance(titles, list):
            raise ThemeError(f"Tema inválido: section_styles.{style_name} não aponta para um estilo.")
        for title in titles:
            if isinstance(title, str) and title.strip():
                section_styles[title.casefold()] = style_name
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ThemeError("Tema inválido: version precisa ser um inteiro maior que zero.")
    identifier = data.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise ThemeError("Tema inválido: id está ausente.")

    return Theme(
        id=identifier, version=version, sha256=sha256_bytes(raw), path=str(file),
        template=layout["template"], page_format=layout["format"], columns=1,
        margins_cm=_number(layout.get("margins_cm"), "layout.margins_cm"),
        images=False, icons=False, charts=False, skill_bars=False,
        font=font, fallback=chain[-1], fallbacks=tuple(chain),
        line_height=_number(typography.get("line_height"), "typography.line_height"),
        scale=scale, min_body_pt=floor, styles=styles, spacing_pt=gaps,
        colors={name: colors[name] for name in _COLORS}, section_styles=section_styles,
        dividers=_flag(layout.get("dividers", True), "layout.dividers"),
        allowed_formats=tuple(allowed),
        resolved_font=resolved, regular_file=str(regular), bold_file=str(bold),
    )


def apply_page_format(theme: Theme, config: dict | None) -> Theme:
    """Honor resumes.page_format from the person's config. Anything else stays in the theme."""
    requested = ((config or {}).get("resumes") or {}).get("page_format")
    if not requested:
        return theme
    return theme.with_page_format(str(requested))
