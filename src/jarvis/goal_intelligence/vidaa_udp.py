"""One-shot, owner-permitted VIDAA UDP discovery; never pairing or control.

Exactly one small JSON datagram to the directed broadcast address of one
locally configured RFC1918 LAN. Windows may route over any connected interface;
the consent summary discloses this. No subnet host enumeration occurs.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.authority.permit import PermitStatus
from jarvis.authority.proposal import ActionProposal, canonical_json
from jarvis.authority.service import AuthorityService
from jarvis.authority.types import ActionAttributes, ActionOrigin, InteractionContext
from jarvis.engineering_substrate.canonical import canonical_digest

_DISCOVERY_PORT = 36671
_PACKET = b'{"request":"discover"}'
_RFC1918 = tuple(
    ipaddress.IPv4Network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


@dataclass(frozen=True, slots=True)
class ReviewedVidaaScopeV1:
    cidr: str
    interface_index: int
    consent_record_id: str = "pending_owner_approval"
    timeout_seconds: float = 2.0
    max_results: int = 8

    def __post_init__(self) -> None:
        net = ipaddress.ip_network(self.cidr, strict=True)
        if (
            not isinstance(net, ipaddress.IPv4Network)
            or not any(net.subnet_of(private) for private in _RFC1918)
            or not 20 <= net.prefixlen <= 30
            or not isinstance(self.interface_index, int)
            or isinstance(self.interface_index, bool)
            or self.interface_index <= 0
            or not self.consent_record_id.strip()
            or self.timeout_seconds != 2.0
            or self.max_results != 8
        ):
            raise ValueError("VIDAA discovery scope outside the reviewed LAN limits")

    @property
    def broadcast(self) -> str:
        return str(ipaddress.IPv4Network(self.cidr).broadcast_address)


def vidaa_approval_material(
    scope: ReviewedVidaaScopeV1, *, goal_id: str, need_id: str
) -> tuple[dict[str, object], dict[str, object]]:
    if not goal_id.strip() or not need_id.strip():
        raise ValueError("VIDAA must bind one existing goal and need")
    return (
        {
            "resource": "vidaa_udp_discovery",
            "protocol": "vidaa_udp",
            "gicc_goal_id": goal_id,
            "gicc_need_id": need_id,
            "address_result_filters": [scope.cidr],
            "all_local_interfaces": True,
            "broadcast_destination": scope.broadcast,
            "interface_index": scope.interface_index,
        },
        {
            "destination_port": _DISCOVERY_PORT,
            "packet_count": 1,
            "timeout_seconds": scope.timeout_seconds,
            "max_results": scope.max_results,
            "device_control": False,
            "pairing": False,
            "login": False,
            "device_probe": False,
        },
    )


def build_vidaa_consent_proposal(
    *, scope: ReviewedVidaaScopeV1, session_id: str, goal_id: str, need_id: str
) -> ActionProposal:
    target, params = vidaa_approval_material(scope, goal_id=goal_id, need_id=need_id)
    return ActionProposal.create(
        session_id=session_id,
        capability="network_discovery",
        operation="discover_vidaa_udp",
        target=target,
        parameters=params,
        material_summary=(
            "Allow ONE VIDAA-specific UDP discovery datagram to directed "
            f"broadcast {scope.broadcast}:{_DISCOVERY_PORT} on LAN {scope.cidr} "
            f"(Windows interface index {scope.interface_index})? Windows routing "
            "may use any connected local interface. Accept replies only from "
            f"{scope.cidr}, wait up to 2 seconds and retain at most 8 "
            "unverified candidates. No host/port scanning, login, pairing, "
            "TV control, or configuration change."
        ),
        attributes=ActionAttributes(external_side_effect=True),
        origin=ActionOrigin.PROACTIVE,
        ttl_seconds=120.0,
    )


def proposal_vidaa_scope(proposal: ActionProposal) -> ReviewedVidaaScopeV1 | None:
    """Reconstruct only a canonical exact operation; deny modified material."""
    if (
        not isinstance(proposal, ActionProposal)
        or not proposal.has_valid_fingerprint()
        or proposal.is_expired()
        or proposal.capability != "network_discovery"
        or proposal.operation != "discover_vidaa_udp"
        or proposal.origin is not ActionOrigin.PROACTIVE
        or not proposal.attributes.external_side_effect
    ):
        return None
    target = proposal.target()
    params = proposal.parameters()
    try:
        ranges = target["address_result_filters"]
        if not isinstance(ranges, list) or len(ranges) != 1:
            return None
        scope = ReviewedVidaaScopeV1(
            cidr=ranges[0],
            interface_index=target["interface_index"],
        )
        canonical_target, canonical_params = vidaa_approval_material(
            scope,
            goal_id=target["gicc_goal_id"],
            need_id=target["gicc_need_id"],
        )
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    if (
        proposal.target_json != canonical_json(canonical_target)
        or proposal.parameters_json != canonical_json(canonical_params)
        or params != canonical_params
    ):
        return None
    return scope


class VidaaAuthorityExecutionGuard:
    """Exactly-once canonical policy, audit and permit check before UDP socket."""

    def __init__(
        self,
        *,
        authority: AuthorityService,
        proposal: ActionProposal,
        context: InteractionContext,
        permit_id: str,
        approval_id: str,
    ) -> None:
        if not isinstance(authority, AuthorityService) or not isinstance(
            context, InteractionContext
        ):
            raise TypeError("VIDAA discovery requires canonical Authority")
        if proposal_vidaa_scope(proposal) is None:
            raise ValueError("VIDAA guard requires exact reviewed proposal")
        if (
            proposal.session_id != context.session_id
            or not str(permit_id).strip()
            or not str(approval_id).strip()
        ):
            raise ValueError("VIDAA permit must bind active owner session")
        self._authority = authority
        self._proposal = proposal
        self._context = context
        self._permit_id = permit_id
        self._approval_id = approval_id
        self._consumed_scope: ReviewedVidaaScopeV1 | None = None

    @property
    def session_id(self) -> str:
        return self._context.session_id

    def binds_information_need(self, *, goal_id: str, need_id: str) -> bool:
        target = self._proposal.target()
        return target.get("gicc_goal_id") == goal_id and target.get("gicc_need_id") == need_id

    def binds_scope(self, scope: ReviewedVidaaScopeV1) -> bool:
        expected = proposal_vidaa_scope(self._proposal)
        return (
            expected is not None
            and scope == ReviewedVidaaScopeV1(
                cidr=expected.cidr,
                interface_index=expected.interface_index,
                consent_record_id=self._approval_id,
            )
        )

    def consumed_for(self, scope: ReviewedVidaaScopeV1) -> bool:
        return scope == self._consumed_scope

    def __call__(self, scope: ReviewedVidaaScopeV1) -> bool:
        if not self.binds_scope(scope):
            return False
        try:
            permit = self._authority.revalidate_and_consume(
                permit_id=self._permit_id,
                proposal=self._proposal,
                context=self._context,
            )
        except Exception:
            return False
        if (
            permit.status is not PermitStatus.CONSUMED
            or permit.approval_id != self._approval_id
        ):
            return False
        self._consumed_scope = scope
        return True


def _label(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")[:40] or "unknown"


@dataclass(frozen=True, slots=True)
class VidaaUdpCandidateV1:
    address: str
    manufacturer: str
    model: str
    observed_at_epoch: int

    @property
    def evidence_ref(self) -> str:
        vendor = _label(self.manufacturer)
        model = _label(self.model)
        digest = canonical_digest(
            {"address": self.address, "manufacturer": vendor,
             "model": model, "time": self.observed_at_epoch}
        )[:24]
        return (
            f"windows_vidaa_udp_unverified:{self.address}:vendor={vendor}:"
            f"model={model}:category=media_player:"
            f"at={self.observed_at_epoch:012d}:{digest}"
        )


def _candidate(packet: bytes, address: object, scope: ReviewedVidaaScopeV1, now: int) -> (
    VidaaUdpCandidateV1 | None
):
    try:
        host = ipaddress.IPv4Address(str(address))
        subnet = ipaddress.IPv4Network(scope.cidr)
        if (
            host not in subnet
            or host in {subnet.network_address, subnet.broadcast_address}
            or len(packet) > 2048
        ):
            return None
        decoded = json.loads(packet)
        if not isinstance(decoded, dict):
            return None
        vendor = decoded.get("manufacturer") or decoded.get("brand") or ""
        model = decoded.get("model") or decoded.get("model_name") or ""
        name = decoded.get("devicename") or decoded.get("name") or decoded.get("device_name") or ""
        if not any(isinstance(value, str) and value.strip() for value in (vendor, model, name)):
            return None
        if not isinstance(vendor, str) or not isinstance(model, str) or not isinstance(name, str):
            return None
        # Name is an unverified research hint, not manufacturer attestation.
        return VidaaUdpCandidateV1(
            address=str(host),
            manufacturer=vendor[:80],
            model=(model or name)[:80],
            observed_at_epoch=now,
        )
    except (UnicodeError, ValueError, TypeError, AttributeError):
        return None


class WindowsVidaaUdpBackend:
    """One directed broadcast after Authority consumes exact owner permit."""

    def __init__(
        self,
        *,
        is_authorized: Callable[[ReviewedVidaaScopeV1], bool] | None = None,
        socket_factory: Callable[..., Any] = socket.socket,
        platform: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        epoch: Callable[[], float] = time.time,
    ) -> None:
        self._authorize = is_authorized
        self._factory = socket_factory
        self._platform = sys.platform if platform is None else platform
        self._clock = clock
        self._epoch = epoch

    def observe(self, scope: ReviewedVidaaScopeV1) -> tuple[VidaaUdpCandidateV1, ...]:
        if not isinstance(scope, ReviewedVidaaScopeV1):
            raise TypeError("VIDAA backend requires reviewed scope")
        if self._platform != "win32" or self._authorize is None:
            return ()
        try:
            if self._authorize(scope) is not True:
                return ()
        except Exception:
            return ()

        result: dict[str, VidaaUdpCandidateV1] = {}
        opened = None
        try:
            opened = self._factory(socket.AF_INET, socket.SOCK_DGRAM)
            opened.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            opened.bind(("", 0))
            opened.sendto(_PACKET, (scope.broadcast, _DISCOVERY_PORT))
            deadline = self._clock() + scope.timeout_seconds
            while len(result) < scope.max_results:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    break
                opened.settimeout(min(remaining, 0.25))
                try:
                    data, sender = opened.recvfrom(2049)
                except (TimeoutError, socket.timeout):
                    continue
                if not isinstance(sender, tuple) or not sender:
                    continue
                candidate = _candidate(data, sender[0], scope, int(self._epoch()))
                if candidate is not None:
                    result[candidate.address] = candidate
        except (OSError, ValueError, AttributeError, TypeError):
            return ()
        finally:
            if opened is not None:
                opened.close()
        return tuple(result[key] for key in sorted(result))
