import json

from fixtures import RESUME_LINES, FakeHttp, default_routes, write_docx

from devjob.cli import main


def run(capsys, http, *args):
    code = main(["--json", *args], http_client=http)
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip() else None


def test_end_to_end_cli(tmp_path, capsys):
    http = FakeHttp(default_routes())
    cv = write_docx(tmp_path / "cv.docx", RESUME_LINES)

    code, data = run(capsys, http, "init")
    assert code == 0

    code, data = run(capsys, http, "search")
    assert code == 1 and "perfil" in data["error"].lower()

    code, data = run(capsys, http, "profile", "import", str(cv))
    assert code == 0 and data["draft_path"]
    code, data = run(capsys, http, "profile", "accept")
    assert data["version"] == 1
    code, data = run(capsys, http, "profile", "import", str(cv))
    assert data["already_accepted"]

    for key, value in [("target_roles", "[Backend Engineer]"), ("seniority.levels", "[senior]"),
                       ("location.country", "BR"), ("work_model.accepted", "[remote]"),
                       ("salary.minimums", "[{currency: BRL, amount: 18000, period: month, contract: clt}]")]:
        code, _ = run(capsys, http, "prefs", "set", key, value)
        assert code == 0
    code, data = run(capsys, http, "prefs", "set", "work_model.accepted", "[spaceship]")
    assert code == 1

    code, data = run(capsys, http, "companies", "add", "https://boards.greenhouse.io/acmecloud")
    assert code == 0 and data["name"] == "Acme Cloud"
    code, data = run(capsys, http, "companies", "add", "https://jobs.lever.co/betaco", "--name", "BetaCo")
    assert code == 0
    code, data = run(capsys, http, "companies", "add", "https://example.com/careers")
    assert code == 1

    code, data = run(capsys, http, "search", "--query", "Backend Java Sênior remoto", "--limit", "20")
    assert code == 1 and "empregador" in data["error"].lower()
    code, data = run(capsys, http, "employment", "confirm", "--current", "Acme Pagamentos")
    assert code == 0 and data["status"] == "employed"
    code, data = run(capsys, http, "search", "--query", "Backend Java Sênior remoto", "--limit", "20")
    assert code == 0
    ids = [r["job"]["id"] for r in data["results"]]
    assert "greenhouse:acmecloud:1001" in ids
    first = data["results"][0]
    assert first["match"]["justification"] and "components" in first["match"]
    assert all(r["job"]["url"].startswith("https://") for r in data["results"])

    web = tmp_path / "web.json"
    web.write_text(json.dumps([{"title": "Senior Backend Engineer", "company": "Acme Cloud",
                                "url": "https://job-boards.greenhouse.io/acmecloud/jobs/1001?utm_source=x"}]),
                   encoding="utf-8")
    code, data = run(capsys, http, "jobs", "import", str(web))
    assert data["imported"][0]["outcome"] == "duplicate"

    code, data = run(capsys, http, "jobs", "show", "greenhouse:acmecloud:1001")
    assert data["description_untrusted"] and data["verification"] == "listed"

    code, data = run(capsys, http, "prepare", "greenhouse:acmecloud:1001")
    assert data["status"] == "needs_resume"

    code, data = run(capsys, http, "resumes", "generate", "--job", "greenhouse:acmecloud:1001", "--language", "en")
    assert code == 0 and data["errors"] == []
    code, data = run(capsys, http, "resumes", "approve", data["draft_id"])
    assert code == 0 and data["pdf_path"].endswith("resume.pdf")
    resume_id = data["id"]

    code, data = run(capsys, http, "prepare", "greenhouse:acmecloud:1001")
    assert data["status"] == "prepared" and data["resume_id"] == resume_id
    app_id = data["application_id"]

    code, data = run(capsys, http, "applications", "status", app_id, "submitted")
    assert code == 1 and "evidência" in data["error"]
    code, data = run(capsys, http, "apply", app_id)
    assert code == 1 and "não implementado" in data["error"]
    code, data = run(capsys, http, "applications", "status", app_id, "submitted", "--evidence",
                     "Protocolo GH-2026-0001 recebido por e-mail")
    assert code == 0 and data["to"] == "submitted"

    code, data = run(capsys, http, "applications", "list")
    assert data[0]["status"] == "submitted" and data[0]["resume_id"] == resume_id

    code, data = run(capsys, http, "profile", "status")
    assert data["version"] >= 1


def test_help_lists_every_command(tmp_path, capsys):
    assert main(["help"]) == 0
    out = capsys.readouterr().out
    for command in ("devjob init", "devjob search", "devjob profile import <file>", "devjob resumes approve <draft>",
                    "devjob applications status <id> <status>", "devjob jobs ignore <job> [--undo]"):
        assert command in out
    assert "aprova rascunho" in out
    assert not (tmp_path / "home").exists(), "help não cria o diretório de dados"

    code, data = run(capsys, None, "help", "resumes")
    assert code == 0 and data and all(e["command"].startswith("resumes ") for e in data)
    code, data = run(capsys, None, "help", "inexistente")
    assert code == 1 and "Grupo desconhecido" in data["error"]
    assert "devjob mode" not in out
    assert "--confirm" not in out
    assert "dev on" not in out
    assert "==SUPPRESS==" not in out
    code, listed = run(capsys, None, "help")
    assert code == 0 and all(item["command"] != "mode" for item in listed)
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    public = capsys.readouterr().out
    assert ",mode," not in public and ",mode}" not in public
    assert "--confirm" not in public and "dev on" not in public and "==SUPPRESS==" not in public


def test_human_output_is_readable(tmp_path, capsys):
    http = FakeHttp(default_routes())
    assert main(["init"], http_client=http) == 0
    out = capsys.readouterr().out
    assert "Diretório de dados" in out
    assert main(["profile", "show"], http_client=http) == 1
    assert "Importe um currículo" in capsys.readouterr().err
