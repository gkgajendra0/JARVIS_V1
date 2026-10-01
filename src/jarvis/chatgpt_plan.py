"""ChatGPT-plan OAuth and Responses transport for local JARVIS intelligence.

This module implements OpenAI's Sign in with ChatGPT flow for locally hosted /
open-source clients. ChatGPT-plan credentials are kept in the existing DPAPI-backed
SecretStore; only the stable, non-secret host identifier is stored as plain local
state. The inference transport deliberately follows the plan-sharing contract:
POST /v1/responses with store=false and stream=true.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import secrets
import threading
import time
import uuid
import webbrowser
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib import error, parse, request

from jarvis.engineering_substrate.secrets.store import (
    SecretAlreadyExistsError,
    SecretNotFoundError,
    SecretStore,
)

CHATGPT_PLAN_PROVIDER_ID = "chatgpt_plan"
CHATGPT_PLAN_TARGET_ID = "work.chatgpt_plan.default"
CHATGPT_PLAN_RESOURCE = "https://api.openai.com/v1"
CHATGPT_PLAN_RESPONSES_URL = f"{CHATGPT_PLAN_RESOURCE}/responses"
CHATGPT_PLAN_MODELS_URL = f"{CHATGPT_PLAN_RESOURCE}/models"
CHATGPT_PLAN_AUTHORIZATION_URL = "https://auth.openai.com/api/accounts/authorize"
CHATGPT_PLAN_TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
CHATGPT_PLAN_ISSUER = "https://auth.openai.com"
CHATGPT_PLAN_JWKS_URL = "https://auth.openai.com/.well-known/jwks.json"
CHATGPT_PLAN_DYNAMIC_CLIENT_ID = "dynamic_agent_client"
CHATGPT_PLAN_REQUIRED_SCOPE = "chatgpt.tokens.use.direct"
CHATGPT_PLAN_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "resource.invoke",
    CHATGPT_PLAN_REQUIRED_SCOPE,
)
CHATGPT_PLAN_SECRET_ID = "chatgpt-plan-oauth-active"
CHATGPT_PLAN_CONSUMER_ID = "jarvis-chatgpt-plan"
CHATGPT_PLAN_AGENT_NAME = "JARVIS"
CHATGPT_PLAN_REFRESH_SKEW_SECONDS = 90.0
_CHATGPT_PLAN_REFRESH_LOCK = threading.RLock()


class ChatGPTPlanError(RuntimeError):
    """Base error for ChatGPT-plan authentication or inference."""


class ChatGPTPlanNotConnected(ChatGPTPlanError):
    """No usable ChatGPT-plan registration is available."""

    status_code = 401
    code = "chatgpt_plan_not_connected"
    retryable = False


class ChatGPTPlanPermissionMissing(ChatGPTPlanError):
    """OAuth completed without permission to consume the ChatGPT plan."""

    status_code = 403
    code = "chatgpt_plan_permission_missing"
    retryable = False


class ChatGPTPlanHTTPError(ChatGPTPlanError):
    """HTTP/stream failure with machine-readable provider evidence."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.retryable = retryable


class ChatGPTPlanUsageUnavailable(ChatGPTPlanHTTPError):
    """The selected ChatGPT plan cannot currently fund this request."""


