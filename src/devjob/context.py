"""Per-command runtime context."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from functools import cached_property

from devjob.config.settings import Paths, ensure_layout, load_config, resolve_home
from devjob.profile import preferences
from devjob.profile.service import load_profile, require_profile, sync_version
from devjob.providers.http import HttpClient
from devjob.security import setup_logging
from devjob.storage.db import connect


@dataclass
class Context:
    paths: Paths
    http_client: HttpClient | None = None
    notes: list[str] = field(default_factory=list)

    @cached_property
    def config(self) -> dict:
        return load_config(self.paths)

    @cached_property
    def conn(self) -> sqlite3.Connection:
        return connect(self.paths.db)

    @property
    def http(self) -> HttpClient:
        if self.http_client is None:
            cfg = self.config["http"]
            self.http_client = HttpClient(cfg["user_agent"], cfg["timeout_seconds"], cfg["min_interval_seconds"],
                                          cfg["max_retries"])
        return self.http_client

    def prefs(self) -> dict:
        return preferences.load_preferences(self.paths.preferences)

    def profile(self, required: bool = True):
        return require_profile(self.paths) if required else load_profile(self.paths)

    def profile_version(self) -> int:
        version, _ = sync_version(self.conn, self.paths)
        return version


def open_context(home: str | None = None, http_client: HttpClient | None = None) -> Context:
    paths = Paths(resolve_home(home))
    notes = ensure_layout(paths)
    setup_logging(paths.logs)
    return Context(paths, http_client, notes)
