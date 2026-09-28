"""Phase-9 capability-source contracts and existing-capability adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.capabilities.models import CapabilityCatalog, CapabilityDescriptor
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateV1,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_registry.projection import (
    CapabilityEffectiveSnapshot,
    CapabilityInventoryEntry,
    CapabilityManagementMode,
)
from jarvis.engineering_substrate.canonical import canonical_digest


@dataclass(frozen=True, slots=True)
class AcquisitionContextV1:
    """Ephemeral read-only view of canonical current capability truth."""

    catalog: CapabilityCatalog
    inventory: tuple[CapabilityInventoryEntry, ...]
    effective_snapshot: CapabilityEffectiveSnapshot | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.catalog, CapabilityCatalog):
            raise TypeError("catalog must be CapabilityCatalog")
        if any(
            not isinstance(item, CapabilityInventoryEntry) for item in self.inventory
        ):
            raise TypeError("inventory must contain CapabilityInventoryEntry values")
        if self.effective_snapshot is not None and not isinstance(
            self.effective_snapshot,
            CapabilityEffectiveSnapshot,
        ):
            raise TypeError(
                "effective_snapshot must be CapabilityEffectiveSnapshot or None"
            )
        catalog_keys = tuple(item.key for item in self.catalog.capabilities)
        if len(catalog_keys) != len(set(catalog_keys)):
            raise ValueError("capability catalog keys must be unique")
        inventory_keys = tuple(item.capability_key for item in self.inventory)
        if len(inventory_keys) != len(set(inventory_keys)):
            raise ValueError("capability inventory keys must be unique")
        if set(inventory_keys) != set(catalog_keys):
            raise ValueError(
                "capability inventory must exactly cover the current catalog"
            )

    def descriptor(self, capability_key: str) -> CapabilityDescriptor | None:
        return self.catalog.by_key(str(capability_key).strip())

    def inventory_entry(
        self,
        capability_key: str,
    ) -> CapabilityInventoryEntry | None:
        normalized = str(capability_key).strip()
        return next(
            (item for item in self.inventory if item.capability_key == normalized),
            None,
        )


class CapabilitySourceAdapter(Protocol):
    """Read-only acquisition source; discovery cannot install or enable anything."""

    source_kind: AcquisitionSourceKind

    def discover(
        self,
        goal: OwnerCapabilityGoalV1,
        context: AcquisitionContextV1,
    ) -> tuple[AcquisitionCandidateV1, ...]: ...


class CapabilitySourceRegistry:
    """Release-owned source-adapter inventory with unique source-kind ownership."""

    def __init__(
        self,
        adapters: tuple[CapabilitySourceAdapter, ...] = (),
    ) -> None:
        self._adapters: dict[AcquisitionSourceKind, CapabilitySourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(
        self,
        adapter: CapabilitySourceAdapter,
    ) -> CapabilitySourceAdapter:
        source_kind = getattr(adapter, "source_kind", None)
        discover = getattr(adapter, "discover", None)
        if not isinstance(source_kind, AcquisitionSourceKind) or not callable(discover):
            raise TypeError("source adapter must expose source_kind and discover()")
        if source_kind in self._adapters:
            raise ValueError(
                f"duplicate capability source adapter: {source_kind.value}"
            )
        self._adapters[source_kind] = adapter
        return adapter

    def adapter(
        self,
        source_kind: AcquisitionSourceKind,
    ) -> CapabilitySourceAdapter | None:
        if not isinstance(source_kind, AcquisitionSourceKind):
            raise TypeError("source_kind must be AcquisitionSourceKind")
        return self._adapters.get(source_kind)

    def adapters(self) -> tuple[CapabilitySourceAdapter, ...]:
        return tuple(self._adapters[key] for key in sorted(self._adapters, key=str))


class ExistingCapabilitySourceAdapter:
    """Project canonical runtime/Phase-8 inventory into acquisition candidates."""

    source_kind = AcquisitionSourceKind.EXISTING_CAPABILITY

    @staticmethod
    def _operations(descriptor: CapabilityDescriptor) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(item).strip().casefold()
                    for item in descriptor.operations
                    if str(item).strip()
                }
            )
        )

    @staticmethod
    def _declared_target_hints(
        descriptor: CapabilityDescriptor,
    ) -> tuple[str, ...]:
        raw = descriptor.metadata().get("acquisition_target_hints", ())
        values = (raw,) if isinstance(raw, str) else raw
        if not isinstance(values, (list, tuple)):
            return ()
        return tuple(
            sorted(
                {
                    " ".join(str(item).split()).casefold()
                    for item in values
                    if str(item).strip()
                }
            )
        )

    @classmethod
    def _target_hints_compatible(
        cls,
        goal: OwnerCapabilityGoalV1,
        descriptor: CapabilityDescriptor,
    ) -> bool:
        required = tuple(
            " ".join(str(item).split()).casefold()
            for item in goal.target_hints
            if str(item).strip()
        )
        if not required:
            return True

        declared = cls._declared_target_hints(descriptor)
        if declared:
            return set(required).issubset(set(declared))

        # Legacy/core descriptors predate explicit acquisition target metadata.
        # Preserve reuse only when the owner-interpreted capability identity itself
        # matches the descriptor's declared identity. This keeps a generic
        # "TV control" goal reusable while preventing a target-specific external
        # request from collapsing into an unrelated local operation merely because
        # both happen to expose similarly named verbs such as mute/unmute.
        requested_capability = " ".join(goal.requested_capability.split()).casefold()
        descriptor_identities = {
            " ".join(descriptor.name.split()).casefold(),
            " ".join(descriptor.capability_id.replace(".", " ").split()).casefold(),
        }
        return requested_capability in descriptor_identities

    def discover(
        self,
        goal: OwnerCapabilityGoalV1,
        context: AcquisitionContextV1,
    ) -> tuple[AcquisitionCandidateV1, ...]:
        if not isinstance(goal, OwnerCapabilityGoalV1):
            raise TypeError("goal must be OwnerCapabilityGoalV1")
        if not isinstance(context, AcquisitionContextV1):
            raise TypeError("context must be AcquisitionContextV1")

        required = set(goal.required_operations)
        candidates: list[AcquisitionCandidateV1] = []
        for descriptor in sorted(
            context.catalog.capabilities,
            key=lambda item: item.key,
        ):
            operations = self._operations(descriptor)
            if not required.issubset(operations):
                continue
            if not self._target_hints_compatible(goal, descriptor):
                continue
            inventory = context.inventory_entry(descriptor.key)
            if inventory is None:  # pragma: no cover - context validation owns this
                continue

            if inventory.management_mode is CapabilityManagementMode.CORE_PINNED:
                descriptor_digest = canonical_digest(descriptor)
                candidates.append(
                    AcquisitionCandidateV1.create(
                        source_kind=self.source_kind,
                        source_identity=descriptor.key,
                        source_digest=descriptor_digest,
                        trust_class=AcquisitionTrustClass.ACCEPTED_RELEASE,
                        supported_operations=operations,
                        strategy=AcquisitionStrategy.REUSE,
                        evidence_refs=(
                            f"capability-catalog:{descriptor.key}",
                            f"descriptor-sha256:{descriptor_digest}",
                        ),
                        verification_requirements=(
                            "existing-capability-runtime-readiness",
                        ),
                        reason_codes=("existing_core_pinned",),
                    )
                )
                continue

            snapshot = context.effective_snapshot
            state = None if snapshot is None else snapshot.state_for_key(descriptor.key)
            if (
                state is None
                or state.selected_package_id is None
                or state.selected_package_version is None
                or state.selected_package_digest is None
            ):
                continue
            candidates.append(
                AcquisitionCandidateV1.create(
                    source_kind=self.source_kind,
                    source_identity=descriptor.key,
                    source_version=state.selected_package_version,
                    source_digest=state.selected_package_digest,
                    trust_class=AcquisitionTrustClass.ACCEPTED_RELEASE,
                    supported_operations=operations,
                    strategy=AcquisitionStrategy.REUSE,
                    evidence_refs=(
                        f"phase8-snapshot-sha256:{snapshot.digest}",
                        f"package-sha256:{state.selected_package_digest}",
                    ),
                    verification_requirements=(
                        "phase8-package-lifecycle-compatibility",
                    ),
                    reason_codes=(
                        "existing_package_managed",
                        *state.reason_codes,
                    ),
                )
            )

        return tuple(candidates)
