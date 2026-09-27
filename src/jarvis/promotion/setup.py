"""One-time secure bootstrap for JARVIS governed GitHub promotion."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from jarvis.engineering_substrate.secrets.store import (
    SecretNotFoundError,
    SecretStore,
)
from jarvis.machine_config import (
    default_machine_config_path,
    load_machine_settings,
    save_machine_settings,
)

_CONSUMER_ID = "github.promotion.v1"
_SCOPE = "repository.promotion"
_DEFAULT_SECRET_ID = "github-promotion-private-key"
_MAX_PRIVATE_KEY_BYTES = 64 * 1024


class PromotionSetupError(RuntimeError):
    """The GitHub promotion bootstrap could not be completed safely."""


def _private_key(path: pathlib.Path) -> bytes:
    source = pathlib.Path(path).expanduser()
    if source.is_symlink() or not source.is_file():
        raise PromotionSetupError("private key must be a regular non-symlink file")
    size = source.stat().st_size
    if size <= 0 or size > _MAX_PRIVATE_KEY_BYTES:
        raise PromotionSetupError("private key file size is invalid")
    value = source.read_bytes()
    if (
        b"-----BEGIN" not in value
        or b"PRIVATE KEY-----" not in value
        or b"-----END" not in value
    ):
        raise PromotionSetupError("private key file is not PEM private-key material")
    return value


def configure_github_promotion(
    *,
    private_key_file: pathlib.Path,
    client_id: str,
    installation_id: int,
    repository_full_name: str,
    secret_id: str = _DEFAULT_SECRET_ID,
    base_branch: str = "main",
    workflow_file: str = "code-quality.yml",
    expected_ci_app_id: int | None = 15368,
    machine_config_path: pathlib.Path | None = None,
    secret_store: SecretStore | None = None,
) -> dict[str, object]:
    if sys.platform != "win32":
        raise PromotionSetupError(
            "GitHub promotion secret bootstrap requires Windows DPAPI"
        )
    client = str(client_id).strip()
    repository = str(repository_full_name).strip()
    secret = str(secret_id).strip()
    branch = str(base_branch).strip()
    workflow = str(workflow_file).strip()
    if not client or not repository or not secret or not branch or not workflow:
        raise PromotionSetupError("GitHub promotion identifiers must not be empty")
    if type(installation_id) is not int or installation_id <= 0:
        raise PromotionSetupError("installation_id must be positive")
    if expected_ci_app_id is not None and (
        type(expected_ci_app_id) is not int or expected_ci_app_id <= 0
    ):
        raise PromotionSetupError("expected_ci_app_id must be positive")

    key = _private_key(private_key_file)
    store = secret_store or SecretStore()
    try:
        descriptor = store.verified_descriptor(secret)
    except SecretNotFoundError:
        descriptor = store.enroll(
            secret_id=secret,
            kind="github-app-private-key",
            service="github-promotion",
            allowed_consumers=(_CONSUMER_ID,),
            allowed_scopes=(_SCOPE,),
            value=key,
        )
        disposition = "enrolled"
    else:
        if descriptor.allowed_consumers != (_CONSUMER_ID,) or descriptor.allowed_scopes != (
            _SCOPE,
        ):
            raise PromotionSetupError(
                "existing GitHub promotion secret has incompatible consumer/scope policy"
            )
        descriptor = store.rotate(secret, value=key)
        disposition = "rotated"

    machine_path = machine_config_path or default_machine_config_path()
    settings = load_machine_settings(machine_path)
    settings.update(
        {
            "JARVIS_GITHUB_PROMOTION_ENABLED": "true",
            "JARVIS_GITHUB_APP_CLIENT_ID": client,
            "JARVIS_GITHUB_APP_INSTALLATION_ID": str(installation_id),
            "JARVIS_GITHUB_REPOSITORY": repository,
            "JARVIS_GITHUB_APP_SECRET_ID": secret,
            "JARVIS_GITHUB_BASE_BRANCH": branch,
            "JARVIS_GITHUB_WORKFLOW_FILE": workflow,
            "JARVIS_GITHUB_EXPECTED_CI_APP_ID": (
                "none" if expected_ci_app_id is None else str(expected_ci_app_id)
            ),
        }
    )
    save_machine_settings(settings, machine_path)

    return {
        "status": "CONFIGURED",
        "secret_id": descriptor.secret_id,
        "secret_version": descriptor.version,
        "secret_disposition": disposition,
        "secret_protector_id": store.protector_id,
        "machine_config_path": str(machine_path.resolve()),
        "repository_full_name": repository,
        "installation_id": installation_id,
        "private_key_persisted_in_machine_config": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis-promotion-setup")
    parser.add_argument("--private-key-file", type=pathlib.Path, required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--installation-id", type=int, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--secret-id", default=_DEFAULT_SECRET_ID)
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--workflow-file", default="code-quality.yml")
    parser.add_argument("--expected-ci-app-id", type=int, default=15368)
    parser.add_argument("--machine-config", type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = configure_github_promotion(
            private_key_file=args.private_key_file,
            client_id=args.client_id,
            installation_id=args.installation_id,
            repository_full_name=args.repository,
            secret_id=args.secret_id,
            base_branch=args.base_branch,
            workflow_file=args.workflow_file,
            expected_ci_app_id=args.expected_ci_app_id,
            machine_config_path=args.machine_config,
        )
    except (OSError, RuntimeError, ValueError) as exc:
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
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
