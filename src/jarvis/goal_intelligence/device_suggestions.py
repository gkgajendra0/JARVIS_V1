"""Owner-facing device *candidates* from fresh, unverified Windows observations.

Read-only decoding of canonical GICC InformationNeed evidence. This is never
device identity attestation, a secret source, pairing, or execution authority.
Owner interactions remain separately bound to exact goal and InformationNeed.
"""

from __future__ import annotations

import ipaddress
import re
import time
from dataclasses import dataclass

from .information import can_rediscover_information
from .models import GoalState
from .store import GoalStore
from .world import canonical_world_entity_type

_AEP_RE = re.compile(
    r"^windows_aep_(?P<source>discovered|neighbor_correlated)_unverified:"
    r"(?P<outer>\d{1,3}(?:\.\d{1,3}){3}):"
    r"windows_aep_unverified:(?P<protocol>upnp|dns_sd|wsd):"
    r"(?P<inner>\d{1,3}(?:\.\d{1,3}){3}):"
    r"vendor=(?P<vendor>[a-z0-9_]{1,40}):"
    r"model=(?P<model>[a-z0-9_]{1,40}):"
    r"category=(?P<category>[a-z0-9_]{1,40}):"
    r"at=(?P<observed>\d{12}):(?P<digest>[a-f0-9]{24})$"
)
_LOCAL_NETWORKS = tuple(
    ipaddress.IPv4Network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_MAX_AGE_SECONDS = 120


@dataclass(frozen=True, slots=True)
class UnverifiedDeviceSuggestionV1:
    """Safe, short-lived display hint for an explicitly bound owner choice."""

    address: str
    protocol: str
    manufacturer_hint: str
    model_hint: str
    category_hint: str
    observed_at_epoch: int
    neighbor_correlated: bool
    evidence_ref: str

    @property
    def display_hint(self) -> str:
        labels = (
            value.replace("_", " ")
            for value in (self.manufacturer_hint, self.model_hint)
            if value != "unknown"
        )
        return " ".join(labels) or "Unidentified network device"


def _decode(ref: str, *, now_epoch: int) -> UnverifiedDeviceSuggestionV1 | None:
    match = _AEP_RE.fullmatch(ref)
    if match is None:
        return None
    fields = match.groupdict()
    if fields["outer"] != fields["inner"]:
        return None
    try:
        address = ipaddress.IPv4Address(fields["outer"])
        observed = int(fields["observed"])
    except ValueError:
        return None
    if not any(address in net for net in _LOCAL_NETWORKS):
        return None
    if observed > now_epoch or now_epoch - observed > _MAX_AGE_SECONDS:
        return None
    if fields["vendor"] == "unknown" and fields["model"] == "unknown":
        return None
    return UnverifiedDeviceSuggestionV1(
        address=str(address),
        protocol=fields["protocol"],
        manufacturer_hint=fields["vendor"],
        model_hint=fields["model"],
        category_hint=fields["category"],
        observed_at_epoch=observed,
        neighbor_correlated=fields["source"] == "neighbor_correlated",
        evidence_ref=ref,
    )


def pending_owner_device_suggestions(
    *,
    store: GoalStore,
    goal_id: str,
    session_id: str,
    now_epoch: int | None = None,
) -> tuple[UnverifiedDeviceSuggestionV1, ...]:
    """Present at most eight unverified candidates, never infer a target.

    Conflicting recent metadata on the same address cancels the entire
    suggestion for that address rather than picking a convenient label.
    """

    if not isinstance(store, GoalStore):
        raise TypeError("suggestions require the canonical GICC GoalStore")
    goal = store.get_goal(goal_id)
    if (
        goal is None
        or goal.state is not GoalState.WAITING_INFORMATION
        or not isinstance(session_id, str)
        or goal.source_session_id != session_id.strip()
    ):
        return ()
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    grouped: dict[str, list[UnverifiedDeviceSuggestionV1]] = {}
    for need in store.list_information_needs(goal_id=goal.goal_id):
        if (
            not can_rediscover_information(need)
            or need.answer_schema.get("type") != "entity_id"
            or canonical_world_entity_type(need.answer_schema.get("entity_type"))
            not in {"media_player", "camera"}
        ):
            continue
        for ref in need.evidence_refs:
            suggestion = _decode(ref, now_epoch=now)
            if suggestion is not None:
                grouped.setdefault(suggestion.address, []).append(suggestion)

    suggestions: list[UnverifiedDeviceSuggestionV1] = []
    for address, items in sorted(grouped.items()):
        signatures = {
            (row.manufacturer_hint, row.model_hint, row.category_hint) for row in items
        }
        if len(signatures) != 1:
            continue
        best = min(
            items,
            key=lambda row: (
                -row.observed_at_epoch,
                not row.neighbor_correlated,
                row.protocol,
                row.evidence_ref,
            ),
        )
        suggestions.append(best)
    return tuple(suggestions[:8])
