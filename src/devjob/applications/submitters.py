"""Extension points for assisted (mode 2) and automated (mode 3) submission.

Neither mode is implemented in the MVP. The interfaces exist so integrations
can be added later; until then every call raises ``SubmissionNotSupported`` and
the user receives the prepared package and the original link.

Rules any future implementation must follow:
* explicit user consent per batch of applications (``Consent``);
* only technically supported and authorized integrations (e.g. documented
  application APIs with credentials the user owns);
* never bypass CAPTCHA, anti-bot controls or authentication;
* show the filled data for review before sending;
* record ``submitted`` only with verifiable confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SubmissionNotSupported(Exception):
    pass


@dataclass(frozen=True)
class Consent:
    application_ids: tuple[str, ...]
    granted_at: str
    confirmed_by_user: bool


@dataclass
class SubmissionResult:
    application_id: str
    submitted: bool
    evidence: str | None
    message: str


class Submitter(Protocol):
    name: str
    mode: str  # "assisted" | "automated"

    def can_handle(self, job) -> bool: ...

    def submit(self, application, job, consent: Consent) -> SubmissionResult: ...


REGISTRY: list[Submitter] = []


def find_submitter(job, mode: str) -> Submitter:
    for submitter in REGISTRY:
        if submitter.mode == mode and submitter.can_handle(job):
            return submitter
    raise SubmissionNotSupported(
        f"Modo '{mode}' ainda não implementado nesta versão. Use o pacote preparado e o link original da vaga "
        "para se candidatar manualmente; depois registre com `devjob applications status <id> submitted "
        "--evidence ...`."
    )
