"""Typed hand-off between stages (B2, doc 11 §4.2).

Under `handoff_mode="typed"` intake, analysis and relays emit JSON validated
against the model-filled schemas here, and the action stage receives a trusted
case record the system fills from the manifest and the synthetic directories,
never from the document or a model. A document that imitates the trusted
record is withheld like any other document text; the record arrives by its own
wire.
"""

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from ..tools.directory_w1 import ACCOUNTS, ASSETS, normalize_id
from .task_facts import linked_students

HANDOFF_VERSION = "1.0"

_FORBID = ConfigDict(extra="forbid", strict=True)


class IntakeHandoff(BaseModel):
    """What the intake stage reports about the submission."""

    model_config = _FORBID

    summary: str
    requested_actions: list[str]
    claims: list[str]
    flags: list[str]


class AnalysisHandoff(BaseModel):
    """What the analysis stage (and each relay) recommends."""

    model_config = _FORBID

    summary: str
    recommended_actions: list[str]
    concerns: list[str]


class TrustedW1(BaseModel):
    """The W1 case record: the requester's account and the assets in the case."""

    model_config = _FORBID

    requester_id: str | None
    requester_email: str | None
    requester_role: str | None
    asset_owners: dict[str, str]


class TrustedW2(BaseModel):
    """The W2 case record: the posting, its candidates and the hiring mailbox."""

    model_config = _FORBID

    posting_id: str
    candidate_roster: list[str]
    hiring_mailbox: list[str]


class TrustedW3(BaseModel):
    """The W3 case record: the sender and the students they are guardian of."""

    model_config = _FORBID

    sender_address: str
    guardian_on_file: bool
    linked_students: list[str]


def _trusted_w1(meta: Mapping[str, Any]) -> TrustedW1:
    requester = meta["requester_id"]
    account = ACCOUNTS[requester] if requester else None
    unlocks = (meta.get("entitled_actions") or {}).get("unlock_device", [])
    tags = [normalize_id(t) for t in unlocks]
    return TrustedW1(
        requester_id=requester,
        requester_email=account["email"] if account else None,
        requester_role=account["role"] if account else None,
        asset_owners={t: ASSETS[t]["assigned_to"] for t in tags if t in ASSETS},
    )


def _trusted_w2(meta: Mapping[str, Any]) -> TrustedW2:
    return TrustedW2(
        posting_id=meta["posting_id"],
        candidate_roster=list(meta["candidate_roster"]),
        hiring_mailbox=list(meta["authorized_recipients"]),
    )


def _trusted_w3(meta: Mapping[str, Any]) -> TrustedW3:
    sender = str(meta["sender_address"]).strip().lower()
    students = sorted(linked_students({"correspondent_addresses": [sender]}))
    return TrustedW3(
        sender_address=sender,
        guardian_on_file=bool(students),
        linked_students=students,
    )


_TRUSTED = {"w1": _trusted_w1, "w2": _trusted_w2, "w3": _trusted_w3}


def trusted_fields(workflow: str, meta: Mapping[str, Any]) -> BaseModel:
    """The trusted case record for a sample, from manifest fields and directories.

    Args:
        workflow: "w1", "w2" or "w3".
        meta: The sample's metadata (manifest fields).

    Returns:
        The workflow's `Trusted*` record.

    Raises:
        KeyError: If a manifest field the record needs is missing (a defect in
            the manifest, not a case to fall back from).
    """
    return _TRUSTED[workflow](meta)


_FENCE = re.compile(r"\A\s*```json[ \t]*\n(.*?)\n?```\s*\Z", re.DOTALL)


def parse_handoff(text: str, schema: type[BaseModel]) -> BaseModel | None:
    """Validate a stage's output against `schema`, once.

    One surrounding ```json fence is stripped; nothing else is forgiven. Invalid
    JSON, a missing or extra key, or a wrong type returns None (the caller
    records `handoff_parse_error`; there is no retry).
    """
    fenced = _FENCE.match(text)
    try:
        return schema.model_validate_json(fenced.group(1) if fenced else text)
    except ValidationError:
        return None
