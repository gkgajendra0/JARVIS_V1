"""Versioned JARVIS-owned sandbox profiles and deterministic Docker commands."""

from __future__ import annotations

import pathlib
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass

from jarvis.engineering_substrate.contracts import (
    SandboxFilesystemMode,
    SandboxNetworkMode,
    SandboxProfile,
)

_DOCKER_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")


class SandboxRegistryError(RuntimeError):
    """Base error for trusted sandbox profile lookup or command construction."""


class DuplicateSandboxProfileError(SandboxRegistryError):
    """An exact sandbox profile ID/version is already registered."""


class UnknownSandboxProfileError(SandboxRegistryError):
    """A requested sandbox profile ID/version is not registered."""


class SandboxPolicyError(SandboxRegistryError):
    """A launch request violates a registered sandbox policy."""


class SandboxResourceUnavailable(SandboxRegistryError):
    """Docker is unavailable; callers must block rather than execute on the host."""


def _has_symlink_component(path: pathlib.Path) -> bool:
    absolute = path.absolute()
    cursor = pathlib.Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.exists() and cursor.is_symlink():
            return True
    return False


@dataclass(frozen=True, slots=True)
class SandboxMountPolicy:
    policy_id: str
    target: str
    read_only: bool

    def __post_init__(self) -> None:
        policy_id = str(self.policy_id).strip().casefold()
        target = str(self.target).strip()
        if not policy_id:
            raise ValueError("policy_id must not be empty")
        if not target.startswith("/") or ".." in pathlib.PurePosixPath(target).parts:
            raise ValueError("sandbox mount target must be an absolute container path")
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "target", target)


@dataclass(frozen=True, slots=True)
class SandboxDefinition:
    profile: SandboxProfile
    mount_policies: tuple[SandboxMountPolicy, ...]
    image_workdir: str
    fixed_entrypoint: tuple[str, ...]

    def __post_init__(self) -> None:
        known = {item.policy_id for item in self.mount_policies}
        if known != set(self.profile.mount_policy_ids):
            raise ValueError("mount policies must exactly match SandboxProfile IDs")
        if len(known) != len(self.mount_policies):
            raise ValueError("sandbox mount policy IDs must be unique")
        if not self.image_workdir.startswith("/"):
            raise ValueError("image_workdir must be an absolute container path")
        if not self.fixed_entrypoint:
            raise ValueError("fixed_entrypoint must not be empty")


@dataclass(frozen=True, slots=True)
class SandboxMountBinding:
    policy_id: str
    source: pathlib.Path

    def __post_init__(self) -> None:
        token = str(self.policy_id).strip().casefold()
        if not token:
            raise ValueError("policy_id must not be empty")
        object.__setattr__(self, "policy_id", token)
        object.__setattr__(self, "source", pathlib.Path(self.source))


@dataclass(frozen=True, slots=True)
class SandboxLaunch:
    profile_id: str
    profile_version: int
    command: tuple[str, ...]
    timeout_seconds: float
    network_mode: SandboxNetworkMode


