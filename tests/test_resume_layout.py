"""Layout of the minimal-professional template for short, medium and long histories."""

from pathlib import Path

import pytest
import yaml

from devjob.resumes.layout_check import check_pdf
from devjob.resumes.render import render_docx, render_pdf
from devjob.resumes.theme import ThemeError, apply_page_format, load_theme

SHORT = """# Marina Costa
Analista de operações
marina.costa@example.com · São Paulo

## Resumo
Profissional em início de carreira, com prática em organização de processos e atendimento.

## Competências técnicas
- Planilhas, atendimento e controle de documentos

## Experiência
### Analista de operações — Oficina Litoral
03/2024 – Atual · São Paulo
- Organizei a fila diária de pedidos da oficina.
- Atualizei a planilha de estoque uma vez por semana.

## Formação
- Tecnólogo em Gestão, Faculdade Horizonte (2023)
"""

MEDIUM = """# Helena Duarte
Coordenadora de projetos
helena.duarte@example.com · Recife

## Resumo
Coordena projetos de operações e acompanha prazos, custos e entregas com equipes pequenas.

## Competências técnicas
- Planejamento, relatórios, facilitação de reuniões

## Experiência
### Coordenadora de projetos — Estúdio Norte
01/2022 – Atual · Recife
- Planejei o calendário de entregas de três frentes de trabalho.
- Reuni o status semanal e registrei os impedimentos.
- Acompanhei contratos com fornecedores locais.

### Analista de projetos — Casa do Porto
06/2018 – 12/2021 · Recife
- Montei cronogramas e atas das reuniões de acompanhamento.
- Organizei o arquivo de propostas e versões aprovadas.

### Assistente administrativa — Mercado da Praça
02/2016 – 05/2018 · Olinda
- Atendi fornecedores e conferi notas de recebimento.
- Mantive a agenda da coordenação e os protocolos internos.

## Formação
- Graduação em Administração, Universidade do Atlântico (2015)

## Certificações
- Curso de gestão de projetos, Instituto da Orla (2019)
"""


def _job(index: int) -> str:
    start = 2012 + index
    return f"""### Especialista de operações — Companhia {index + 1}
01/{start} – 12/{start + 1} · Cidade {index + 1}
- Conduzi a rotina de planejamento da unidade {index + 1} durante todo o período.
- Registrei indicadores semanais e expliquei os desvios nas reuniões de acompanhamento.
- Reorganizei o fluxo de pedidos para reduzir retrabalho entre as equipes da unidade.
- Documentei os procedimentos usados pelos turnos da manhã e da tarde.
- Treinei pessoas novas no uso das planilhas e do arquivo de protocolos.
"""


LONG = """# Rafael Nogueira
Especialista de operações
rafael.nogueira@example.com · Curitiba

## Resumo
Trajetória longa em operações, com histórico confirmado em várias unidades e equipes.

## Competências técnicas
- Planejamento, indicadores, procedimentos, treinamento de equipes

## Experiência
""" + "\n".join(_job(index) for index in range(7)) + """
## Formação
- Graduação em Engenharia de Produção, Instituto do Paraná (2011)

## Certificações
- Formação interna de supervisão, Companhia 3 (2016)
"""


def test_theme_refuses_to_shrink_body_text(tmp_path):
    theme = load_theme()
    assert theme.style("skills").size_pt == 10
    assert theme.style("education").size_pt == 10.5
    assert theme.style("body").bold is False
    assert theme.fallbacks[:3] == ("Calibri", "Aptos", "Liberation Sans")
    data = yaml.safe_load(Path(theme.path).read_text(encoding="utf-8"))
    data["typography"]["body"]["size_pt"] = 8
    broken = tmp_path / "theme.yaml"
    broken.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ThemeError) as exc:
        load_theme(broken)
    assert "10" in str(exc.value)
    with pytest.raises(ThemeError):
        apply_page_format(theme, {"resumes": {"page_format": "A3"}})


def test_letter_changes_only_the_page(tmp_path):
    letter = load_theme().with_page_format("Letter")
    assert letter.page_mm() == (215.9, 279.4)
    assert letter.style("name").size_pt == 20
    pdf = tmp_path / "letter.pdf"
    render_pdf(SHORT, pdf, letter)
    report = check_pdf(pdf, SHORT, letter)
    assert report.ok, report.errors


def test_short_medium_and_long_profiles(tmp_path):
    theme = load_theme()
    expectations = {"short": (SHORT, 1, 1), "medium": (MEDIUM, 1, 2), "long": (LONG, 2, 4)}
    for name, (markdown, low, high) in expectations.items():
        folder = tmp_path / name
        pdf = folder / "resume.pdf"
        docx = folder / "resume.docx"
        render_pdf(markdown, pdf, theme)
        render_docx(markdown, docx, theme)
        report = check_pdf(pdf, markdown, theme, preview_dir=folder)
        assert report.ok, report.errors
        assert report.previews
        assert low <= report.pages <= high
        assert "compatibilidade universal" in report.note
        assert docx.stat().st_size > 1000
        import zipfile
        xml = zipfile.ZipFile(docx).read("word/document.xml")
        assert b"Arial" in xml
