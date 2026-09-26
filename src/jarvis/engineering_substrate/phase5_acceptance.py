"""Consolidated owner-machine acceptance for Phase 5.

This harness performs only bounded acceptance work. It does not grant Authority,
approve an EngineeringChange, promote code, deploy code, or weaken any policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import (
    CapabilityManifest,
    DependencyEcosystem,
    DependencyRequirement,
)
from jarvis.engineering_substrate.dependency import (
    UV_WINDOWS_X64_0_12_19,
    DependencyBroker,
    OfflineCandidateVerifier,
    OfflineVerificationBundleBuilder,
    PythonResolutionEnvironment,
    UvAdapter,
    UvBinaryRegistration,
    default_dependency_source_registry,
)
from jarvis.engineering_substrate.discovery_acceptance import (
    run_acceptance as run_discovery_acceptance,
)
from jarvis.engineering_substrate.manifest import (
    CapabilityManifestRegistry,
    DependencyResolutionRegistration,
    DigestRegistration,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.engineering_substrate.provenance import ProvenanceService
from jarvis.engineering_substrate.sandbox import default_sandbox_registry
from jarvis.engineering_substrate.secrets.acceptance import (
    run_acceptance as run_secret_acceptance,
)
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


class Phase5AcceptanceError(RuntimeError):
    """The integrated Phase-5 acceptance could not prove an invariant."""


@dataclass(frozen=True, slots=True)
class UvReleaseAcceptance:
    adapter: UvAdapter
    release_asset_sha256: str
    executable_sha256: str
    signer_subject: str
    signer_thumbprint: str


def _hash_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _tested_commit(repo: pathlib.Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Phase5AcceptanceError(
            "acceptance could not identify the tested Git revision"
        ) from exc
    commit = completed.stdout.strip().casefold()
    if (
        completed.returncode != 0
        or len(commit) != 40
        or any(char not in "0123456789abcdef" for char in commit)
    ):
        raise Phase5AcceptanceError("acceptance Git revision is not a full commit SHA")
    return commit


def _require_regular_file(path: pathlib.Path, *, field: str) -> pathlib.Path:
    if path.is_symlink() or not path.is_file():
        raise Phase5AcceptanceError(f"{field} must be a regular file")
    return path.resolve()


def _verify_authenticode(executable: pathlib.Path) -> tuple[str, str]:
    script = (
        "$s=Get-AuthenticodeSignature -LiteralPath $env:JARVIS_PHASE5_UV_EXE;"
        "[pscustomobject]@{"
        "Status=[string]$s.Status;"
        "Subject=[string]$s.SignerCertificate.Subject;"
        "Thumbprint=[string]$s.SignerCertificate.Thumbprint"
        "}|ConvertTo-Json -Compress"
    )
    child_environment = dict(os.environ)
    child_environment["JARVIS_PHASE5_UV_EXE"] = str(executable)
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            shell=False,
            env=child_environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Phase5AcceptanceError(
            "uv Authenticode verification could not run"
        ) from exc
    if completed.returncode != 0:
        raise Phase5AcceptanceError("uv Authenticode verification failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise Phase5AcceptanceError(
            "uv Authenticode verification returned invalid evidence"
        ) from exc
    if not isinstance(payload, dict) or payload.get("Status") != "Valid":
        raise Phase5AcceptanceError("uv Authenticode signature is not valid")
    subject = str(payload.get("Subject") or "").strip()
    thumbprint = str(payload.get("Thumbprint") or "").strip().casefold()
    if not subject or not thumbprint:
        raise Phase5AcceptanceError("uv Authenticode signer identity is unavailable")
    return subject, thumbprint


def _validate_uv_release_asset(
    asset_path: pathlib.Path,
    executable_path: pathlib.Path,
) -> UvReleaseAcceptance:
    policy = UV_WINDOWS_X64_0_12_19
    asset = _require_regular_file(asset_path, field="uv release asset")
    executable = _require_regular_file(executable_path, field="uv executable")
    if asset.name != policy.release_asset_name:
        raise Phase5AcceptanceError("uv release asset file name is not reviewed")
    asset_digest = _hash_file(asset)
    if asset_digest != policy.release_asset_sha256:
        raise Phase5AcceptanceError("uv release asset SHA-256 mismatch")

    executable_digest = _hash_file(executable)
    try:
        with zipfile.ZipFile(asset) as archive:
            members = tuple(
                name
                for name in archive.namelist()
                if pathlib.PurePosixPath(name).name.casefold() == "uv.exe"
            )
            if len(members) != 1:
                raise Phase5AcceptanceError(
                    "reviewed uv asset must contain exactly one uv.exe"
                )
            archived_digest = hashlib.sha256(archive.read(members[0])).hexdigest()
    except zipfile.BadZipFile as exc:
        raise Phase5AcceptanceError(
            "reviewed uv release asset is not a valid ZIP"
        ) from exc
    if archived_digest != executable_digest:
        raise Phase5AcceptanceError(
            "uv executable bytes are not from the reviewed release asset"
        )

    signer_subject, signer_thumbprint = _verify_authenticode(executable)
    registration = UvBinaryRegistration(
        executable_path=executable,
        version=policy.version,
        executable_sha256=executable_digest,
        release_commit_sha=policy.release_commit_sha,
        release_asset_sha256=asset_digest,
        release_policy_digest=policy.policy_digest,
    )
    adapter = UvAdapter(
        release_policy=policy,
        binary_registration=registration,
    )
    adapter.verify_trust()
    return UvReleaseAcceptance(
        adapter=adapter,
        release_asset_sha256=asset_digest,
        executable_sha256=executable_digest,
        signer_subject=signer_subject,
        signer_thumbprint=signer_thumbprint,
    )


def _manifest_acceptance(
    *,
    resolution,
    provenance_results,
    sandbox_registry,
):
    resolution_digest = canonical_digest(resolution)
    provenance_registrations = tuple(
        DigestRegistration(
            reference_id=result.provenance.provenance_id,
            digest=canonical_digest(result.provenance),
        )
        for result in provenance_results
    )
    provenance_ids = tuple(
        registration.reference_id for registration in provenance_registrations
    )
    provenance_digests = tuple(
        registration.digest for registration in provenance_registrations
    )
    sandbox = sandbox_registry.require("dependency.verify.v1", 1)
    sandbox_digest = canonical_digest(sandbox.profile)
    references = ManifestReferenceCatalog(
        dependency_resolutions=(
            DependencyResolutionRegistration(
                resolution_id=resolution.resolution_id,
                digest=resolution_digest,
                provenance_ids=provenance_ids,
            ),
        ),
        provenance=provenance_registrations,
        sandbox_profiles=(
            DigestRegistration(
                reference_id="dependency.verify.v1",
                digest=sandbox_digest,
            ),
        ),
        verification_contract_ids=("phase5.offline-candidate.v1",),
        disable_rollback_contract_ids=("phase5.acceptance-disable.v1",),
    )
    registry = CapabilityManifestRegistry(
        executors=(
            TrustedExecutorRegistration(
                executor_id="phase5.acceptance.executor",
                adapter_ids=("phase5.acceptance.adapter",),
                operations=("verify",),
                authority_attribute_floor=(),
                allowed_secret_scopes=("repository.read",),
                sandbox_profile_ids=("dependency.verify.v1",),
            ),
        ),
        adapters=(
            TrustedAdapterRegistration(
                adapter_id="phase5.acceptance.adapter",
                operations=("verify",),
            ),
        ),
        references=references,
    )
    manifest = CapabilityManifest(
        manifest_id="phase5.acceptance.manifest",
        manifest_version=1,
        capability_id="phase5.acceptance.capability",
        capability_version="1.0.0",
        purpose="Harmless Phase-5 owner acceptance capability",
        adapter_id="phase5.acceptance.adapter",
        executor_id="phase5.acceptance.executor",
        operations=("verify",),
        dependency_resolution_ids=(resolution.resolution_id,),
        secret_scope_requirements=("repository.read",),
        authority_attributes=(),
        sandbox_profile_ids=("dependency.verify.v1",),
        discovery_scope_ids=(),
        platform_constraints=(),
        resource_requirements=(),
        health_probe_ids=(),
        verification_contract_ids=("phase5.offline-candidate.v1",),
        hardware_acceptance_contract_ids=(),
        provenance_ids=provenance_ids,
        disable_rollback_contract_id="phase5.acceptance-disable.v1",
        dependency_resolution_digests=(resolution_digest,),
        sandbox_profile_digests=(sandbox_digest,),
        discovery_scope_digests=(),
        provenance_digests=provenance_digests,
    )
    registered = registry.register(manifest)
    if registered.manifest_digest != canonical_digest(manifest):
        raise Phase5AcceptanceError("manifest digest changed during registration")
    return registered


def _restart_lineage_acceptance(root: pathlib.Path) -> dict[str, object]:
    store_path = root / "restart-work.sqlite3"
    first = SQLiteWorkStore(store_path)
    item = WorkItem(
        request="Phase-5 restart lineage acceptance",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="phase5-owner-acceptance",
        source_turn_id="restart-boundary",
    )
    first.create(item)
    waiting = item.transition(
        WorkState.WAITING_RESOURCE,
        status_detail="phase5 acceptance resource wait",
    )
    first.save(waiting, expected_version=item.version)

    restarted = SQLiteWorkStore(store_path)
    recovered = restarted.require(item.work_id)
    if recovered.work_id != item.work_id:
        raise Phase5AcceptanceError("restart changed WorkItem identity")
    if recovered.state is not WorkState.WAITING_RESOURCE:
        raise Phase5AcceptanceError("restart changed WorkItem waiting state")
    if recovered.version != waiting.version:
        raise Phase5AcceptanceError("restart changed WorkItem lineage version")
    return {
        "work_id": recovered.work_id,
        "state": recovered.state.value,
        "version": recovered.version,
        "lineage_digest": canonical_digest(
            {
                "work_id": recovered.work_id,
                "state": recovered.state.value,
                "version": recovered.version,
                "source_session_id": recovered.source_session_id,
                "source_turn_id": recovered.source_turn_id,
            }
        ),
    }


def run_acceptance(
    *,
    repo_root: pathlib.Path,
    uv_release_asset: pathlib.Path,
    uv_executable: pathlib.Path,
) -> dict[str, object]:
    if sys.platform != "win32":
        raise Phase5AcceptanceError("Phase-5 owner acceptance requires Windows")
    repo = pathlib.Path(repo_root)
    if repo.is_symlink() or not repo.is_dir():
        raise Phase5AcceptanceError("acceptance repo_root must be a regular directory")
    repo = repo.resolve()
    tested_commit = _tested_commit(repo)

    uv_trust = _validate_uv_release_asset(uv_release_asset, uv_executable)
    uv = uv_trust.adapter

    with tempfile.TemporaryDirectory(prefix="jarvis-phase5-acceptance-") as temp:
        root = pathlib.Path(temp)
        workspace = root / "dependency-workspace"
        staging = root / "staging"
        bundle_root = root / "offline-bundle"
        candidate = root / "candidate"
        workspace.mkdir()
        staging.mkdir()

        artifact_store = ArtifactStore(root / "artifacts")
        broker = DependencyBroker(
            source_registry=default_dependency_source_registry(),
            uv_adapter=uv,
            artifact_store=artifact_store,
            protected_main_root=repo,
        )
        requirement = DependencyRequirement(
            requirement_id="phase5-acceptance-tomli-w",
            ecosystem=DependencyEcosystem.PYTHON,
            package_name="tomli-w",
            version_constraint="==1.2.0",
            purpose="Harmless Phase-5 owner acceptance dependency",
            registered_source_ids=("pypi.public.v1",),
            platform_constraints=(
                "python==3.11",
                "x86_64-pc-windows-msvc",
            ),
            change_id="phase5-owner-acceptance",
            work_id="phase5-owner-acceptance",
        )
        resolved = broker.resolve_python(
            requirement,
            workspace=workspace,
            environment=PythonResolutionEnvironment(
                python_version="3.11",
                python_platform="x86_64-pc-windows-msvc",
            ),
        )
        parsed = broker.inspect_lock(resolved)
        if not parsed.wheels:
            raise Phase5AcceptanceError(
                "resolved dependency produced no wheel evidence"
            )
        artifacts = broker.acquire_locked_wheels(
            resolved,
            staging_dir=staging,
        )
        if not artifacts:
            raise Phase5AcceptanceError("no locked wheels were admitted")

        provenance = ProvenanceService(artifact_store=artifact_store)
        provenance_results = tuple(
            provenance.verify_pypi_artifact(
                artifact,
                resolution=resolved.resolution,
                provenance_id=f"phase5-acceptance:{artifact.sha256[:16]}",
            )
            for artifact in artifacts
        )
        if any(
            result.provenance.verification_status.value != "verified"
            for result in provenance_results
        ):
            raise Phase5AcceptanceError("dependency provenance was not verified")

        sandbox_registry = default_sandbox_registry(
            protected_main_root=repo,
        )
        bundle = OfflineVerificationBundleBuilder(artifact_store).build(
            resolved,
            artifacts,
            output_root=bundle_root,
        )
        offline = OfflineCandidateVerifier(
            sandbox_registry=sandbox_registry,
        ).verify(
            bundle,
            candidate_dir=candidate,
            worktree=repo,
        )
        if offline.canonical_lock_digest != resolved.resolution.lock_digest:
            raise Phase5AcceptanceError("offline verification changed canonical lock")

        registered_manifest = _manifest_acceptance(
            resolution=resolved.resolution,
            provenance_results=provenance_results,
            sandbox_registry=sandbox_registry,
        )
        secret = run_secret_acceptance()
        if secret.status != "PASS":
            raise Phase5AcceptanceError("disposable secret acceptance did not pass")
        discovery = run_discovery_acceptance()
        if discovery.get("status") != "PASS":
            raise Phase5AcceptanceError("bounded discovery acceptance did not pass")
        if discovery.get("execution_enabled_count") != 0:
            raise Phase5AcceptanceError(
                "discovery acceptance unexpectedly enabled execution"
            )
        restart = _restart_lineage_acceptance(root)

        evidence = {
            "status": "PASS",
            "tested_commit": tested_commit,
            "recorded_at": datetime.now(UTC).isoformat(),
            "uv": {
                "version": uv.release_policy.version,
                "release_asset_sha256": uv_trust.release_asset_sha256,
                "executable_sha256": uv_trust.executable_sha256,
                "policy_digest": uv.release_policy.policy_digest,
                "signature_kind": uv.release_policy.platform_signature_kind,
                "signer_subject": uv_trust.signer_subject,
                "signer_thumbprint": uv_trust.signer_thumbprint,
            },
            "dependency": {
                "package": "tomli-w==1.2.0",
                "resolution_id": resolved.resolution.resolution_id,
                "resolution_digest": canonical_digest(resolved.resolution),
                "lock_digest": resolved.resolution.lock_digest,
                "artifact_digests": sorted(artifact.sha256 for artifact in artifacts),
            },
            "provenance": [
                {
                    "provenance_id": result.provenance.provenance_id,
                    "attestation_status": result.provenance.attestation_status.value,
                    "verification_status": result.provenance.verification_status.value,
                    "provenance_digest": canonical_digest(result.provenance),
                }
                for result in provenance_results
            ],
            "offline_candidate": {
                "profile_id": offline.profile_id,
                "image": offline.image,
                "inventory": list(offline.inventory),
                "verification_digest": offline.verification_digest,
            },
            "manifest": {
                "manifest_id": registered_manifest.manifest.manifest_id,
                "manifest_digest": registered_manifest.manifest_digest,
                "authority_risk_floor": registered_manifest.authority_risk_floor.name,
            },
            "secret": {
                "store_protector_id": secret.store_protector_id,
                "consumer_id": secret.consumer_id,
                "scope": secret.scope,
                "child_digest": secret.child_digest,
                "persistence_files_scanned": secret.persistence_files_scanned,
            },
            "discovery": discovery,
            "restart": restart,
        }
        evidence["evidence_digest"] = canonical_digest(evidence)
        return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=pathlib.Path, required=True)
    parser.add_argument("--uv-release-asset", type=pathlib.Path, required=True)
    parser.add_argument("--uv-executable", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)

    try:
        evidence = run_acceptance(
            repo_root=args.repo_root,
            uv_release_asset=args.uv_release_asset,
            uv_executable=args.uv_executable,
        )
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "status": evidence["status"],
                "evidence_digest": evidence["evidence_digest"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
