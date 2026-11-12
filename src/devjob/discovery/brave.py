"""Optional Brave Search API. Native host search is the default and stays free."""

from __future__ import annotations

import os
from urllib.parse import urlencode

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveNotConfigured(RuntimeError):
    """Raised when Brave was selected but the user did not provide a key."""


def provider_status(config: dict) -> dict:
    discovery = (config.get("search") or {}).get("discovery") or {}
    provider = str(discovery.get("provider") or "native")
    env_name = str(discovery.get("brave_api_key_env") or "DEVJOB_BRAVE_API_KEY")
    configured = provider == "brave" and bool(os.environ.get(env_name))
    return {"mode": provider, "paid_api_required": False, "brave_configured": configured,
            "brave_api_key_env": env_name}


def brave_configured(config: dict) -> bool:
    return provider_status(config)["brave_configured"]


def request_urls(query: str, config: dict) -> list[str]:
    """Pages the optional client would request. Building them does not contact the network."""
    discovery = (config.get("search") or {}).get("discovery") or {}
    count = int(discovery.get("max_results_per_query") or 10)
    pages = max(1, int(discovery.get("max_pages") or 1))
    urls = []
    for page in range(pages):
        params = urlencode({"q": query, "count": count, "offset": page * count})
        urls.append(f"{BRAVE_ENDPOINT}?{params}")
    return urls


def search(http, query: str, config: dict) -> list[dict]:
    if not brave_configured(config):
        raise BraveNotConfigured(
            "Brave Search não está configurado. A pesquisa nativa do ambiente segue disponível "
            "e nenhuma API paga é obrigatória.")
    env_name = provider_status(config)["brave_api_key_env"]
    headers = {"X-Subscription-Token": os.environ[env_name], "Accept": "application/json"}
    hits = []
    for url in request_urls(query, config):
        payload = http.get_json(url, headers=headers)
        for item in ((payload or {}).get("web") or {}).get("results") or []:
            if item.get("url"):
                hits.append({"title": item.get("title") or "", "url": item["url"],
                             "snippet": item.get("description") or ""})
    return hits
