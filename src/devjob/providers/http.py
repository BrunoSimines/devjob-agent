"""Polite HTTP client: identifies itself, throttles per host, retries transient
errors and honours Retry-After. It never tries to bypass 401/403, CAPTCHAs or
other access controls."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from devjob.providers.base import AccessDenied, ProviderUnavailable, SourceNotFound

log = logging.getLogger("devjob.http")
MAX_BYTES = 20 * 1024 * 1024
_RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, user_agent: str, timeout: float = 20, min_interval: float = 1.0, max_retries: int = 2,
                 sleep=time.sleep) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._sleep = sleep
        self._last_request: dict[str, float] = {}

    def _throttle(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = time.monotonic()

    def get_bytes(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        host = urlsplit(url).hostname or ""
        request_headers = {"User-Agent": self.user_agent, "Accept": "application/json, text/html;q=0.8"}
        request_headers.update(headers or {})
        attempt = 0
        while True:
            self._throttle(host)
            request = urllib.request.Request(url, headers=request_headers, method="GET")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = response.read(MAX_BYTES + 1)
                    if len(data) > MAX_BYTES:
                        raise ProviderUnavailable(f"Resposta grande demais de {host}")
                    return data
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise SourceNotFound(f"{host}: não encontrado (404)") from exc
                if exc.code in (401, 403):
                    raise AccessDenied(f"{host}: acesso negado ({exc.code}). Não será contornado.") from exc
                if exc.code in _RETRY_STATUS and attempt < self.max_retries:
                    attempt += 1
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = min(float(retry_after), 30.0) if retry_after and retry_after.isdigit() else 2.0 ** attempt
                    log.info("HTTP %s em %s; nova tentativa em %.0fs", exc.code, host, delay)
                    self._sleep(delay)
                    continue
                raise ProviderUnavailable(f"{host}: HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    self._sleep(2.0 ** attempt)
                    continue
                raise ProviderUnavailable(f"{host}: indisponível ({exc})") from exc

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        data = self.get_bytes(url, {"Accept": "application/json", **(headers or {})})
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"Resposta inválida (não é JSON) de {urlsplit(url).hostname}") from exc

    def get_text(self, url: str, headers: dict[str, str] | None = None) -> str:
        return self.get_bytes(url, {"Accept": "text/html,application/xhtml+xml", **(headers or {})}).decode(
            "utf-8", errors="replace")