class SandboxRegistry:
    """Exact trusted sandbox definitions; model-authored Docker flags never enter."""

    def __init__(
        self,
        definitions: Iterable[SandboxDefinition] = (),
        *,
        docker_executable: str | None = None,
        protected_main_root: pathlib.Path | None = None,
    ) -> None:
        self._definitions: dict[tuple[str, int], SandboxDefinition] = {}
        self._docker_executable = docker_executable
        self._protected_main_root = (
            None
            if protected_main_root is None
            else pathlib.Path(protected_main_root).resolve()
        )
        for definition in definitions:
            self.register(definition)

    def register(self, definition: SandboxDefinition) -> None:
        if not isinstance(definition, SandboxDefinition):
            raise TypeError("definition must be a SandboxDefinition")
        key = (definition.profile.profile_id, definition.profile.profile_version)
        if key in self._definitions:
            raise DuplicateSandboxProfileError(
                f"sandbox profile already registered: {key[0]}.v{key[1]}"
            )
        self._definitions[key] = definition

    def require(self, profile_id: str, profile_version: int = 1) -> SandboxDefinition:
        key = (str(profile_id).strip().casefold(), int(profile_version))
        try:
            return self._definitions[key]
        except KeyError as exc:
            raise UnknownSandboxProfileError(
                f"unknown sandbox profile: {key[0]}.v{key[1]}"
            ) from exc

    def all(self) -> tuple[SandboxDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def _docker(self) -> str:
        docker = self._docker_executable or shutil.which("docker")
        if not docker:
            raise SandboxResourceUnavailable(
                "Docker is unavailable; sandbox-required work cannot fall back to host"
            )
        return docker

    @staticmethod
    def _image(value: str) -> str:
        image = str(value).strip()
        if not _DOCKER_IMAGE.fullmatch(image) or image.startswith("-"):
            raise SandboxPolicyError("Docker image reference is not a trusted token")
        return image

    def _mount_args(
        self,
        definition: SandboxDefinition,
        bindings: tuple[SandboxMountBinding, ...],
    ) -> list[str]:
        expected = {item.policy_id: item for item in definition.mount_policies}
        supplied: dict[str, SandboxMountBinding] = {}
        for binding in bindings:
            if binding.policy_id in supplied:
                raise SandboxPolicyError(
                    f"duplicate sandbox mount binding: {binding.policy_id}"
                )
            supplied[binding.policy_id] = binding
        if set(supplied) != set(expected):
            raise SandboxPolicyError(
                "sandbox mount bindings must exactly match profile"
            )

        args: list[str] = []
        home = pathlib.Path.home().resolve()
        for policy_id in sorted(expected):
            policy = expected[policy_id]
            source = supplied[policy_id].source
            if _has_symlink_component(source):
                raise SandboxPolicyError(
                    "sandbox mount source cannot traverse a symlink"
                )
            resolved = source.resolve()
            if resolved == home:
                raise SandboxPolicyError("entire owner home profile cannot be mounted")
            lower_parts = {part.casefold() for part in resolved.parts}
            if (
                "docker.sock" in lower_parts
                or resolved.name.casefold() == "docker.sock"
            ):
                raise SandboxPolicyError("Docker socket mount is forbidden")
            if (
                self._protected_main_root is not None
                and not policy.read_only
                and (
                    resolved == self._protected_main_root
                    or self._protected_main_root in resolved.parents
                )
            ):
                raise SandboxPolicyError(
                    "protected main cannot be mounted writable into a sandbox"
                )
            mode = ",readonly" if policy.read_only else ""
            args.extend(
                [
                    "--mount",
                    f"type=bind,src={resolved},dst={policy.target}{mode}",
                ]
            )
        return args

    def build_launch(
        self,
        *,
        profile_id: str,
        image: str,
        mounts: tuple[SandboxMountBinding, ...],
        profile_version: int = 1,
        trusted_suffix: tuple[str, ...] = (),
        requested_timeout_seconds: float | None = None,
    ) -> SandboxLaunch:
        definition = self.require(profile_id, profile_version)
        profile = definition.profile
        docker = self._docker()
        image_token = self._image(image)

        if trusted_suffix and profile.profile_id != "test.offline.v1":
            raise SandboxPolicyError(
                "runtime command suffix is only supported by the reviewed pytest adapter"
            )
        for item in trusted_suffix:
            text = str(item).strip()
            pure = pathlib.PurePath(text.split("::", 1)[0])
            if (
                not text
                or pure.is_absolute()
                or pathlib.PureWindowsPath(str(pure)).is_absolute()
                or ".." in pure.parts
                or text.startswith("-")
            ):
                raise SandboxPolicyError(
                    "pytest target must remain a relative non-option path"
                )

        timeout = profile.timeout_seconds
        if requested_timeout_seconds is not None:
            requested = float(requested_timeout_seconds)
            if requested <= 0:
                raise SandboxPolicyError("requested timeout must be positive")
            timeout = min(timeout, requested)

        network = (
            "none" if profile.network_mode is SandboxNetworkMode.NONE else "bridge"
        )
        command: list[str] = [
            docker,
            "run",
            "--rm",
            "--network",
            network,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(profile.pid_limit),
            "--memory",
            f"{profile.memory_limit_mb}m",
            "--cpus",
            f"{profile.cpu_limit:g}",
        ]
        command.extend(self._mount_args(definition, mounts))
        command.extend(
            [
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=512m",
                "--workdir",
                definition.image_workdir,
                image_token,
                *definition.fixed_entrypoint,
                *trusted_suffix,
            ]
        )
        return SandboxLaunch(
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            command=tuple(command),
            timeout_seconds=timeout,
            network_mode=profile.network_mode,
        )


def _profile(
    *,
    profile_id: str,
    entrypoint_id: str,
    network_mode: SandboxNetworkMode,
    mount_policy_ids: tuple[str, ...],
    timeout_seconds: float,
    allowed_secret_scopes: tuple[str, ...] = (),
) -> SandboxProfile:
    return SandboxProfile(
        profile_id=profile_id,
        profile_version=1,
        entrypoint_id=entrypoint_id,
        network_mode=network_mode,
        filesystem_mode=SandboxFilesystemMode.READ_ONLY_ROOT,
        mount_policy_ids=mount_policy_ids,
        dropped_capabilities=("all",),
        no_new_privileges=True,
        cpu_limit=2,
        memory_limit_mb=2048,
        pid_limit=128,
        timeout_seconds=timeout_seconds,
        environment_allowlist=(),
        allowed_secret_scopes=allowed_secret_scopes,
        output_policy_ids=("bounded_text.v1",),
    )


DEFAULT_SANDBOX_DEFINITIONS = (
    SandboxDefinition(
        profile=_profile(
            profile_id="test.offline.v1",
            entrypoint_id="pytest.v1",
            network_mode=SandboxNetworkMode.NONE,
            mount_policy_ids=("workspace_ro",),
            timeout_seconds=300,
        ),
        mount_policies=(SandboxMountPolicy("workspace_ro", "/workspace", True),),
        image_workdir="/workspace",
        fixed_entrypoint=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider"),
    ),
    SandboxDefinition(
        profile=_profile(
            profile_id="dependency.acquire.v1",
            entrypoint_id="dependency_acquire_worker.v1",
            network_mode=SandboxNetworkMode.REGISTERED_SOURCES,
            mount_policy_ids=("staging_rw", "worktree_ro"),
            timeout_seconds=300,
            allowed_secret_scopes=("repository.read",),
        ),
        mount_policies=(
            SandboxMountPolicy("staging_rw", "/staging", False),
            SandboxMountPolicy("worktree_ro", "/workspace", True),
        ),
        image_workdir="/workspace",
        fixed_entrypoint=(
            "python",
            "-m",
            "jarvis.engineering_substrate.dependency.worker",
            "acquire",
        ),
    ),
    SandboxDefinition(
        profile=_profile(
            profile_id="dependency.verify.v1",
            entrypoint_id="dependency_verify_worker.v1",
            network_mode=SandboxNetworkMode.NONE,
            mount_policy_ids=("artifacts_ro", "candidate_rw", "worktree_ro"),
            timeout_seconds=300,
        ),
        mount_policies=(
            SandboxMountPolicy("artifacts_ro", "/artifacts", True),
            SandboxMountPolicy("candidate_rw", "/candidate", False),
            SandboxMountPolicy("worktree_ro", "/workspace", True),
        ),
        image_workdir="/candidate",
        fixed_entrypoint=(
            "python",
            "-m",
            "jarvis.engineering_substrate.dependency.worker",
            "verify",
        ),
    ),
)


def default_sandbox_registry(
    *,
    docker_executable: str | None = None,
    protected_main_root: pathlib.Path | None = None,
) -> SandboxRegistry:
    return SandboxRegistry(
        DEFAULT_SANDBOX_DEFINITIONS,
        docker_executable=docker_executable,
        protected_main_root=protected_main_root,
    )
