# DevJob Agent

Assistente de carreira local, gratuito e open source. Ele lê o seu currículo, guarda um perfil editável, busca vagas reais, explica a compatibilidade e monta o pacote da candidatura para você enviar.

Os seus dados ficam na sua máquina. Nada é inventado: uma dedução só entra no perfil depois que você confirma. A candidatura é preparada; o envio fica com você.

Funciona de dois jeitos:

- no **Claude Code** ou no **Cursor**, conversando com a skill `/devjob-agent`;
- no terminal, com a CLI `devjob`.

## O que você precisa

- Python 3.11 ou mais novo
- Git
- Claude Code ou Cursor, se quiser usar a skill. A CLI funciona sozinha.

## Instalar

Se o Python ainda não estiver instalado:

- Windows: `winget install Python.Python.3.12`
- macOS: `brew install python@3.12`
- Linux: o pacote `python3.12` da sua distribuição

Baixe o código e rode o instalador na pasta do projeto:

```bash
git clone https://github.com/BrunoSimines/devjob-agent.git devjob-agent
cd devjob-agent
python scripts/install.py
```

No Windows, se `python` não estiver no PATH, use `py scripts/install.py`.

O instalador:

1. cria um Python isolado em `~/.devjob-agent/runtime/venv` e instala o programa ali;
2. cria os seus dados em `~/.devjob-agent` (banco, preferências e configuração);
3. instala a skill em `~/.claude/skills/devjob-agent/`. O Claude Code lê essa pasta, e o [Cursor também](https://cursor.com/docs/skills);
4. grava na skill o caminho da CLI, para o agente achá-la sem depender do PATH.

Abra de novo o Claude Code ou o Cursor depois da instalação, para a skill aparecer.

### Conferir

O instalador não coloca `devjob` no PATH. Use o caminho completo.

Windows (PowerShell):

```powershell
& "$env:USERPROFILE\.devjob-agent\runtime\venv\Scripts\devjob.exe" doctor
```

macOS e Linux:

```bash
~/.devjob-agent/runtime/venv/bin/devjob doctor
```

`doctor` diz se a instalação e as preferências estão em ordem. Para usar só `devjob` no terminal, acrescente a pasta `Scripts` (Windows) ou `bin` (macOS e Linux) ao PATH.

Nos exemplos abaixo, `devjob` significa esse comando. No Windows, troque pelo caminho entre aspas com `&` na frente, como no exemplo do `doctor`.

### Opções do instalador

| Opção | Efeito |
|---|---|
| `--target cursor` | instala só em `~/.cursor/skills` |
| `--target both` | instala em `.claude/skills` e `.cursor/skills` |
| `--scope project --project-dir <pasta>` | instala a skill dentro de um projeto |
| `--home <pasta>` | usa outro diretório de dados |
| `--uninstall` | remove a skill e mantém os seus dados |

## Usar no chat

No Claude Code ou no Cursor, digite `/devjob-agent` e a ação, ou peça em linguagem natural.

| Você quer | Peça |
|---|---|
| Começar | `/devjob-agent setup` |
| Atualizar o currículo ou um fato | `/devjob-agent profile` |
| Procurar vagas | `/devjob-agent search` |
| Entender uma vaga | `/devjob-agent match` |
| Montar a candidatura | `/devjob-agent prepare` |
| Acompanhar o que você já enviou | `/devjob-agent applications` |

Exemplo: "procure vagas de backend sênior, remotas, em português".

A skill mostra o que vai mudar e espera a sua aprovação antes de gravar o perfil, aprovar um currículo ou preparar uma candidatura. O texto do currículo que ela lê é processado pelo provedor do modelo da sua sessão. A busca na web usa cargo, habilidades e local; nome, e-mail, telefone e empregadores ficam de fora da consulta.

## Usar no terminal

### 1. Importar o currículo

```bash
devjob profile import ~/curriculo.pdf
devjob profile review
devjob profile accept
```

`import` cria um rascunho. `review` mostra o que muda. `accept` grava `~/.devjob-agent/profile.md`. Sem `accept`, o perfil não é atualizado.

Cada fato fica marcado com a origem: `[resume]` veio do currículo, `[user]` foi você quem disse, `[inferred]` é uma dedução e só conta depois de `devjob profile confirm "<texto>"`.

### 2. Dizer o que você procura

```bash
devjob prefs show
devjob prefs set work_model.accepted "[remote]"
devjob prefs set contract_types.accepted "[clt, pj]"
devjob prefs set location.country "BR"
devjob prefs set location.city "São Paulo"
```

Um requisito com `eliminatory: true` descarta a vaga quando a informação existe e viola a regra. Salário, modelo de trabalho ou contrato ausentes ficam como incertos; ausência não elimina.

Exemplo de salário mínimo, em reais por mês:

```bash
devjob prefs set salary.minimums "[{contract: clt, currency: BRL, amount: 18000, period: month}]"
```

As chaves estão em [references/preferences.md](references/preferences.md). Um exemplo completo, fictício, está em `examples/preferences.example.yaml`.

### 3. Confirmar emprego

Antes da primeira busca personalizada, confirme a situação atual. A última experiência do currículo não vira emprego atual sozinha.

```bash
devjob employment confirm --current "Empresa Atual" --alias "Outra grafia"
devjob employment previous "Empresa Anterior"
```

Se estiver sem emprego: `devjob employment confirm --unemployed`.

A empresa atual não entra nas recomendações. Empresas anteriores também ficam de fora até você liberar uma com `devjob employment allow "Nome"`.

### 4. Buscar vagas

Pelo chat, a skill monta as consultas, pesquisa na web e importa só a página da empresa ou de um quadro oficial (Greenhouse, Lever, Ashby, InHire, Gupy, SmartRecruiters, Workday). Um site que só republica o anúncio não é o link de candidatura.

Pelo terminal, cadastre os quadros e rode a busca:

```bash
devjob companies add https://job-boards.greenhouse.io/<empresa>
devjob companies detect https://empresa.com/carreiras --add
devjob search --query "backend java senior" --remote --limit 20
```

`search` atualiza os quadros cadastrados, compara com o seu perfil e mostra a lista. `devjob match <id>` explica uma vaga. O id pode ser o número da lista, um pedaço do id ou a URL.

`--remote` e os outros filtros de `search` valem só para aquela execução. Para guardar a regra, use `prefs set`.

### 5. Preparar a candidatura

```bash
devjob resumes add ~/curriculo.pdf --label "Geral" --role "Backend Engineer"
devjob resumes select <id-da-vaga>
devjob prepare <id-da-vaga>
```

`prepare` cria a pasta `~/.devjob-agent/applications/<id>/` com o currículo, a vaga, a análise e um checklist. Nada é enviado.

Quando você mesmo enviar, registre com a evidência que recebeu:

```bash
devjob applications status <id> submitted --evidence "protocolo ou e-mail de confirmação"
```

Outros status: `interviewing`, `rejected`, `offer`, `closed`.

### Ajuda

`devjob help` lista os comandos. `devjob help resumes` mostra um grupo. `devjob search --help` mostra as opções de um comando. A referência completa está em [references/cli.md](references/cli.md).

Para saída em JSON, `--json` vem antes do comando: `devjob --json doctor`.

## Onde ficam os seus dados

Tudo em `~/.devjob-agent` (ou na pasta de `DEVJOB_HOME`):

| Arquivo ou pasta | Conteúdo |
|---|---|
| `profile.md` | perfil profissional |
| `preferences.yaml` | o que você procura |
| `config.yaml` | pesos da compatibilidade e formato de página |
| `devjob.db` | vagas, buscas e candidaturas |
| `resumes/` | currículos da biblioteca |
| `applications/` | pacotes preparados |
| `imports/` | textos e planos temporários |
| `logs/devjob.log` | log com e-mail e telefone mascarados |

Esses arquivos ficam fora do repositório. O `.gitignore` também bloqueia currículo, banco e PDF caso o diretório de dados seja apontado para dentro do projeto.

## O que já funciona

| Parte | Situação |
|---|---|
| Perfil a partir de PDF ou DOCX, revisão e versões | funciona na sua máquina |
| Preferências | funciona na sua máquina |
| Greenhouse, Lever e InHire | funciona, lendo a API pública de cada quadro |
| Busca web pela skill, mais `companies detect` e `jobs import` | funciona, usando a busca do Claude Code ou do Cursor |
| Página com JSON-LD `JobPosting` (`jobs add-url`) | funciona, lendo a página da vaga |
| Compatibilidade, biblioteca de currículos, PDF e DOCX | funciona na sua máquina |
| Pacote de candidatura | funciona; o envio é seu |
| Preenchimento assistido no navegador e envio automático | ainda não existem |
| OCR de PDF escaneado | ainda não existe |

## Privacidade

- A CLI, sozinha, não envia o currículo para nenhum serviço.
- Com a skill, o provedor do modelo da sessão processa o texto do currículo, do perfil e das vagas que o agente analisa, segundo os termos desse provedor.
- A internet recebe só leituras das APIs públicas de vagas e das páginas que você pedir para consultar.
- O programa se identifica nas requisições, espera entre um acesso e outro no mesmo site, respeita `Retry-After` e para diante de login, CAPTCHA ou bloqueio.
- Texto de anúncio é dado, não ordem. A skill não executa instrução encontrada numa vaga.

## Como a compatibilidade é calculada

Oito critérios, com pesos em `config.yaml`: requisitos obrigatórios, experiência, requisitos desejáveis, senioridade, idiomas, local e regime, remuneração e preferências. Critério sem informação sai da nota e aparece como incerto. A ordenação usa nota vezes confiança, então falta de dado não empurra uma vaga para o topo. Vaga sem requisitos identificáveis não sai como recomendada.

A escolha do currículo é outra conta: ele mostra o que você tem e a vaga pede? O programa reaproveita um currículo já salvo quando ele serve para aquele tipo de vaga. Uma versão nova só é proposta quando a história seria outra, por exemplo outro idioma ou outro nível de cargo. O rascunho usa fatos confirmados, e a verificação recusa empresa, cargo, data, número ou tecnologia que não estejam no perfil.

## Para quem desenvolve

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

No Windows: `.venv\Scripts\pip install -e ".[dev]"` e `.venv\Scripts\pytest`.

Os testes usam dados fictícios e respostas HTTP simuladas. Não acessam a rede.

Para incluir outro quadro de vagas:

1. crie `src/devjob/providers/<nome>.py` com uma subclasse de `JobProvider` (`fetch_jobs`, `fetch_job`, `validate_source`), usando só endpoints documentados;
2. registre a classe em `providers/__init__.py` e o padrão de URL em `discovery/detect.py`;
3. preencha `field_sources` e use `verification="listed"` só quando a vaga veio da listagem oficial;
4. cubra o provedor com testes de resposta simulada.

```text
SKILL.md              skill do Claude Code e do Cursor
prompts/              instruções versionadas de cada fluxo
references/           documentação lida pelo agente
scripts/install.py    instalador
src/devjob/           CLI, perfil, busca, compatibilidade, currículos
tests/                testes sem rede
examples/             preferências, fontes e currículos fictícios
```

## Licença

MIT. Dependências: pypdf (BSD-3-Clause), python-docx (MIT), PyYAML (MIT), fpdf2 (LGPL-3.0, usada como biblioteca, sem modificações).