@dataclass(frozen=True, slots=True)
class ChatGPTPlanCredentials:
    email: str | None
    issuer: str
    subject: str
    client_id: str
    ext_agent_host_id: str
    id_token: str
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    scopes: tuple[str, ...]
    saved_at_epoch: float
    earliest_refresh_at_epoch: float | None = None

    @property
    def access_expires_at_epoch(self) -> float:
        return self.saved_at_epoch + float(self.expires_in)

    @property
    def plan_usage_enabled(self) -> bool:
        return CHATGPT_PLAN_REQUIRED_SCOPE in self.scopes

    def to_bytes(self) -> bytes:
        payload = asdict(self)
        payload["scopes"] = list(self.scopes)
        return json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> ChatGPTPlanCredentials:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ChatGPTPlanError(
                "stored ChatGPT-plan credentials are invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise ChatGPTPlanError("stored ChatGPT-plan credentials are invalid")
        try:
            return cls(
                email=(
                    None
                    if payload.get("email") is None
                    else str(payload["email"]).strip() or None
                ),
                issuer=str(payload["issuer"]),
                subject=str(payload["subject"]),
                client_id=str(payload["client_id"]),
                ext_agent_host_id=str(payload["ext_agent_host_id"]),
                id_token=str(payload["id_token"]),
                access_token=str(payload["access_token"]),
                refresh_token=str(payload["refresh_token"]),
                token_type=str(payload.get("token_type") or "Bearer"),
                expires_in=int(payload["expires_in"]),
                scopes=tuple(str(item) for item in payload["scopes"]),
                saved_at_epoch=float(payload["saved_at_epoch"]),
                earliest_refresh_at_epoch=(
                    None
                    if payload.get("earliest_refresh_at_epoch") is None
                    else float(payload["earliest_refresh_at_epoch"])
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ChatGPTPlanError(
                "stored ChatGPT-plan credentials are incomplete"
            ) from exc


@dataclass(frozen=True, slots=True)
class ChatGPTPlanModel:
    slug: str
    display_name: str


@dataclass(frozen=True, slots=True)
class ChatGPTPlanResponse:
    output_text: str
    usage: dict[str, int]
    usage_observed: bool


class CredentialStoreLike(Protocol):
    def load(self) -> ChatGPTPlanCredentials | None: ...

    def save(self, credentials: ChatGPTPlanCredentials) -> None: ...


class ChatGPTPlanCredentialStore:
    """Persist one active registration in JARVIS's encrypted SecretStore."""

    def __init__(self, secret_store: SecretStore | None = None) -> None:
        self._store = secret_store or SecretStore()

    def load(self) -> ChatGPTPlanCredentials | None:
        try:
            material = self._store.materialize(CHATGPT_PLAN_SECRET_ID)
        except SecretNotFoundError:
            return None
        return ChatGPTPlanCredentials.from_bytes(material.value)

    def save(self, credentials: ChatGPTPlanCredentials) -> None:
        if not isinstance(credentials, ChatGPTPlanCredentials):
            raise TypeError("credentials must be ChatGPTPlanCredentials")
        value = credentials.to_bytes()
        try:
            self._store.enroll(
                secret_id=CHATGPT_PLAN_SECRET_ID,
                kind="oauth-token-set",
                service="openai-chatgpt-plan",
                allowed_consumers=(CHATGPT_PLAN_CONSUMER_ID,),
                allowed_scopes=("responses", "models", "oauth-refresh"),
                value=value,
            )
        except SecretAlreadyExistsError:
            self._store.rotate(CHATGPT_PLAN_SECRET_ID, value=value)


def default_chatgpt_plan_host_path() -> Path:
    if os.name == "nt":
        base = Path(
            os.environ.get(
                "LOCALAPPDATA",
                str(Path.home() / "AppData" / "Local"),
            )
        )
    else:
        base = Path(
            os.environ.get(
                "XDG_STATE_HOME",
                str(Path.home() / ".local" / "state"),
            )
        )
    return (base / "JARVIS" / "chatgpt_plan_host.json").resolve()


def load_or_create_chatgpt_plan_host_id(path: Path | None = None) -> str:
    target = Path(path or default_chatgpt_plan_host_path()).resolve()
    if target.exists():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            host_id = str(payload["ext_agent_host_id"]).strip()
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ChatGPTPlanError("ChatGPT-plan host identity is invalid") from exc
        if not host_id.startswith("urn:uuid:"):
            raise ChatGPTPlanError("ChatGPT-plan host identity is invalid")
        return host_id

    host_id = f"urn:uuid:{uuid.uuid4()}"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {"schema_version": 1, "ext_agent_host_id": host_id},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return host_id


def _base64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _json_error_details(raw: bytes) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    error_payload = payload.get("error", payload)
    if not isinstance(error_payload, dict):
        return None, None
    code = error_payload.get("code")
    message = error_payload.get("message")
    return (
        str(code).strip() if code else None,
        str(message).strip() if message else None,
    )


def _request_json(
    url: str,
    *,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    body = None
    request_headers = dict(headers or {})
    if data is not None:
        body = parse.urlencode(data).encode("utf-8")
        request_headers.setdefault(
            "Content-Type",
            "application/x-www-form-urlencoded",
        )
    req = request.Request(url, data=body, headers=request_headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raw = exc.read()
        code, message = _json_error_details(raw)
        raise ChatGPTPlanHTTPError(
            message or f"ChatGPT-plan HTTP {exc.code}",
            status_code=exc.code,
            code=code,
        ) from exc
    except error.URLError as exc:
        raise ChatGPTPlanHTTPError(
            "ChatGPT-plan network request failed",
            retryable=True,
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ChatGPTPlanHTTPError(
            "ChatGPT-plan endpoint returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ChatGPTPlanHTTPError("ChatGPT-plan endpoint returned invalid JSON")
    return payload


def _validate_id_token(
    id_token: str,
    *,
    client_id: str,
    nonce: str,
) -> dict[str, Any]:
    """Verify signature + OIDC issuer/audience/expiry/nonce."""

    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise ChatGPTPlanError(
            "PyJWT is required for Sign in with ChatGPT token validation"
        ) from exc

    try:
        header = jwt.get_unverified_header(id_token)
        algorithm = str(header.get("alg") or "").strip()
        if algorithm not in {"RS256", "ES256"}:
            raise ChatGPTPlanError(
                f"unsupported ChatGPT ID-token signing algorithm: {algorithm or 'missing'}"
            )
        signing_key = jwt.PyJWKClient(CHATGPT_PLAN_JWKS_URL).get_signing_key_from_jwt(
            id_token
        )
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=[algorithm],
            audience=client_id,
            issuer=CHATGPT_PLAN_ISSUER,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )
    except ChatGPTPlanError:
        raise
    except Exception as exc:
        raise ChatGPTPlanError("ChatGPT ID-token validation failed") from exc

    if not isinstance(claims, dict):
        raise ChatGPTPlanError("ChatGPT ID token contained invalid claims")
    if str(claims.get("nonce") or "") != nonce:
        raise ChatGPTPlanError("ChatGPT ID-token nonce did not match the request")
    if not str(claims.get("sub") or "").strip():
        raise ChatGPTPlanError("ChatGPT ID token has no subject")
    return claims


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    result_queue: queue.Queue[dict[str, str]]

    def do_GET(self) -> None:
        parsed_url = parse.urlparse(self.path)
        if parsed_url.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            return
        values = parse.parse_qs(parsed_url.query, keep_blank_values=True)
        flattened = {key: items[0] for key, items in values.items() if items}
        self.result_queue.put(flattened)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>JARVIS connected to ChatGPT.</h2>"
            b"<p>You can close this window and return to the terminal.</p>"
            b"</body></html>"
        )

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def _wait_for_oauth_callback(
    *,
    authorization_url_builder,
    timeout_seconds: float,
) -> dict[str, str]:
    result_queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=1)

    class Handler(_OAuthCallbackHandler):
        pass

    Handler.result_queue = result_queue
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1.0
    port = int(server.server_address[1])
    redirect_uri = f"http://127.0.0.1:{port}/auth/callback"
    authorization_url = authorization_url_builder(redirect_uri)
    webbrowser.open(authorization_url, new=1, autoraise=True)

    deadline = time.monotonic() + timeout_seconds
    try:
        while time.monotonic() < deadline:
            server.handle_request()
            try:
                return result_queue.get_nowait()
            except queue.Empty:
                continue
    finally:
        server.server_close()
    raise ChatGPTPlanError("Timed out waiting for ChatGPT authorization")


def _normalize_scopes(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = value.split()
    elif isinstance(value, list | tuple):
        raw = [str(item) for item in value]
    else:
        raw = []
    return tuple(dict.fromkeys(item.strip() for item in raw if item.strip()))


def _usage_from_response(response_payload: object) -> tuple[dict[str, int], bool]:
    if not isinstance(response_payload, dict):
        return {}, False
    usage = response_payload.get("usage")
    if not isinstance(usage, dict):
        return {}, False
    normalized: dict[str, int] = {}
    aliases = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "total_tokens": "total_tokens",
    }
    for source, target in aliases.items():
        value = usage.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            normalized[target] = value
    return normalized, bool(normalized)


def _schema_name(value: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in {"_", "-"} else "_" for char in value
    ).strip("_")
    return (cleaned or "jarvis_response")[:64]


def _strict_json_schema(value: object) -> object:
    """Project Pydantic JSON Schema into OpenAI strict-output shape."""

    if isinstance(value, list):
        return [_strict_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {
        str(key): _strict_json_schema(item)
        for key, item in value.items()
        if key != "default"
    }
    if normalized.get("type") == "object":
        properties = normalized.get("properties")
        if isinstance(properties, dict):
            normalized["additionalProperties"] = False
            normalized["required"] = list(properties)
        else:
            additional = normalized.get("additionalProperties")
            if additional not in {None, False}:
                raise ValueError(
                    "OpenAI strict structured output cannot contain dynamic object "
                    "maps; use a fixed object model or encode flexible JSON as a string"
                )
            normalized["properties"] = {}
            normalized["additionalProperties"] = False
            normalized["required"] = []
    return normalized


class ChatGPTPlanSessionManager:
    """Own OAuth renewal, model discovery, and plan-backed Responses transport."""

    def __init__(
        self,
        *,
        credential_store: CredentialStoreLike | None = None,
        host_path: Path | None = None,
        clock=time.time,
    ) -> None:
        self._credentials = credential_store or ChatGPTPlanCredentialStore()
        self._host_path = host_path
        self._clock = clock
        # Refresh tokens rotate. All managers in this process must serialize refreshes.
        self._refresh_lock = _CHATGPT_PLAN_REFRESH_LOCK

    def current_credentials(self) -> ChatGPTPlanCredentials | None:
        return self._credentials.load()

    def is_connected(self) -> bool:
        credentials = self.current_credentials()
        return bool(credentials and credentials.plan_usage_enabled)

    def sign_in(
        self,
        *,
        timeout_seconds: float = 300.0,
    ) -> ChatGPTPlanCredentials:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        existing = self.current_credentials()
        host_id = load_or_create_chatgpt_plan_host_id(self._host_path)
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = _base64url_sha256(verifier)
        requested_client_id = (
            existing.client_id
            if existing is not None
            else CHATGPT_PLAN_DYNAMIC_CLIENT_ID
        )

        redirect_holder: dict[str, str] = {}

        def authorization_url(redirect_uri: str) -> str:
            redirect_holder["uri"] = redirect_uri
            params = {
                "client_id": requested_client_id,
                "ext_agent_host_id": host_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": " ".join(CHATGPT_PLAN_SCOPES),
                "resource": CHATGPT_PLAN_RESOURCE,
                "state": state,
                "nonce": nonce,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
            }
            if existing is None:
                params["agent_name_hint"] = CHATGPT_PLAN_AGENT_NAME
            else:
                params["id_token_hint"] = existing.id_token
                if existing.email:
                    params["login_hint"] = existing.email
            return CHATGPT_PLAN_AUTHORIZATION_URL + "?" + parse.urlencode(params)

        callback = _wait_for_oauth_callback(
            authorization_url_builder=authorization_url,
            timeout_seconds=timeout_seconds,
        )
        if callback.get("state") != state:
            raise ChatGPTPlanError("ChatGPT OAuth state did not match the request")
        if callback.get("error"):
            raise ChatGPTPlanError(f"ChatGPT authorization failed: {callback['error']}")
        code = str(callback.get("code") or "").strip()
        if not code:
            raise ChatGPTPlanError("ChatGPT authorization callback contained no code")

        if existing is None:
            issued_client_id = str(callback.get("client_id") or "").strip()
            if (
                not issued_client_id
                or issued_client_id == CHATGPT_PLAN_DYNAMIC_CLIENT_ID
            ):
                raise ChatGPTPlanError(
                    "ChatGPT dynamic registration did not return an issued client ID"
                )
        else:
            callback_client_id = str(callback.get("client_id") or "").strip()
            if callback_client_id and callback_client_id != existing.client_id:
                raise ChatGPTPlanError(
                    "ChatGPT authorization returned a different client registration"
                )
            issued_client_id = existing.client_id

        token_payload = _request_json(
            CHATGPT_PLAN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": issued_client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_holder["uri"],
                "resource": CHATGPT_PLAN_RESOURCE,
            },
        )
        id_token = str(token_payload.get("id_token") or "").strip()
        access_token = str(token_payload.get("access_token") or "").strip()
        refresh_token = str(token_payload.get("refresh_token") or "").strip()
        if not id_token or not access_token or not refresh_token:
            raise ChatGPTPlanError("ChatGPT token response was incomplete")

        claims = _validate_id_token(
            id_token,
            client_id=issued_client_id,
            nonce=nonce,
        )
        subject = str(claims["sub"]).strip()
        if existing is not None and subject != existing.subject:
            raise ChatGPTPlanError(
                "ChatGPT reauthorization identity did not match the saved account"
            )

        scopes = _normalize_scopes(token_payload.get("scope"))
        if CHATGPT_PLAN_REQUIRED_SCOPE not in scopes:
            raise ChatGPTPlanPermissionMissing(
                "ChatGPT authorization did not grant plan usage permission"
            )

        now = float(self._clock())
        expires_in = int(token_payload.get("expires_in") or 0)
        if expires_in <= 0:
            raise ChatGPTPlanError("ChatGPT token response has invalid expiry")
        earliest = token_payload.get("earliest_refresh_at")
        credentials = ChatGPTPlanCredentials(
            email=(
                str(claims.get("email")).strip()
                if claims.get("email") is not None
                else None
            ),
            issuer=str(claims.get("iss") or CHATGPT_PLAN_ISSUER),
            subject=subject,
            client_id=issued_client_id,
            ext_agent_host_id=host_id,
            id_token=id_token,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=str(token_payload.get("token_type") or "Bearer"),
            expires_in=expires_in,
            scopes=scopes,
            saved_at_epoch=now,
            earliest_refresh_at_epoch=(None if earliest is None else float(earliest)),
        )
        self._credentials.save(credentials)
        return credentials

    def _refresh(self, previous: ChatGPTPlanCredentials) -> ChatGPTPlanCredentials:
        try:
            payload = _request_json(
                CHATGPT_PLAN_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": previous.client_id,
                    "refresh_token": previous.refresh_token,
                    "resource": CHATGPT_PLAN_RESOURCE,
                },
            )
        except ChatGPTPlanHTTPError as exc:
            if exc.code == "invalid_grant":
                raise ChatGPTPlanHTTPError(
                    "ChatGPT-plan authorization must be renewed",
                    status_code=401,
                    code=exc.code,
                    retryable=False,
                ) from exc
            raise
        access_token = str(payload.get("access_token") or "").strip()
        refresh_token = str(payload.get("refresh_token") or "").strip()
        if not access_token or not refresh_token:
            raise ChatGPTPlanError("ChatGPT refresh response was incomplete")

        scopes = _normalize_scopes(payload.get("scope")) or previous.scopes
        if CHATGPT_PLAN_REQUIRED_SCOPE not in scopes:
            raise ChatGPTPlanPermissionMissing(
                "ChatGPT refresh no longer grants plan usage permission"
            )
        expires_in = int(payload.get("expires_in") or previous.expires_in)
        earliest = payload.get("earliest_refresh_at")
        refreshed = ChatGPTPlanCredentials(
            email=previous.email,
            issuer=previous.issuer,
            subject=previous.subject,
            client_id=previous.client_id,
            ext_agent_host_id=previous.ext_agent_host_id,
            id_token=str(payload.get("id_token") or previous.id_token),
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=str(payload.get("token_type") or previous.token_type),
            expires_in=expires_in,
            scopes=scopes,
            saved_at_epoch=float(self._clock()),
            earliest_refresh_at_epoch=(
                previous.earliest_refresh_at_epoch
                if earliest is None
                else float(earliest)
            ),
        )
        self._credentials.save(refreshed)
        return refreshed

    def access_token(self) -> str:
        with self._refresh_lock:
            credentials = self.current_credentials()
            if credentials is None or not credentials.plan_usage_enabled:
                raise ChatGPTPlanNotConnected(
                    "JARVIS is not connected to ChatGPT plan usage"
                )
            now = float(self._clock())
            refresh_at = (
                credentials.access_expires_at_epoch - CHATGPT_PLAN_REFRESH_SKEW_SECONDS
            )
            if now < refresh_at:
                return credentials.access_token
            return self._refresh(credentials).access_token

    def list_models(self) -> tuple[ChatGPTPlanModel, ...]:
        payload = _request_json(
            CHATGPT_PLAN_MODELS_URL,
            headers={"Authorization": f"Bearer {self.access_token()}"},
        )
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise ChatGPTPlanError("ChatGPT model catalog has an invalid shape")
        models: list[ChatGPTPlanModel] = []
        for item in raw_models:
            if not isinstance(item, dict) or item.get("visibility") != "list":
                continue
            slug = str(item.get("slug") or "").strip()
            if not slug:
                continue
            models.append(
                ChatGPTPlanModel(
                    slug=slug,
                    display_name=str(item.get("display_name") or slug).strip() or slug,
                )
            )
        if not models:
            raise ChatGPTPlanError(
                "The connected ChatGPT account exposed no selectable plan models"
            )
        return tuple(models)

    def invoke_structured(
        self,
        *,
        model: str,
        instructions: str,
        input_payload: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
        timeout_seconds: float = 120.0,
    ) -> ChatGPTPlanResponse:
        normalized_model = str(model).strip()
        if not normalized_model:
            raise ValueError("model must not be empty")
        body = json.dumps(
            {
                "model": normalized_model,
                "instructions": instructions,
                "input": [
                    {
                        "role": "user",
                        "content": json.dumps(
                            input_payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                            default=str,
                        ),
                    }
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": _schema_name(schema_name),
                        "strict": True,
                        "schema": _strict_json_schema(schema),
                    }
                },
                "store": False,
                "stream": True,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        req = request.Request(
            CHATGPT_PLAN_RESPONSES_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self.access_token()}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )

        output: list[str] = []
        completed_payload: dict[str, Any] | None = None
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ChatGPTPlanHTTPError(
                            "ChatGPT plan returned an invalid stream event"
                        ) from exc
                    if not isinstance(event, dict):
                        continue
                    event_type = str(event.get("type") or "")
                    if event_type == "response.output_text.delta":
                        delta = event.get("delta")
                        if isinstance(delta, str):
                            output.append(delta)
                    elif event_type == "response.failed":
                        response_payload = event.get("response")
                        error_payload = (
                            response_payload.get("error")
                            if isinstance(response_payload, dict)
                            else None
                        )
                        code = (
                            str(error_payload.get("code") or "").strip()
                            if isinstance(error_payload, dict)
                            else ""
                        )
                        message = (
                            str(error_payload.get("message") or "").strip()
                            if isinstance(error_payload, dict)
                            else ""
                        )
                        if code in {
                            "subscription_sharing_usage_limit_exceeded",
                            "subscription_sharing_usage_unavailable",
                        }:
                            raise ChatGPTPlanUsageUnavailable(
                                message or code,
                                status_code=429,
                                code=code,
                                retryable=True,
                            )
                        raise ChatGPTPlanHTTPError(
                            message
                            or f"ChatGPT plan response failed: {code or 'unknown'}",
                            code=code or None,
                        )
                    elif event_type == "error":
                        error_payload = event.get("error")
                        code = (
                            str(error_payload.get("code") or "").strip()
                            if isinstance(error_payload, dict)
                            else ""
                        )
                        message = (
                            str(error_payload.get("message") or "").strip()
                            if isinstance(error_payload, dict)
                            else ""
                        )
                        if code in {
                            "subscription_sharing_usage_limit_exceeded",
                            "subscription_sharing_usage_unavailable",
                        }:
                            raise ChatGPTPlanUsageUnavailable(
                                message or code,
                                status_code=429,
                                code=code,
                                retryable=True,
                            )
                        raise ChatGPTPlanHTTPError(
                            message
                            or f"ChatGPT plan stream error: {code or 'unknown'}",
                            code=code or None,
                        )
                    elif event_type == "response.incomplete":
                        raise ChatGPTPlanHTTPError(
                            "ChatGPT plan response was incomplete",
                            retryable=True,
                        )
                    elif event_type == "response.completed":
                        payload = event.get("response")
                        completed_payload = payload if isinstance(payload, dict) else {}
        except error.HTTPError as exc:
            raw = exc.read()
            code, message = _json_error_details(raw)
            if code in {
                "subscription_sharing_usage_limit_exceeded",
                "subscription_sharing_usage_unavailable",
            }:
                raise ChatGPTPlanUsageUnavailable(
                    message or code,
                    status_code=exc.code,
                    code=code,
                    retryable=True,
                ) from exc
            raise ChatGPTPlanHTTPError(
                message or f"ChatGPT-plan HTTP {exc.code}",
                status_code=exc.code,
                code=code,
            ) from exc
        except error.URLError as exc:
            raise ChatGPTPlanHTTPError(
                "ChatGPT-plan inference network request failed",
                retryable=True,
            ) from exc

        if completed_payload is None:
            raise ChatGPTPlanHTTPError(
                "ChatGPT plan stream ended without response.completed",
                retryable=True,
            )
        text = "".join(output).strip()
        if not text:
            raise ChatGPTPlanHTTPError(
                "ChatGPT plan completed without structured output text"
            )
        usage, observed = _usage_from_response(completed_payload)
        return ChatGPTPlanResponse(
            output_text=text,
            usage=usage,
            usage_observed=observed,
        )


def utc_saved_at(credentials: ChatGPTPlanCredentials) -> str:
    return datetime.fromtimestamp(
        credentials.saved_at_epoch,
        tz=UTC,
    ).isoformat()
