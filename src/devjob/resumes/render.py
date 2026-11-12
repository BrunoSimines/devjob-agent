"""Render resume Markdown to PDF and DOCX using only the loaded theme.

One column, left aligned, selectable text. Sizes, colors and gaps come from the
theme. Nothing here shrinks a font to save a page or picks a second family.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from devjob.resumes.theme import Theme, ThemeError, load_theme

_IMAGE = re.compile(r"!\[[^\]]*\]\(|<img\b", re.IGNORECASE)
_BARS = re.compile(r"[█▓▒░]{3,}")
_CONTACT = re.compile(r"@|https?://|www\.|·|\+\d|\d[\d\s().-]{7,}\d", re.IGNORECASE)
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF\U00002B00-\U00002BFF]"
)


@dataclass(frozen=True)
class Block:
    role: str
    text: str
    company: str | None = None
    extra_before: bool = False
    style: str | None = None

    def style_name(self) -> str:
        if self.style:
            return self.style
        if self.role == "section":
            return "section_title"
        if self.role in ("bullet", "paragraph"):
            return "body"
        return self.role


def parse_blocks(markdown: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("### "):
            blocks.append(("h3", line[4:].strip()))
        elif line.startswith("## "):
            blocks.append(("h2", line[3:].strip()))
        elif line.startswith("# "):
            blocks.append(("h1", line[2:].strip()))
        elif re.match(r"^\s*[-*] ", line):
            blocks.append(("bullet", re.sub(r"^\s*[-*] ", "", line).strip()))
        else:
            blocks.append(("p", line.strip()))
    return blocks


def _strip_inline(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`", lambda m: next(g for g in m.groups() if g), text)


def _contact(text: str) -> bool:
    return _CONTACT.search(text) is not None


def classify(markdown: str, section_styles: dict[str, str] | None = None) -> list[Block]:
    """Map the Markdown skeleton to theme roles. Presentation values are not read from the text."""
    mapping = section_styles or {}
    raw = parse_blocks(markdown)
    if not raw:
        return []
    index = 0
    blocks: list[Block] = []
    if raw[0][0] == "h1":
        blocks.append(Block("name", _strip_inline(raw[0][1])))
        index = 1
    header: list[str] = []
    while index < len(raw) and raw[index][0] == "p":
        header.append(_strip_inline(raw[index][1]))
        index += 1
    if len(header) == 1:
        blocks.append(Block("contact" if _contact(header[0]) else "professional_title", header[0]))
    elif header:
        blocks.append(Block("professional_title", header[0]))
        for line in header[1:-1]:
            blocks.append(Block("paragraph", line))
        blocks.append(Block("contact" if _contact(header[-1]) or len(header) >= 2 else "paragraph", header[-1]))

    expect_date = False
    experiences_in_section = 0
    section_style: str | None = None
    for kind, text in raw[index:]:
        text = _strip_inline(text)
        if kind == "h2":
            expect_date = False
            experiences_in_section = 0
            section_style = mapping.get(text.casefold())
            blocks.append(Block("section", text))
        elif kind == "h3":
            expect_date = True
            role, separator, company = text.partition(" — ")
            blocks.append(Block("experience", role.strip(), company.strip() if separator else None,
                                extra_before=experiences_in_section > 0))
            experiences_in_section += 1
        elif kind == "bullet":
            expect_date = False
            blocks.append(Block("bullet", text, style=section_style))
        elif expect_date:
            expect_date = False
            blocks.append(Block("date", text))
        else:
            blocks.append(Block("paragraph", text, style=section_style))
    return blocks


def _guard(markdown: str, theme: Theme) -> None:
    if _IMAGE.search(markdown):
        raise ThemeError("O tema proíbe imagens. O currículo não foi renderizado e nenhum visual substituto foi aplicado.")
    if _BARS.search(markdown):
        raise ThemeError(
            "O tema proíbe barras de habilidades. O currículo não foi renderizado "
            "e nenhum visual substituto foi aplicado.")
    if _EMOJI.search(markdown):
        raise ThemeError("O tema proíbe emojis. O currículo não foi renderizado.")
    if theme.columns != 1 or theme.page_format not in theme.allowed_formats:
        raise ThemeError("O tema não é o layout de uma coluna no formato permitido. Nada foi renderizado.")


def _groups(blocks: list[Block]) -> list[list[Block]]:
    """Keep a heading with the block that follows it, and a job header with its first bullet."""
    groups: list[list[Block]] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.role == "section" and index + 1 < len(blocks):
            groups.append([block, blocks[index + 1]])
            index += 2
        elif block.role == "experience":
            group = [block]
            cursor = index + 1
            if cursor < len(blocks) and blocks[cursor].role == "date":
                group.append(blocks[cursor])
                cursor += 1
            if cursor < len(blocks) and blocks[cursor].role == "bullet":
                group.append(blocks[cursor])
                cursor += 1
            groups.append(group)
            index = cursor
        elif block.role == "name" and index + 1 < len(blocks) and blocks[index + 1].role in (
                "professional_title", "contact"):
            groups.append([block, blocks[index + 1]])
            index += 2
        else:
            groups.append([block])
            index += 1
    return groups


def render_pdf(markdown: str, path: Path, theme: Theme | None = None) -> Path:
    from fpdf import FPDF

    theme = theme or load_theme()
    _guard(markdown, theme)
    margin = theme.margins_cm * 10.0
    page_w, page_h = theme.page_mm()

    class _Page(FPDF):
        def header(self):
            # Paint the page. Contact details stay in the body, never in this header.
            x, y = self.get_x(), self.get_y()
            self.set_fill_color(*theme.rgb("background"))
            self.rect(0, 0, self.w, self.h, "F")
            self.set_xy(x, y)

    pdf = _Page(format=theme.page_format, unit="mm")
    pdf.set_margins(margin, margin, margin)
    pdf.set_auto_page_break(True, margin=margin)
    pdf.add_page()
    pdf.add_font(theme.resolved_font, "", theme.regular_file)
    pdf.add_font(theme.resolved_font, "B", theme.bold_file)
    family = theme.resolved_font
    width = pdf.w - pdf.l_margin - pdf.r_margin
    frame = pdf.h - pdf.t_margin - pdf.b_margin

    def font_for(style_name: str) -> float:
        style = theme.style(style_name)
        pdf.set_font(family, "B" if style.bold else "", style.size_pt)
        pdf.set_text_color(*theme.rgb("secondary" if style_name in ("contact", "date", "professional_title") else "primary"))
        return theme.leading_mm(style.size_pt)

    def text_height(style_name: str, text: str, box: float) -> float:
        leading = font_for(style_name)
        measured = pdf.multi_cell(box, leading, text, align="L", dry_run=True, output="HEIGHT")
        return float(measured)

    def block_height(block: Block) -> float:
        box = width - 4 if block.role == "bullet" else width
        if block.role == "experience":
            role_h = text_height("role", block.text, width)
            if not block.company:
                height = role_h
            else:
                together = text_height("role", f"{block.text} — {block.company}", width)
                height = together if together <= theme.leading_mm(theme.style("company").size_pt) * 1.2 else (
                    role_h + text_height("company", block.company, width))
            if block.extra_before:
                height += theme.gap_mm("between_experiences")
            return height
        style = block.style_name()
        label = f"• {block.text}" if block.role == "bullet" else block.text
        height = text_height(style, label, box)
        if block.role == "name":
            height += theme.gap_mm("after_name")
        elif block.role == "contact":
            height += theme.gap_mm("after_contacts")
        elif block.role == "section":
            height += theme.gap_mm("before_sections") + theme.gap_mm("after_titles")
        elif block.role == "bullet":
            height += theme.gap_mm("between_bullets")
        elif block.role == "paragraph":
            height += theme.gap_mm("between_paragraphs")
        return height

    def draw(block: Block) -> None:
        if block.role == "name":
            pdf.multi_cell(width, font_for("name"), block.text, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(theme.gap_mm("after_name"))
        elif block.role == "professional_title":
            pdf.multi_cell(width, font_for("professional_title"), block.text, align="L", new_x="LMARGIN", new_y="NEXT")
        elif block.role == "contact":
            pdf.multi_cell(width, font_for("contact"), block.text, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(theme.gap_mm("after_contacts"))
        elif block.role == "section":
            pdf.ln(theme.gap_mm("before_sections"))
            pdf.multi_cell(width, font_for("section_title"), block.text, align="L", new_x="LMARGIN", new_y="NEXT")
            if theme.dividers:
                pdf.set_draw_color(*theme.rgb("divider"))
                pdf.set_line_width(0.2)
                y = pdf.get_y()
                pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(theme.gap_mm("after_titles"))
        elif block.role == "experience":
            if block.extra_before:
                pdf.ln(theme.gap_mm("between_experiences"))
            role_style = theme.style("role")
            company_style = theme.style("company")
            leading = max(theme.leading_mm(role_style.size_pt), theme.leading_mm(company_style.size_pt))
            pdf.set_text_color(*theme.rgb("primary"))
            company_text = f" — {block.company}" if block.company else ""
            pdf.set_font(family, "B" if role_style.bold else "", role_style.size_pt)
            role_width = pdf.get_string_width(block.text)
            pdf.set_font(family, "B" if company_style.bold else "", company_style.size_pt)
            company_width = pdf.get_string_width(company_text) if company_text else 0
            if not company_text or role_width + company_width <= width:
                pdf.set_font(family, "B" if role_style.bold else "", role_style.size_pt)
                pdf.write(leading, block.text)
                if company_text:
                    pdf.set_font(family, "B" if company_style.bold else "", company_style.size_pt)
                    pdf.write(leading, company_text)
                pdf.ln(leading)
            else:
                pdf.set_font(family, "B" if role_style.bold else "", role_style.size_pt)
                pdf.multi_cell(width, theme.leading_mm(role_style.size_pt), block.text, align="L",
                               new_x="LMARGIN", new_y="NEXT")
                pdf.set_font(family, "B" if company_style.bold else "", company_style.size_pt)
                pdf.multi_cell(width, theme.leading_mm(company_style.size_pt), block.company or "", align="L",
                               new_x="LMARGIN", new_y="NEXT")
        elif block.role == "date":
            pdf.multi_cell(width, font_for("date"), block.text, align="L", new_x="LMARGIN", new_y="NEXT")
        elif block.role == "bullet":
            pdf.set_x(pdf.l_margin + 4)
            pdf.multi_cell(width - 4, font_for(block.style_name()), f"• {block.text}", align="L",
                           new_x="LMARGIN", new_y="NEXT")
            pdf.ln(theme.gap_mm("between_bullets"))
        else:
            pdf.multi_cell(width, font_for(block.style_name()), block.text, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(theme.gap_mm("between_paragraphs"))

    for group in _groups(classify(markdown, theme.section_styles)):
        guarded = group
        if group and group[0].role in ("section", "experience") and len(group) > 1:
            if block_height(group[-1]) > 35:
                guarded = group[:-1]
        needed = sum(block_height(block) for block in guarded)
        if needed < frame * 0.9 and pdf.will_page_break(needed):
            pdf.add_page()
        for block in group:
            draw(block)
    if abs(pdf.w - page_w) > 1 or abs(pdf.h - page_h) > 1:
        raise ThemeError("A página renderizada não corresponde ao formato do tema. Nada foi salvo.")
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def render_docx(markdown: str, path: Path, theme: Theme | None = None) -> Path:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Mm, Pt, RGBColor

    theme = theme or load_theme()
    _guard(markdown, theme)
    document = docx.Document()
    section = document.sections[0]
    page_w, page_h = theme.page_mm()
    section.page_width = Mm(page_w)
    section.page_height = Mm(page_h)
    section.left_margin = section.right_margin = section.top_margin = section.bottom_margin = Cm(theme.margins_cm)
    for container in (section.header, section.footer):
        for paragraph in container.paragraphs:
            paragraph.text = ""
    normal = document.styles["Normal"]
    normal.font.name = theme.resolved_font
    normal.font.size = Pt(theme.style("body").size_pt)
    normal.font.color.rgb = RGBColor(*theme.rgb("primary"))
    normal.font.bold = False
    normal.font.italic = False

    def paint(run, style_name: str, color: str) -> None:
        style = theme.style(style_name)
        run.font.name = theme.resolved_font
        run.bold = style.bold
        run.italic = False
        run.underline = False
        run.font.size = Pt(style.size_pt)
        run.font.color.rgb = RGBColor(*theme.rgb(color))
        fonts = run._element.get_or_add_rPr().find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            run._element.get_or_add_rPr().append(fonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs"):
            fonts.set(qn(attr), theme.resolved_font)

    def paragraph(text: str, style_name: str, color: str, *, before: float = 0, after: float = 0,
                  bullet: bool = False, keep_with_next: bool = False, keep_together: bool = False):
        block = document.add_paragraph()
        formatting = block.paragraph_format
        formatting.alignment = WD_ALIGN_PARAGRAPH.LEFT
        formatting.line_spacing = theme.line_height
        formatting.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        formatting.space_before = Pt(before)
        formatting.space_after = Pt(after)
        formatting.widow_control = True
        formatting.keep_together = keep_together
        formatting.keep_with_next = keep_with_next
        paint(block.add_run(("• " if bullet else "") + text), style_name, color)
        return block

    def divider(block) -> None:
        if not theme.dividers:
            return
        border = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), theme.colors["divider"].lstrip("#"))
        border.append(bottom)
        block._p.get_or_add_pPr().append(border)

    for block in classify(markdown, theme.section_styles):
        if block.role == "name":
            paragraph(block.text, "name", "primary", after=theme.spacing_pt["after_name"], keep_with_next=True)
        elif block.role == "professional_title":
            paragraph(block.text, "professional_title", "secondary", keep_with_next=True)
        elif block.role == "contact":
            paragraph(block.text, "contact", "secondary", after=theme.spacing_pt["after_contacts"])
        elif block.role == "section":
            divider(paragraph(block.text, "section_title", "primary",
                              before=theme.spacing_pt["before_sections"], after=theme.spacing_pt["after_titles"],
                              keep_with_next=True))
        elif block.role == "experience":
            before = theme.spacing_pt["between_experiences"] if block.extra_before else 0
            row = document.add_paragraph()
            row.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            row.paragraph_format.line_spacing = theme.line_height
            row.paragraph_format.space_before = Pt(before)
            row.paragraph_format.space_after = Pt(0)
            row.paragraph_format.widow_control = True
            row.paragraph_format.keep_with_next = True
            row.paragraph_format.keep_together = True
            paint(row.add_run(block.text), "role", "primary")
            if block.company:
                paint(row.add_run(" — " + block.company), "company", "primary")
        elif block.role == "date":
            paragraph(block.text, "date", "secondary", keep_with_next=True, keep_together=True)
        elif block.role == "bullet":
            paragraph(block.text, block.style_name(), "primary", after=theme.spacing_pt["between_bullets"],
                      bullet=True, keep_together=True)
        else:
            paragraph(block.text, block.style_name(), "primary", after=theme.spacing_pt["between_paragraphs"],
                      keep_together=True)
    if document.paragraphs and not document.paragraphs[0].text:
        document.paragraphs[0]._element.getparent().remove(document.paragraphs[0]._element)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(path))
    return path
