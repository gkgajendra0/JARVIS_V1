from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Any

CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
ALLOWED_LIFECYCLES = {"accepted", "shadow"}
ALLOWED_AUTHORITY_EFFECTS = {"none", "evidence", "governed_execution"}
ALLOWED_HEALTH_KINDS = {"test", "entrypoint"}
FORBIDDEN_KEYS = {
    "command",
    "shell",
    "script",
    "secret",
    "secrets",
    "token",
    "api_key",
    "apikey",
    "password",
}


def normalize_package(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repo_file(repo_root: Path, raw: str) -> Path:
    if not raw or "\\" in raw:
        raise ValueError(f"repository reference must use a non-empty POSIX path: {raw!r}")
    candidate = (repo_root / raw).resolve()
    if not candidate.is_relative_to(repo_root):
        raise ValueError(f"repository reference escapes repo root: {raw}")
    if not candidate.is_file():
        raise ValueError(f"repository reference is not a file: {raw}")
    return candidate


def find_forbidden_keys(value: Any, prefix: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN_KEYS:
                findings.append(f"{prefix}.{key}")
            findings.extend(find_forbidden_keys(child, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_forbidden_keys(child, f"{prefix}[{index}]"))
    return findings


def dependency_cycle(capabilities: dict[str, dict[str, Any]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    trail: list[str] = []

    def visit(capability_id: str) -> list[str] | None:
        if capability_id in visiting:
            start = trail.index(capability_id)
            return trail[start:] + [capability_id]
        if capability_id in visited:
            return None
        visiting.add(capability_id)
        trail.append(capability_id)
        for dependency in capabilities[capability_id].get("depends_on", []):
            cycle = visit(dependency)
            if cycle:
                return cycle
        trail.pop()
        visiting.remove(capability_id)
        visited.add(capability_id)
        return None

    for capability_id in capabilities:
        cycle = visit(capability_id)
        if cycle:
            return cycle
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sbom", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--git-sha", default=None)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    pyproject_path = repo_root / "pyproject.toml"
    sbom_path = Path(args.sbom).resolve()
    registry_path = Path(args.registry).resolve()
    output_path = Path(args.output).resolve()

    project_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = project_data["project"]
    project_name = str(project["name"])
    project_version = str(project["version"])
    scripts = project.get("scripts", {})
    optional_groups = project.get("optional-dependencies", {})

    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))

    checks: dict[str, bool] = {}
    errors: list[str] = []

    def record(name: str, condition: bool, detail: str) -> None:
        checks[name] = bool(condition)
        if not condition:
            errors.append(detail)

    record("sbom_format", sbom.get("bomFormat") == "CycloneDX", "SBOM is not CycloneDX")
    record("sbom_spec_17", sbom.get("specVersion") == "1.7", "SBOM specVersion is not 1.7")

    metadata_component = sbom.get("metadata", {}).get("component", {}) or {}
    record(
        "sbom_root_name",
        normalize_package(str(metadata_component.get("name", ""))) == normalize_package(project_name),
        f"SBOM metadata component name does not match {project_name}",
    )
    record(
        "sbom_root_version",
        str(metadata_component.get("version", "")) == project_version,
        f"SBOM metadata component version does not match {project_version}",
    )

    components = sbom.get("components", []) or []
    component_versions: dict[str, set[str]] = {}
    for component in components:
        name = normalize_package(str(component.get("name", "")))
        if not name:
            continue
        component_versions.setdefault(name, set()).add(str(component.get("version", "")))

    dependency_edges = sum(len(item.get("dependsOn", []) or []) for item in (sbom.get("dependencies", []) or []))

    record(
        "registry_research_only",
        registry.get("status") == "research-only",
        "Capability registry fixture must remain research-only during this spike",
    )
    record(
        "registry_schema",
        registry.get("schema_version") == "step4-research-v1",
        "Unexpected capability registry schema version",
    )

    forbidden = find_forbidden_keys(registry)
    record(
        "registry_no_executable_or_secret_fields",
        not forbidden,
        "Registry contains forbidden executable/secret-bearing fields: " + ", ".join(forbidden),
    )

    raw_capabilities = registry.get("capabilities", [])
    record(
        "registry_capabilities_nonempty",
        isinstance(raw_capabilities, list) and bool(raw_capabilities),
        "Registry contains no capabilities",
    )

    capabilities: dict[str, dict[str, Any]] = {}
    duplicate_ids: list[str] = []
    for capability in raw_capabilities if isinstance(raw_capabilities, list) else []:
        capability_id = str(capability.get("id", ""))
        if capability_id in capabilities:
            duplicate_ids.append(capability_id)
        capabilities[capability_id] = capability

    record("capability_ids_unique", not duplicate_ids, f"Duplicate capability IDs: {duplicate_ids}")
    invalid_ids = [capability_id for capability_id in capabilities if not CAPABILITY_ID.fullmatch(capability_id)]
    record("capability_ids_stable", not invalid_ids, f"Invalid capability IDs: {invalid_ids}")

    bad_lifecycle = [
        capability_id
        for capability_id, capability in capabilities.items()
        if capability.get("lifecycle") not in ALLOWED_LIFECYCLES
    ]
    record("capability_lifecycle_valid", not bad_lifecycle, f"Invalid capability lifecycle: {bad_lifecycle}")

    bad_authority = [
        capability_id
        for capability_id, capability in capabilities.items()
        if capability.get("authority_effect") not in ALLOWED_AUTHORITY_EFFECTS
    ]
    record("capability_authority_effect_valid", not bad_authority, f"Invalid authority effect: {bad_authority}")

    unknown_dependencies: list[str] = []
    self_dependencies: list[str] = []
    for capability_id, capability in capabilities.items():
        for dependency in capability.get("depends_on", []):
            if dependency == capability_id:
                self_dependencies.append(capability_id)
            elif dependency not in capabilities:
                unknown_dependencies.append(f"{capability_id}->{dependency}")
    record("capability_dependencies_known", not unknown_dependencies, f"Unknown capability dependencies: {unknown_dependencies}")
    record("capability_no_self_dependency", not self_dependencies, f"Self dependencies: {self_dependencies}")

    cycle = None
    if not unknown_dependencies and not self_dependencies:
        cycle = dependency_cycle(capabilities)
    record("capability_dependency_graph_acyclic", cycle is None, f"Capability dependency cycle: {cycle}")

    evidence_paths: set[str] = {"pyproject.toml", "docs/CURRENT_ARCHITECTURE.md"}
    missing_or_invalid_paths: list[str] = []
    missing_runtime_packages: list[str] = []
    unknown_optional_groups: list[str] = []
    invalid_health_checks: list[str] = []

    resolved_capabilities: list[dict[str, Any]] = []
    for capability_id, capability in capabilities.items():
        implementation_paths = list(capability.get("implementation_paths", []))
        source_refs = list(capability.get("source_refs", []))
        path_refs = implementation_paths + source_refs
        for ref in path_refs:
            try:
                repo_file(repo_root, ref)
            except ValueError as exc:
                missing_or_invalid_paths.append(f"{capability_id}: {exc}")
            else:
                evidence_paths.add(ref)

        resolved_runtime: dict[str, list[str]] = {}
        for package in capability.get("runtime_packages", []):
            normalized = normalize_package(str(package))
            versions = sorted(component_versions.get(normalized, set()))
            if not versions:
                missing_runtime_packages.append(f"{capability_id}:{package}")
            resolved_runtime[str(package)] = versions

        declared_optional: dict[str, list[str]] = {}
        for group in capability.get("optional_dependency_groups", []):
            if group not in optional_groups:
                unknown_optional_groups.append(f"{capability_id}:{group}")
                declared_optional[str(group)] = []
            else:
                declared_optional[str(group)] = list(optional_groups[group])

        resolved_health: list[dict[str, str]] = []
        for health in capability.get("health_checks", []):
            kind = health.get("kind")
            ref = str(health.get("ref", ""))
            if kind not in ALLOWED_HEALTH_KINDS:
                invalid_health_checks.append(f"{capability_id}:{kind}:{ref}")
                continue
            if kind == "test":
                try:
                    repo_file(repo_root, ref)
                except ValueError as exc:
                    invalid_health_checks.append(f"{capability_id}: {exc}")
                else:
                    evidence_paths.add(ref)
                    resolved_health.append({"kind": "test", "ref": ref})
            else:
                if ref not in scripts:
                    invalid_health_checks.append(f"{capability_id}: unknown entrypoint {ref}")
                else:
                    resolved_health.append({"kind": "entrypoint", "ref": ref})

        resolved_capabilities.append(
            {
                "id": capability_id,
                "lifecycle": capability.get("lifecycle"),
                "purpose": capability.get("purpose"),
                "depends_on": list(capability.get("depends_on", [])),
                "authority_effect": capability.get("authority_effect"),
                "runtime_packages": resolved_runtime,
                "optional_dependency_groups": declared_optional,
                "implementation_paths": implementation_paths,
                "source_refs": source_refs,
                "health_checks": resolved_health,
                "known_limitations": list(capability.get("known_limitations", [])),
            }
        )

    record("capability_repo_refs_exist", not missing_or_invalid_paths, "Invalid repository references: " + "; ".join(missing_or_invalid_paths))
    record("capability_runtime_packages_in_sbom", not missing_runtime_packages, "Runtime packages absent from SBOM: " + ", ".join(missing_runtime_packages))
    record("capability_optional_groups_declared", not unknown_optional_groups, "Unknown optional dependency groups: " + ", ".join(unknown_optional_groups))
    record("capability_health_refs_valid", not invalid_health_checks, "Invalid health references: " + "; ".join(invalid_health_checks))

    fingerprints: list[dict[str, str]] = []
    for ref in sorted(evidence_paths):
        path = repo_file(repo_root, ref)
        fingerprints.append({"path": ref, "sha256": sha256_file(path)})

    registry_repo_path: str | None = None
    if registry_path.is_relative_to(repo_root):
        registry_repo_path = registry_path.relative_to(repo_root).as_posix()
        fingerprints.append({"path": registry_repo_path, "sha256": sha256_file(registry_path)})

    status = "PASS" if all(checks.values()) else "FAIL"
    result = {
        "status": status,
        "purpose": "Step 4 research-only self-knowledge/SBOM evidence; not production architecture approval",
        "project": {
            "name": project_name,
            "version": project_version,
            "git_sha": args.git_sha,
        },
        "sbom": {
            "format": sbom.get("bomFormat"),
            "spec_version": sbom.get("specVersion"),
            "component_count": len(components),
            "dependency_edge_count": dependency_edges,
            "source_file": str(sbom_path),
        },
        "registry": {
            "schema_version": registry.get("schema_version"),
            "status": registry.get("status"),
            "source_authority": registry.get("source_authority", []),
            "source_file": registry_repo_path or str(registry_path),
            "capability_count": len(capabilities),
        },
        "capabilities": sorted(resolved_capabilities, key=lambda item: item["id"]),
        "authoritative_source_fingerprints": sorted(fingerprints, key=lambda item: item["path"]),
        "checks": checks,
        "errors": errors,
        "boundaries": [
            "The CycloneDX SBOM is generated dependency evidence, not canonical JARVIS architecture truth.",
            "The capability registry is declarative and contains references, not arbitrary executable instructions.",
            "Current runtime/configuration values remain owned by their authoritative runtime/configuration sources and are not copied into this snapshot.",
            "Learned operational observations must remain provenance-rich and cannot silently overwrite declared architecture or current runtime truth.",
            "No autonomous repair, self-modification, authority expansion, or deployment is implemented by this spike."
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"SELF_KNOWLEDGE_STATUS={status}")
    print(f"CYCLONEDX_SPEC={sbom.get('specVersion')}")
    print(f"SBOM_COMPONENTS={len(components)}")
    print(f"CAPABILITIES={len(capabilities)}")
    print(f"FINGERPRINTS={len(fingerprints)}")
    print(f"FAILED_CHECKS={[name for name, passed in checks.items() if not passed]}")

    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
