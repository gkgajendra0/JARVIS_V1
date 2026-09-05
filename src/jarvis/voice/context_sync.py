"""Fail-closed capability policy for synchronizing JARVIS context to realtime providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jarvis.config import JarvisConfig


class ProviderContextSyncMode(StrEnum):
    """How a provider can receive a rebuilt JARVIS chat context."""

    INITIAL_HISTORY_ONLY = "initial_history_only"
    MID_SESSION_UPDATE = "mid_session_update"


@dataclass(frozen=True, slots=True)
class ProviderContextSyncCapability:
    provider: str
    model: str
    mode: ProviderContextSyncMode
    automatic_mid_session_sync_supported: bool
    reason: str


def provider_context_sync_capability(
    config: JarvisConfig,
) -> ProviderContextSyncCapability:
    """Return the supported context-sync boundary for the configured realtime model.

    This is intentionally conservative. A provider/model is not considered safe for
    automatic mid-session synchronization merely because LiveKit exposes a common
    ``update_chat_ctx`` method. The concrete provider adapter must support forwarding
    that update to the active model.
    """

    if not isinstance(config, JarvisConfig):
        raise TypeError("config must be a JarvisConfig")

    if config.realtime_provider == "gemini":
        model = config.gemini_realtime_model
        if model.casefold().startswith("gemini-3.1-"):
            return ProviderContextSyncCapability(
                provider="gemini",
                model=model,
                mode=ProviderContextSyncMode.INITIAL_HISTORY_ONLY,
                automatic_mid_session_sync_supported=False,
                reason=(
                    "LiveKit's Gemini 3.1 realtime adapter currently ignores "
                    "mid-session update_chat_ctx calls; keep provider-native history "
                    "and use supported function tools for explicit external context"
                ),
            )
        return ProviderContextSyncCapability(
            provider="gemini",
            model=model,
            mode=ProviderContextSyncMode.MID_SESSION_UPDATE,
            automatic_mid_session_sync_supported=True,
            reason="configured Gemini realtime model supports LiveKit chat-context updates",
        )

    return ProviderContextSyncCapability(
        provider="openai",
        model=config.realtime_model,
        mode=ProviderContextSyncMode.MID_SESSION_UPDATE,
        automatic_mid_session_sync_supported=True,
        reason="LiveKit OpenAI realtime adapter supports update_chat_ctx",
    )
