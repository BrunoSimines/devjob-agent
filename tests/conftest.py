from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures import PREFERENCES, RESUME_LINES, FakeHttp, default_routes, write_docx  # noqa: E402

from devjob.config.settings import deep_merge  # noqa: E402
from devjob.context import open_context  # noqa: E402
from devjob.profile import preferences, service  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVJOB_HOME", str(tmp_path / "home"))


@pytest.fixture
def http():
    return FakeHttp(default_routes())


@pytest.fixture
def ctx(tmp_path, http):
    context = open_context(str(tmp_path / "home"), http)
    yield context
    if "conn" in context.__dict__:
        context.conn.close()


@pytest.fixture
def resume_docx(tmp_path) -> Path:
    return write_docx(tmp_path / "joana.docx", RESUME_LINES)


@pytest.fixture
def profiled_ctx(ctx, resume_docx):
    """Context with the fictional resume imported and accepted, plus preferences."""
    service.import_resume(ctx.conn, ctx.paths, resume_docx)
    service.accept_draft(ctx.conn, ctx.paths)
    prefs = deep_merge(preferences.defaults(), PREFERENCES)
    preferences.save_preferences(ctx.paths.preferences, prefs)
    return ctx
