from jarvis.model_routing.live_policy import LiveUsageProfile, OperationalLivePolicy


def policy():
    return OperationalLivePolicy(provenance="offline-test-policy")


def profile(**changes):
    values = {
        "profile_id": "offline-only",
        "version": 1,
        "model_id": "gemini-3.8-live",
        "sdk_versions": {"google-genai": "2.22.0"},
        "config_ref": policy().fingerprint,
        "counter_scope": "generation",
        "field_map": {
            "input_tokens": "prompt_tokens_details.TEXT",
            "input_audio_tokens": "prompt_tokens_details.AUDIO",
            "output_tokens": "response_tokens_details.TEXT",
            "output_audio_tokens": "response_tokens_details.AUDIO",
        },
        "zero_rules": {},
        "transcription_mode": "response_text",
        "terminal_mode": "same_event",
        "source_refs": ("https://example.invalid/offline-only",),
        "evidence_digest": "a" * 64,
    }
    values.update(changes)
    return LiveUsageProfile(**values)


def usage():
    return {
        "prompt_token_count": 15,
        "response_token_count": 11,
        "thoughts_token_count": 2,
        "cached_content_token_count": 3,
        "tool_use_prompt_token_count": 0,
        "total_token_count": 28,
        "prompt_tokens_details": [
            {"modality": "TEXT", "token_count": 5},
            {"modality": "AUDIO", "token_count": 10},
        ],
        "response_tokens_details": [
            {"modality": "TEXT", "token_count": 4},
            {"modality": "AUDIO", "token_count": 7},
        ],
    }


class OperationalEndpoint:
    def __init__(self, runtime):
        self.runtime = runtime
        self.clients = 0
        self.wires = []
        self.configs = []

    def client(self):
        from types import SimpleNamespace

        assert self.runtime.paid_budget.status().reserved_inr_minor == 1000
        self.clients += 1
        return SimpleNamespace(
            aio=SimpleNamespace(
                live=SimpleNamespace(connect=self.connect), aclose=self.aclose
            )
        )

    async def aclose(self):
        pass

    def connect(self, *, model, config):
        from contextlib import asynccontextmanager

        from google.genai import types
        from tests.gemini_live.helpers import Wire

        @asynccontextmanager
        async def opened():
            self.configs.append(types.LiveConnectConfig.model_validate(config))
            wire = Wire(self)
            self.wires.append(wire)
            try:
                yield wire
            finally:
                wire.closed = True

        return opened()


def environment(tmp_path, **profile_changes):
    from types import SimpleNamespace

    from tests.gemini_live.test_budget import live_env

    from jarvis.voice.gemini_live_model import ControlledGeminiLiveModel
    from jarvis.voice.gemini_operational_budget import OperationalLiveAdmission
    from jarvis.voice.gemini_transport import GeminiTransportState

    _, runtime, target, _ = live_env(tmp_path)
    endpoint = OperationalEndpoint(runtime)
    state = GeminiTransportState(
        epoch=1, current_epoch=lambda: 1, authorize=lambda: True
    )
    a = OperationalLiveAdmission(
        runtime,
        session_id="original-session",
        authorize=lambda: True,
        policy=policy(),
        profile=profile(**profile_changes),
    )
    m = ControlledGeminiLiveModel(
        target=target,
        voice="Puck",
        state=state,
        admission=a,
        client_factory=endpoint.client,
    )
    return SimpleNamespace(
        model=m,
        session=m.session(turn_detection_disabled=True),
        runtime=runtime,
        endpoint=endpoint,
    )


def expensive_usage(tokens=85000):
    return {
        "prompt_token_count": tokens,
        "response_token_count": 0,
        "thoughts_token_count": 0,
        "cached_content_token_count": 0,
        "tool_use_prompt_token_count": 0,
        "total_token_count": tokens,
        "prompt_tokens_details": [
            {"modality": "TEXT", "token_count": tokens},
            {"modality": "AUDIO", "token_count": 0},
        ],
        "response_tokens_details": [
            {"modality": "TEXT", "token_count": 0},
            {"modality": "AUDIO", "token_count": 0},
        ],
    }
