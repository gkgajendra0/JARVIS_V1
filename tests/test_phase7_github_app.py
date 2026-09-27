from __future__ import annotations

import base64
import json
from contextlib import contextmanager

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from jarvis.dev_control import RuntimeReleaseIdentity
from jarvis.engineering_substrate.secrets.broker import (
    default_secret_consumer_registry,
)
from jarvis.promotion.github_app import (
    BrokeredGitHubAppClient,
    GitHubAppConfig,
)
from jarvis.promotion.github_app_helper import _github_jwt

BASE = "1" * 40
HEAD = "2" * 40
MERGE = "3" * 40


def _decode(segment: str) -> dict[str, object]:
    padding_bytes = "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment + padding_bytes))


def test_github_app_jwt_is_rs256_bound_and_short_lived() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")

    token = _github_jwt(pem, "Iv1.phase7", now=1_000)
    header_text, payload_text, signature_text = token.split(".")
    header = _decode(header_text)
    payload = _decode(payload_text)

    assert header == {"alg": "RS256", "typ": "JWT"}
    assert payload == {"exp": 1540, "iat": 940, "iss": "Iv1.phase7"}
    signature = base64.urlsafe_b64decode(
        signature_text + "=" * (-len(signature_text) % 4)
    )
    private_key.public_key().verify(
        signature,
        f"{header_text}.{payload_text}".encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_default_secret_registry_scopes_github_private_key_consumer() -> None:
    policy = default_secret_consumer_registry().require("github.promotion.v1")

    assert policy.allowed_scopes == ("repository.promotion",)
    assert policy.secret_environment_variable == "JARVIS_GITHUB_APP_PRIVATE_KEY"
    assert "PYTHONPATH" not in policy.inherited_environment_allowlist


class _Broker:
    @contextmanager
    def child_environment(self, lease_id, *, consumer_id, parent_environment=None):
        del parent_environment
        assert lease_id == "lease-1"
        assert consumer_id == "github.promotion.v1"
        environment = {
            "PATH": "test-path",
            "JARVIS_GITHUB_APP_PRIVATE_KEY": "private-key-material",
        }
        try:
            yield environment
        finally:
            environment.clear()


class _FakeStdin:
    def __init__(self, process) -> None:
        self.process = process

    def write(self, text: str) -> int:
        request = json.loads(text)
        op = request["op"]
        if op == "bootstrap":
            result = {"ready": True}
        elif op == "publish_candidate":
            result = {
                "branch": request["branch"],
                "head_sha": request["head_sha"],
                "published": True,
            }
        elif op == "ensure_pull_request" or op == "read_pull_request":
            result = {
                "number": 12,
                "base_sha": BASE,
                "head_sha": HEAD,
                "draft": False,
                "state": "open",
                "merged": False,
                "merge_sha": None,
            }
        elif op == "read_workflow":
            result = {
                "run_id": "99",
                "event": "pull_request",
                "head_sha": HEAD,
                "tested_merge_sha": MERGE,
                "status": "completed",
                "conclusion": "success",
                "checks": [
                    {"context": "ruff", "conclusion": "success", "app_id": 15368}
                ],
            }
        elif op == "read_protected_main_sha":
            result = {"sha": BASE}
        elif op == "squash_merge":
            result = {"sha": MERGE}
        elif op == "shutdown":
            result = {"shutdown": True}
        else:
            raise AssertionError(f"unexpected RPC operation: {op}")
        self.process.responses.append(json.dumps({"ok": True, "result": result}) + "\n")
        return len(text)

    def flush(self) -> None:
        return None


class _FakeStdout:
    def __init__(self, process) -> None:
        self.process = process

    def readline(self) -> str:
        return self.process.responses.pop(0)


class _FakeProcess:
    def __init__(self) -> None:
        self.responses: list[str] = []
        self.stdin = _FakeStdin(self)
        self.stdout = _FakeStdout(self)
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True

    def wait(self, timeout=None) -> int:
        del timeout
        self.terminated = True
        return 0


def test_brokered_client_exposes_only_typed_github_operations(tmp_path) -> None:
    release_root = tmp_path / "release"
    helper = release_root / "src" / "jarvis" / "promotion" / "github_app_helper.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("# fixture\n", encoding="utf-8")
    process = _FakeProcess()
    captured = {}

    def factory(args, **kwargs):
        captured["args"] = args
        captured["env"] = dict(kwargs["env"])
        captured["cwd"] = kwargs["cwd"]
        return process

    identity = RuntimeReleaseIdentity(
        release_sha="a" * 40,
        release_root=str(release_root),
        promotion_attempt_id="promotion_fixture",
        config_digest="b" * 64,
    )
    client = BrokeredGitHubAppClient(
        broker=_Broker(),
        lease_id="lease-1",
        config=GitHubAppConfig(
            client_id="Iv1.phase7",
            installation_id=123,
            repository_full_name="gkgajendra0/JARVIS_V1",
        ),
        release_identity=identity,
        process_factory=factory,
    )

    workspace = tmp_path / "candidate"
    workspace.mkdir()
    with client:
        client.publish_candidate(
            workspace_root=workspace,
            branch="repair/phase7",
            head_sha=HEAD,
        )
        pr = client.ensure_pull_request(
            branch="repair/phase7",
            head_sha=HEAD,
            base_sha=BASE,
            title="Phase 7",
            body="Exact candidate",
        )
        workflow = client.read_workflow(pr.number)
        assert client.read_protected_main_sha() == BASE
        assert client.squash_merge(12, expected_head_sha=HEAD) == MERGE

    assert pr.head_sha == HEAD
    assert workflow.tested_merge_sha == MERGE
    assert captured["args"][1] == str(helper.resolve())
    assert captured["cwd"] == release_root.resolve()
    assert captured["env"]["JARVIS_GITHUB_APP_PRIVATE_KEY"] == "private-key-material"
    assert process.terminated
