"""Provider registry. Add a provider by subclassing ``JobProvider`` and listing it here."""

from __future__ import annotations

from devjob.providers.base import (AccessDenied, JobProvider, ProviderError, ProviderUnavailable,
                                   SourceNotFound)
from devjob.providers.greenhouse import GreenhouseProvider
from devjob.providers.inhire import InHireProvider
from devjob.providers.lever import LeverProvider

PROVIDERS: dict[str, type[JobProvider]] = {
    GreenhouseProvider.name: GreenhouseProvider,
    LeverProvider.name: LeverProvider,
    InHireProvider.name: InHireProvider,
}


def get_provider(name: str, http) -> JobProvider:
    try:
        return PROVIDERS[name](http)
    except KeyError as exc:
        raise ProviderError(f"Provedor desconhecido: {name}. Disponíveis: {', '.join(PROVIDERS)}") from exc


__all__ = ["PROVIDERS", "get_provider", "JobProvider", "ProviderError", "ProviderUnavailable",
           "SourceNotFound", "AccessDenied"]
