from __future__ import annotations

import json
import subprocess
import sys
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from jarvis.authority.tooling import builtin_windows_hello_command

from .proposal import ActionProposal


class StrongVerifierError(RuntimeError):
    pass


class StrongVerificationStatus(str, Enum):
    VERIFIED = "verified"
    CANCELED = "canceled"
    FAILED = "failed"
    RETRIES_EXHAUSTED = "retries_exhausted"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class StrongVerificationResult:
    status: StrongVerificationStatus
    verifier_id: str
    verification_id: str | None = None
    proposal_fingerprint: str | None = None
    session_id: str | None = None
    reason_codes: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status is StrongVerificationStatus.VERIFIED

    def is_bound_to(self, *, proposal: ActionProposal, session_id: str) -> bool:
        return (
            self.proposal_fingerprint == proposal.fingerprint
            and self.session_id == session_id
        )


class StrongVerifier(Protocol):
    def verify(
        self,
        *,
        proposal: ActionProposal,
        session_id: str,
    ) -> StrongVerificationResult: ...


class WindowsHelloVerifier:
    """Desktop Windows Hello verifier (UserConsentVerifier for an owner window).

    By default the prompt runs in the signed Python runtime
    (``jarvis.authority.windows_hello_consent``), so no separately compiled
    executable has to pass Smart App Control. ``helper_path`` runs a separate
    executable with the same JSON contract instead (tests and diagnostics).
    """

    verifier_id = "windows-hello-userconsentverifier-v1"

    def __init__(
        self,
        helper_path: str | Path | None = None,
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._helper_path = (
            Path(helper_path).expanduser() if helper_path is not None else None
        )
        self._timeout_seconds = timeout_seconds

    def _command(self) -> list[str] | None:
        if self._helper_path is None:
            return list(builtin_windows_hello_command())
        if not self._helper_path.is_file():
            return None
        return [str(self._helper_path)]

    def verify(
        self,
        *,
        proposal: ActionProposal,
        session_id: str,
    ) -> StrongVerificationResult:
        verification_id = str(uuid.uuid4())

        def result(
            status: StrongVerificationStatus,
            reason: str,
        ) -> StrongVerificationResult:
            return self._result(
                status,
                reason,
                verification_id=verification_id,
                proposal=proposal,
                session_id=session_id,
            )

        if sys.platform != "win32":
            return result(StrongVerificationStatus.UNAVAILABLE, "not_windows")
        if proposal.session_id != session_id:
            return result(StrongVerificationStatus.ERROR, "session_mismatch")
        if not proposal.has_valid_fingerprint():
            return result(StrongVerificationStatus.ERROR, "proposal_integrity_invalid")
        command = self._command()
        if command is None:
            return result(StrongVerificationStatus.UNAVAILABLE, "helper_not_found")

        request = json.dumps(
            {"message": f"Authorize JARVIS action: {proposal.material_summary}"},
            ensure_ascii=False,
        )
        try:
            completed = subprocess.run(
                command,
                input=request,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                check=False,
                timeout=self._timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return result(StrongVerificationStatus.ERROR, "helper_timeout")
        except (OSError, UnicodeError):
            return result(StrongVerificationStatus.ERROR, "helper_launch_failed")

        try:
            payload = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError):
            return result(StrongVerificationStatus.ERROR, "helper_invalid_output")
        if not isinstance(payload, dict):
            return result(StrongVerificationStatus.ERROR, "helper_invalid_output")

        raw_status = payload.get("status")
        reason = payload.get("reason")
        if not isinstance(raw_status, str) or not isinstance(reason, str):
            return result(StrongVerificationStatus.ERROR, "helper_invalid_output")
        try:
            status = StrongVerificationStatus(raw_status)
        except ValueError:
            return result(StrongVerificationStatus.ERROR, "helper_unknown_status")
        if completed.returncode != 0 and status is not StrongVerificationStatus.ERROR:
            return result(StrongVerificationStatus.ERROR, "helper_failed")
        return result(status, reason)

    def _result(
        self,
        status: StrongVerificationStatus,
        reason: str,
        *,
        verification_id: str,
        proposal: ActionProposal,
        session_id: str,
    ) -> StrongVerificationResult:
        return StrongVerificationResult(
            status=status,
            verifier_id=self.verifier_id,
            verification_id=verification_id,
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
            reason_codes=(reason,),
        )
