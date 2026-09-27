"""Authority-bound Phase-8 capability lifecycle mutation service."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.authority.types import RiskClass
from jarvis.capability_registry.authority import (
    CapabilityLifecycleAction,
    CapabilityLifecycleAuthorityBridge,
    CapabilityLifecycleAuthoritySource,
    CapabilityLifecycleProposalBinding,
)
from jarvis.capability_registry.compatibility import (
    CapabilityCompatibilityReportV1,
    CompatibilityReason,
    CompatibilityVerdict,
)
from jarvis.capability_registry.contracts import StrictSemVer
from jarvis.capability_registry.models import (
    AdmittedCapabilityPackage,
    CapabilityLifecycleEventKind,
    CapabilityRegistryState,
    DesiredActivationState,
    PackageDisposition,
)
from jarvis.capability_registry.projection import (
    CapabilityEffectiveSnapshot,
    package_component_id,
)
from jarvis.capability_registry.reconciliation import (
    CapabilityLifecycleReconciler,
    ReconciliationTrigger,
)
from jarvis.capability_registry.store import (
    CapabilityRegistrySelectionError,
    CapabilityRegistryStore,
    StaleRegistryGenerationError,
    UnknownCapabilityPackageError,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.manifest import RegisteredCapabilityManifest
from jarvis.self_model.health import HealthState

_SAFETY_QUARANTINE_REASONS = frozenset(
    {
        CompatibilityReason.DESCRIPTOR_DIGEST_MISMATCH.value,
        CompatibilityReason.MANIFEST_DIGEST_MISMATCH.value,
        CompatibilityReason.MANIFEST_CAPABILITY_MISMATCH.value,
        CompatibilityReason.MANIFEST_VERSION_MISMATCH.value,
        CompatibilityReason.ARTIFACT_INTEGRITY_FAILED.value,
        CompatibilityReason.ARTIFACT_SIZE_MISMATCH.value,
        CompatibilityReason.ARTIFACT_PROVENANCE_MISSING.value,
    }
)


class CapabilityLifecycleMutationError(RuntimeError):
    pass


class CapabilityLifecyclePreconditionError(CapabilityLifecycleMutationError):
    pass


class CapabilityLifecycleReconciliationError(CapabilityLifecycleMutationError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityLifecycleMutationResult:
    action: CapabilityLifecycleAction
    previous_state: CapabilityRegistryState
    current_state: CapabilityRegistryState
    compatibility: CapabilityCompatibilityReportV1 | None
    snapshot: CapabilityEffectiveSnapshot
    changed: bool


class CapabilityLifecycleService:
    """Transition-fenced lifecycle mutations over durable registry truth."""

    def __init__(
        self,
        *,
        store: CapabilityRegistryStore,
        reconciler: CapabilityLifecycleReconciler,
        authority: CapabilityLifecycleAuthorityBridge,
    ) -> None:
        if reconciler.store is not store:
            raise ValueError(
                "lifecycle service and reconciler must share registry store"
            )
        self.store = store
        self.reconciler = reconciler
        self.authority = authority
        self.evaluator = reconciler.evaluator
        self.projection = reconciler.projection

    def _current(
        self,
        capability_id: str,
        *,
        expected_generation: int,
    ) -> CapabilityRegistryState:
        current = self.store.require_registry(capability_id)
        if current.generation != expected_generation:
            raise StaleRegistryGenerationError(
                "lifecycle request expected stale registry generation"
            )
        return current

    def _package(
        self,
        capability_id: str,
        package_id: str,
        package_version: str,
    ) -> tuple[
        AdmittedCapabilityPackage,
        CapabilityCompatibilityReportV1,
        RegisteredCapabilityManifest,
    ]:
        package = self.store.get_package(package_id, package_version)
        if package is None:
            raise UnknownCapabilityPackageError("capability package is not admitted")
        if package.package.capability_id != str(capability_id).strip().casefold():
            raise CapabilityRegistrySelectionError(
                "capability package belongs to another capability"
            )
        registered = self.evaluator.manifest_registry.require(
            package.package.manifest_id,
            package.package.manifest_version,
        )
        report = self.evaluator.evaluate(package)
        return package, report, registered

    @staticmethod
    def _require_ready(
        package: AdmittedCapabilityPackage,
        report: CapabilityCompatibilityReportV1,
    ) -> None:
        if package.disposition is not PackageDisposition.AVAILABLE:
            raise CapabilityLifecyclePreconditionError(
                "target capability package is not AVAILABLE"
            )
        if report.verdict is not CompatibilityVerdict.READY:
            reasons = ",".join(report.reason_codes)
            raise CapabilityLifecyclePreconditionError(
                f"target capability package is not READY: {reasons}"
            )

    def _require_healthy(
        self,
        *,
        capability_id: str,
        package: AdmittedCapabilityPackage,
        registered: RegisteredCapabilityManifest,
    ) -> None:
        provider = self.evaluator.provider_registry.get(
            package.package.capability_id,
            registered.manifest.executor_id,
            registered.manifest.adapter_id,
        )
        if provider is None:
            raise CapabilityLifecyclePreconditionError(
                "trusted provider is unavailable for target package"
            )
        snapshot = self.reconciler.health_bridge.observe(
            package_component_id(capability_id),
            provider=provider,
            required_probe_ids=registered.manifest.health_probe_ids,
        )
        if snapshot.state is not HealthState.HEALTHY:
            raise CapabilityLifecyclePreconditionError(
                f"target capability health is not acceptable: {snapshot.state.value}"
            )

    @staticmethod
    def _synthetic_compatibility_digest(
        state: CapabilityRegistryState,
    ) -> str:
        return canonical_digest(
            {
                "capability_id": state.capability_id,
                "generation": state.generation,
                "selected_package_id": state.selected_package_id,
                "selected_package_version": state.selected_package_version,
                "selected_package_digest": state.selected_package_digest,
                "reason": "no_selected_package",
            }
        )

    def _binding(
        self,
        *,
        action: CapabilityLifecycleAction,
        state: CapabilityRegistryState,
        package: AdmittedCapabilityPackage | None,
        report: CapabilityCompatibilityReportV1 | None,
        registered: RegisteredCapabilityManifest | None,
        source: CapabilityLifecycleAuthoritySource,
    ) -> CapabilityLifecycleProposalBinding:
        if registered is None:
            risk_floor = RiskClass.PERSISTENT_OR_EXTERNAL
            authority_attributes: tuple[str, ...] = ()
        else:
            risk_floor = registered.authority_risk_floor
            authority_attributes = registered.manifest.authority_attributes
        return CapabilityLifecycleProposalBinding(
            action=action,
            capability_id=state.capability_id,
            expected_generation=state.generation,
            package_id=None if package is None else package.package.package_id,
            package_version=(
                None if package is None else package.package.package_version
            ),
            package_digest=None if package is None else package.package_digest,
            compatibility_digest=(
                self._synthetic_compatibility_digest(state)
                if report is None
                else report.digest
            ),
            manifest_risk_floor=risk_floor,
            manifest_authority_attributes=authority_attributes,
            source=source,
        )

    def _reconcile_after_fence(
        self,
        *,
        expected_state: CapabilityRegistryState,
        action: CapabilityLifecycleAction,
        require_effective: bool | None,
    ) -> CapabilityEffectiveSnapshot:
        try:
            snapshot = self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
        except Exception as exc:
            raise CapabilityLifecycleReconciliationError(
                "durable lifecycle mutation committed but reconciliation failed"
            ) from exc
        state = snapshot.state(expected_state.capability_id)
        if (
            state is None
            or state.registry_generation != expected_state.generation
            or state.applied_generation != expected_state.generation
        ):
            self.projection.fail_closed("lifecycle_generation_mismatch")
            raise CapabilityLifecycleReconciliationError(
                "reconciled lifecycle generation does not match durable registry"
            )
        if (
            require_effective is not None
            and state.effective_enabled is not require_effective
        ):
            self.projection.fail_closed("lifecycle_effective_state_mismatch")
            raise CapabilityLifecycleReconciliationError(
                f"{action.value} did not produce the required effective routing state"
            )
        return snapshot

    def _restore_after_failed_transition(self) -> None:
        try:
            self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
        except Exception:
            self.projection.fail_closed("lifecycle_restore_failed")

    def select_version(
        self,
        capability_id: str,
        *,
        package_id: str,
        package_version: str,
        expected_generation: int,
        authority_session_id: str,
        source: CapabilityLifecycleAuthoritySource,
    ) -> CapabilityLifecycleMutationResult:
        current = self._current(
            capability_id,
            expected_generation=expected_generation,
        )
        package, report, registered = self._package(
            capability_id,
            package_id,
            package_version,
        )
        self._require_ready(package, report)
        if current.desired_state is DesiredActivationState.ENABLED:
            self._require_healthy(
                capability_id=current.capability_id,
                package=package,
                registered=registered,
            )
        if (
            current.selected_package_id == package.package.package_id
            and current.selected_package_version == package.package.package_version
            and current.selected_package_digest == package.package_digest
        ):
            snapshot = self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
            return CapabilityLifecycleMutationResult(
                action=CapabilityLifecycleAction.SELECT_VERSION,
                previous_state=current,
                current_state=current,
                compatibility=report,
                snapshot=snapshot,
                changed=False,
            )

        binding = self._binding(
            action=CapabilityLifecycleAction.SELECT_VERSION,
            state=current,
            package=package,
            report=report,
            registered=registered,
            source=source,
        )
        committed: CapabilityRegistryState | None = None
        try:
            with self.projection.transition_fence.hold(current.capability_id):
                authorized = self.authority.authorize(
                    binding,
                    authority_session_id=authority_session_id,
                )
                self.authority.consume(authorized)
                committed = self.store.transition_registry(
                    current.capability_id,
                    expected_generation=current.generation,
                    desired_state=current.desired_state,
                    selected_package_id=package.package.package_id,
                    selected_package_version=package.package.package_version,
                    event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
                    reason_code="version_selected",
                    authority_ref=authorized.authority_ref,
                    evidence_ref=report.digest,
                )
                self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
        except Exception:
            if committed is None:
                self._restore_after_failed_transition()
            raise

        snapshot = self._reconcile_after_fence(
            expected_state=committed,
            action=CapabilityLifecycleAction.SELECT_VERSION,
            require_effective=(
                True
                if committed.desired_state is DesiredActivationState.ENABLED
                else False
            ),
        )
        return CapabilityLifecycleMutationResult(
            action=CapabilityLifecycleAction.SELECT_VERSION,
            previous_state=current,
            current_state=committed,
            compatibility=report,
            snapshot=snapshot,
            changed=True,
        )

    def enable(
        self,
        capability_id: str,
        *,
        expected_generation: int,
        authority_session_id: str,
        source: CapabilityLifecycleAuthoritySource,
    ) -> CapabilityLifecycleMutationResult:
        current = self._current(
            capability_id,
            expected_generation=expected_generation,
        )
        if not current.has_selection:
            raise CapabilityLifecyclePreconditionError(
                "enable requires an already selected package version"
            )
        package, report, registered = self._package(
            current.capability_id,
            current.selected_package_id or "",
            current.selected_package_version or "",
        )
        self._require_ready(package, report)
        self._require_healthy(
            capability_id=current.capability_id,
            package=package,
            registered=registered,
        )
        if current.desired_state is DesiredActivationState.ENABLED:
            snapshot = self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
            state = snapshot.state(current.capability_id)
            if state is None or not state.effective_enabled:
                raise CapabilityLifecyclePreconditionError(
                    "enabled durable intent is not currently effective"
                )
            return CapabilityLifecycleMutationResult(
                action=CapabilityLifecycleAction.ENABLE,
                previous_state=current,
                current_state=current,
                compatibility=report,
                snapshot=snapshot,
                changed=False,
            )

        binding = self._binding(
            action=CapabilityLifecycleAction.ENABLE,
            state=current,
            package=package,
            report=report,
            registered=registered,
            source=source,
        )
        committed: CapabilityRegistryState | None = None
        try:
            with self.projection.transition_fence.hold(current.capability_id):
                authorized = self.authority.authorize(
                    binding,
                    authority_session_id=authority_session_id,
                )
                self.authority.consume(authorized)
                committed = self.store.transition_registry(
                    current.capability_id,
                    expected_generation=current.generation,
                    desired_state=DesiredActivationState.ENABLED,
                    selected_package_id=package.package.package_id,
                    selected_package_version=package.package.package_version,
                    event_kind=CapabilityLifecycleEventKind.DESIRED_STATE_CHANGED,
                    reason_code="capability_enabled",
                    authority_ref=authorized.authority_ref,
                    evidence_ref=report.digest,
                )
                self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
        except Exception:
            if committed is None:
                self._restore_after_failed_transition()
            raise

        snapshot = self._reconcile_after_fence(
            expected_state=committed,
            action=CapabilityLifecycleAction.ENABLE,
            require_effective=True,
        )
        return CapabilityLifecycleMutationResult(
            action=CapabilityLifecycleAction.ENABLE,
            previous_state=current,
            current_state=committed,
            compatibility=report,
            snapshot=snapshot,
            changed=True,
        )

    def disable(
        self,
        capability_id: str,
        *,
        expected_generation: int,
        authority_session_id: str,
        source: CapabilityLifecycleAuthoritySource,
    ) -> CapabilityLifecycleMutationResult:
        current = self._current(
            capability_id,
            expected_generation=expected_generation,
        )
        package = None
        report = None
        registered = None
        if current.has_selection:
            package, report, registered = self._package(
                current.capability_id,
                current.selected_package_id or "",
                current.selected_package_version or "",
            )
        if current.desired_state is DesiredActivationState.DISABLED:
            snapshot = self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
            return CapabilityLifecycleMutationResult(
                action=CapabilityLifecycleAction.DISABLE,
                previous_state=current,
                current_state=current,
                compatibility=report,
                snapshot=snapshot,
                changed=False,
            )

        binding = self._binding(
            action=CapabilityLifecycleAction.DISABLE,
            state=current,
            package=package,
            report=report,
            registered=registered,
            source=source,
        )
        committed: CapabilityRegistryState | None = None
        try:
            with self.projection.transition_fence.hold(current.capability_id):
                authorized = self.authority.authorize(
                    binding,
                    authority_session_id=authority_session_id,
                )
                self.authority.consume(authorized)
                committed = self.store.transition_registry(
                    current.capability_id,
                    expected_generation=current.generation,
                    desired_state=DesiredActivationState.DISABLED,
                    selected_package_id=current.selected_package_id,
                    selected_package_version=current.selected_package_version,
                    event_kind=CapabilityLifecycleEventKind.DESIRED_STATE_CHANGED,
                    reason_code="capability_disabled",
                    authority_ref=authorized.authority_ref,
                    evidence_ref=(
                        binding.compatibility_digest
                        if report is None
                        else report.digest
                    ),
                )
                self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
        except Exception:
            if committed is None:
                self._restore_after_failed_transition()
            raise

        snapshot = self._reconcile_after_fence(
            expected_state=committed,
            action=CapabilityLifecycleAction.DISABLE,
            require_effective=False,
        )
        return CapabilityLifecycleMutationResult(
            action=CapabilityLifecycleAction.DISABLE,
            previous_state=current,
            current_state=committed,
            compatibility=report,
            snapshot=snapshot,
            changed=True,
        )

    def rollback_version(
        self,
        capability_id: str,
        *,
        package_version: str,
        expected_generation: int,
        authority_session_id: str,
        source: CapabilityLifecycleAuthoritySource,
    ) -> CapabilityLifecycleMutationResult:
        current = self._current(
            capability_id,
            expected_generation=expected_generation,
        )
        if not current.has_selection:
            raise CapabilityLifecyclePreconditionError(
                "rollback requires a selected package version"
            )
        current_semver = StrictSemVer.parse(current.selected_package_version or "")
        target_semver = StrictSemVer.parse(package_version)
        if target_semver.compare_precedence(current_semver) >= 0:
            raise CapabilityLifecyclePreconditionError(
                "rollback target must have lower SemVer precedence"
            )
        package_id = current.selected_package_id or ""
        package, report, registered = self._package(
            current.capability_id,
            package_id,
            package_version,
        )
        self._require_ready(package, report)
        if current.desired_state is DesiredActivationState.ENABLED:
            self._require_healthy(
                capability_id=current.capability_id,
                package=package,
                registered=registered,
            )

        binding = self._binding(
            action=CapabilityLifecycleAction.ROLLBACK_VERSION,
            state=current,
            package=package,
            report=report,
            registered=registered,
            source=source,
        )
        committed: CapabilityRegistryState | None = None
        try:
            with self.projection.transition_fence.hold(current.capability_id):
                authorized = self.authority.authorize(
                    binding,
                    authority_session_id=authority_session_id,
                )
                self.authority.consume(authorized)
                committed = self.store.transition_registry(
                    current.capability_id,
                    expected_generation=current.generation,
                    desired_state=current.desired_state,
                    selected_package_id=package.package.package_id,
                    selected_package_version=package.package.package_version,
                    event_kind=CapabilityLifecycleEventKind.VERSION_SELECTED,
                    reason_code="version_rollback",
                    authority_ref=authorized.authority_ref,
                    evidence_ref=report.digest,
                )
                self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
        except Exception:
            if committed is None:
                self._restore_after_failed_transition()
            raise

        snapshot = self._reconcile_after_fence(
            expected_state=committed,
            action=CapabilityLifecycleAction.ROLLBACK_VERSION,
            require_effective=(
                True
                if committed.desired_state is DesiredActivationState.ENABLED
                else False
            ),
        )
        return CapabilityLifecycleMutationResult(
            action=CapabilityLifecycleAction.ROLLBACK_VERSION,
            previous_state=current,
            current_state=committed,
            compatibility=report,
            snapshot=snapshot,
            changed=True,
        )

    def retire_package(
        self,
        capability_id: str,
        *,
        package_id: str,
        package_version: str,
        expected_generation: int,
        authority_session_id: str,
        source: CapabilityLifecycleAuthoritySource,
    ) -> CapabilityLifecycleMutationResult:
        current = self._current(
            capability_id,
            expected_generation=expected_generation,
        )
        package, report, registered = self._package(
            current.capability_id,
            package_id,
            package_version,
        )
        if package.disposition is PackageDisposition.QUARANTINED:
            raise CapabilityLifecyclePreconditionError(
                "quarantined package cannot be retired"
            )
        if package.disposition is PackageDisposition.RETIRED:
            snapshot = self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
            return CapabilityLifecycleMutationResult(
                action=CapabilityLifecycleAction.RETIRE_PACKAGE,
                previous_state=current,
                current_state=current,
                compatibility=report,
                snapshot=snapshot,
                changed=False,
            )
        binding = self._binding(
            action=CapabilityLifecycleAction.RETIRE_PACKAGE,
            state=current,
            package=package,
            report=report,
            registered=registered,
            source=source,
        )
        try:
            with self.projection.transition_fence.hold(current.capability_id):
                authorized = self.authority.authorize(
                    binding,
                    authority_session_id=authority_session_id,
                )
                self.authority.consume(authorized)
                self.store.set_package_disposition(
                    package.package.package_id,
                    package.package.package_version,
                    disposition=PackageDisposition.RETIRED,
                    reason_code="package_retired",
                    expected_generation=current.generation,
                    authority_ref=authorized.authority_ref,
                    evidence_ref=report.digest,
                )
                self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
        except Exception:
            self._restore_after_failed_transition()
            raise

        durable = self.store.require_registry(current.capability_id)
        require_effective = (
            False
            if (
                durable.selected_package_id == package.package.package_id
                and durable.selected_package_version == package.package.package_version
            )
            else None
        )
        snapshot = self._reconcile_after_fence(
            expected_state=durable,
            action=CapabilityLifecycleAction.RETIRE_PACKAGE,
            require_effective=require_effective,
        )
        return CapabilityLifecycleMutationResult(
            action=CapabilityLifecycleAction.RETIRE_PACKAGE,
            previous_state=current,
            current_state=durable,
            compatibility=report,
            snapshot=snapshot,
            changed=True,
        )

    def quarantine_package_if_unsafe(
        self,
        capability_id: str,
        *,
        package_id: str,
        package_version: str,
    ) -> CapabilityLifecycleMutationResult:
        current = self.store.require_registry(capability_id)
        package, report, _ = self._package(
            current.capability_id,
            package_id,
            package_version,
        )
        reasons = set(report.reason_codes).intersection(_SAFETY_QUARANTINE_REASONS)
        if not reasons:
            raise CapabilityLifecyclePreconditionError(
                "automatic quarantine requires deterministic integrity/security evidence"
            )
        if package.disposition is PackageDisposition.QUARANTINED:
            snapshot = self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
            return CapabilityLifecycleMutationResult(
                action=CapabilityLifecycleAction.QUARANTINE_PACKAGE,
                previous_state=current,
                current_state=current,
                compatibility=report,
                snapshot=snapshot,
                changed=False,
            )

        try:
            with self.projection.transition_fence.hold(current.capability_id):
                self.store.set_package_disposition(
                    package.package.package_id,
                    package.package.package_version,
                    disposition=PackageDisposition.QUARANTINED,
                    reason_code="automatic_safety_quarantine",
                    evidence_ref=report.digest,
                )
                self.reconciler.reconcile(ReconciliationTrigger.LIFECYCLE)
        except Exception:
            self._restore_after_failed_transition()
            raise

        durable = self.store.require_registry(current.capability_id)
        require_effective = (
            False
            if (
                durable.selected_package_id == package.package.package_id
                and durable.selected_package_version == package.package.package_version
            )
            else None
        )
        snapshot = self._reconcile_after_fence(
            expected_state=durable,
            action=CapabilityLifecycleAction.QUARANTINE_PACKAGE,
            require_effective=require_effective,
        )
        return CapabilityLifecycleMutationResult(
            action=CapabilityLifecycleAction.QUARANTINE_PACKAGE,
            previous_state=current,
            current_state=durable,
            compatibility=report,
            snapshot=snapshot,
            changed=True,
        )
