"""Machine-profile configuration with environment overrides for JARVIS."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from jarvis.ai_provider import (
    configured_ai_provider,
    configured_tts_provider,
    normalize_ai_provider,
    normalize_tts_provider,
)
from jarvis.autonomy.mode import AutonomyMode
from jarvis.machine_config import configured_text, load_machine_settings
from jarvis.runtime_lane import (
    GiccMode,
    RuntimeLane,
    configured_gicc_mode,
    configured_runtime_lane,
    validate_gicc_runtime_policy,
)

VALID_LOG_LEVELS = frozenset({"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"})
TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})
DEFAULT_GEMINI_REALTIME_MODEL = "gemini-3.8-live"
LEGACY_GEMINI_REALTIME_MODELS = frozenset({"gemini-3.1-flash-live-preview"})


def _configured_bool(
    name: str,
    default: bool,
    machine_settings: Mapping[str, str],
) -> bool:
    value = configured_text(name, machine_settings)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"Unsupported {name}: {value!r}")


def _configured_float(
    name: str,
    default: float,
    machine_settings: Mapping[str, str],
) -> float:
    value = configured_text(name, machine_settings)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported {name}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"Unsupported {name}: {value!r}")
    return parsed


def _configured_int(
    name: str,
    default: int,
    machine_settings: Mapping[str, str],
) -> int:
    value = configured_text(name, machine_settings)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported {name}: {value!r}") from exc


def _configured_autonomy_mode(
    machine_settings: Mapping[str, str],
) -> AutonomyMode:
    value = configured_text(
        "JARVIS_AUTONOMY_MODE",
        machine_settings,
        AutonomyMode.SHADOW.value,
    )
    assert value is not None
    try:
        return AutonomyMode(value.strip().casefold())
    except ValueError as exc:
        raise ValueError(f"Unsupported JARVIS_AUTONOMY_MODE: {value!r}") from exc


def _configured_optional_text(
    name: str,
    machine_settings: Mapping[str, str],
) -> str | None:
    value = configured_text(name, machine_settings)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _configured_required_text(
    name: str,
    default: str,
    machine_settings: Mapping[str, str],
) -> str:
    value = configured_text(name, machine_settings, default)
    assert value is not None
    return value


@dataclass(frozen=True, slots=True)
class JarvisConfig:
    log_level: str = "INFO"
    ai_provider: str = "openai"
    chatgpt_plan_enabled: bool = False
    chatgpt_plan_model: str | None = None
    default_media_target: str | None = None
    tts_provider: str = "gemini"
    realtime_model: str = "gpt-realtime"
    realtime_voice: str = "marin"
    gemini_realtime_model: str = DEFAULT_GEMINI_REALTIME_MODEL
    gemini_realtime_voice: str = "Charon"
    gemini_tts_model: str = "gemini-3.8-flash-tts"
    tts_project_billing_isolation_verified: bool = False
    hands_planner_model: str | None = None
    autonomy_mode: AutonomyMode = AutonomyMode.SHADOW
    work_orchestration_enabled: bool = False
    work_orchestration_model: str | None = None
    development_engine_enabled: bool = False
    development_engine_model: str | None = None
    work_context_mode: str = "shadow"
    global_brain_router_mode: str = "shadow"
    jev_bounded_decisions_enabled: bool = False
    jev_benchmark_admitted: bool = False
    jev_benchmark_report_path: str | None = None
    jev_model: str = "jev-latest"
    jev_endpoint: str = "https://api.typesafe.ai/v1/systemone"
    jev_min_confidence: float = 0.0
    runtime_lane: RuntimeLane = RuntimeLane.PRODUCTION
    gicc_mode: GiccMode = GiccMode.OFF
    work_dbos_database_url: str | None = field(default=None, repr=False)
    work_global_concurrency: int = 4
    development_test_docker_image: str | None = None
    github_promotion_enabled: bool = False
    github_app_client_id: str | None = None
    github_app_installation_id: int | None = None
    github_repository_full_name: str | None = None
    github_app_secret_id: str | None = None
    github_base_branch: str = "main"
    github_workflow_file: str = "code-quality.yml"
    github_expected_ci_app_id: int | None = 15368
    visual_computer_use_enabled: bool = False
    show_transcript: bool = True
    startup_greeting_enabled: bool = True
    wake_model_path: str | None = None
    wake_threshold: float = 0.68
    wake_debounce_seconds: float = 2.0
    audio_input_device: str | None = None
    audio_output_device: str | None = None
    # Retained only as a compatibility field while ADR-010 historical code exists.
    # The production MediaDevices runtime does not consume this selector.
    audio_output_wasapi_device: str | None = None
    audio_ring_buffer_seconds: float = 2.5
    audio_pre_roll_seconds: float = 0.75
    wake_cooldown_seconds: float = 1.0
    initial_request_timeout_seconds: float = 8.0
    follow_up_timeout_seconds: float = 15.0
    max_utterance_seconds: float = 15.0
    live_context_recent_turns: int = 24
    memory_enabled: bool = False
    memory_candidate_extraction_enabled: bool = False
    memory_candidate_extraction_model: str | None = None
    memory_semantic_recall_model: str | None = None
    vision_enabled: bool = False
    vision_head_model_path: str | None = None
    vision_default_camera: str = "lenovo"
    vision_lenovo_device_index: int = 0
    vision_pocket3_device_index: int = 1
    speaker_shadow_enabled: bool = False
    active_speaker_shadow_enabled: bool = False
    active_speaker_model_path: str | None = None
    pocket3_native_tracking_enabled: bool = False
    pocket3_ble_name: str = "OsmoPocket3-C36F"
    pocket3_owner_evidence_max_age_seconds: float = 2.0
    pocket3_subject_push_stale_seconds: float = 1.25
    pocket3_lock_pending_timeout_seconds: float = 2.5
    pocket3_resend_cooldown_seconds: float = 1.0

    def __post_init__(self) -> None:
        normalized = str(self.log_level).strip().upper()
        if normalized not in VALID_LOG_LEVELS:
            raise ValueError(f"Unsupported JARVIS_LOG_LEVEL: {self.log_level!r}")
        object.__setattr__(self, "log_level", normalized)

        object.__setattr__(self, "ai_provider", normalize_ai_provider(self.ai_provider))
        object.__setattr__(
            self,
            "tts_provider",
            normalize_tts_provider(self.tts_provider),
        )

        if not isinstance(self.chatgpt_plan_enabled, bool):
            raise TypeError("chatgpt_plan_enabled must be a bool")
        if not isinstance(self.development_engine_enabled, bool):
            raise TypeError("development_engine_enabled must be a bool")
        if self.development_engine_enabled:
            if not self.chatgpt_plan_enabled:
                raise ValueError(
                    "DevelopmentEngine requires JARVIS_CHATGPT_PLAN_ENABLED=true"
                )
            development_model = str(
                self.development_engine_model or self.chatgpt_plan_model or ""
            ).strip()
            if not development_model:
                raise ValueError(
                    "DevelopmentEngine requires JARVIS_DEVELOPMENT_ENGINE_MODEL "
                    "or JARVIS_CHATGPT_PLAN_MODEL"
                )

        if not isinstance(self.tts_project_billing_isolation_verified, bool):
            raise TypeError("tts_project_billing_isolation_verified must be a bool")

        if not isinstance(self.autonomy_mode, AutonomyMode):
            raise TypeError("autonomy_mode must be an AutonomyMode")

        work_context_mode = str(self.work_context_mode).strip().casefold()
        if work_context_mode not in {"off", "shadow", "apply"}:
            raise ValueError("work_context_mode must be one of: off, shadow, apply")
        object.__setattr__(self, "work_context_mode", work_context_mode)

        brain_router_mode = str(self.global_brain_router_mode).strip().casefold()
        if brain_router_mode not in {"off", "shadow", "apply"}:
            raise ValueError(
                "global_brain_router_mode must be one of: off, shadow, apply"
            )
        object.__setattr__(
            self,
            "global_brain_router_mode",
            brain_router_mode,
        )

        if not isinstance(self.jev_bounded_decisions_enabled, bool):
            raise TypeError("jev_bounded_decisions_enabled must be a bool")
        if not isinstance(self.jev_benchmark_admitted, bool):
            raise TypeError("jev_benchmark_admitted must be a bool")
        jev_model = str(self.jev_model).strip()
        jev_endpoint = str(self.jev_endpoint).strip()
        if not jev_model:
            raise ValueError("jev_model must not be empty")
        if not jev_endpoint:
            raise ValueError("jev_endpoint must not be empty")
        if not 0.0 <= float(self.jev_min_confidence) <= 1.0:
            raise ValueError("jev_min_confidence must be between 0 and 1")
        if self.jev_bounded_decisions_enabled:
            if not self.jev_benchmark_admitted:
                raise ValueError(
                    "JEV bounded decisions require owner-machine benchmark admission"
                )
            if float(self.jev_min_confidence) <= 0.0:
                raise ValueError(
                    "JEV bounded decisions require a calibrated confidence threshold"
                )
            if not str(self.jev_benchmark_report_path or "").strip():
                raise ValueError(
                    "JEV bounded decisions require a benchmark report path"
                )
        object.__setattr__(self, "jev_model", jev_model)
        object.__setattr__(self, "jev_endpoint", jev_endpoint)
        object.__setattr__(self, "jev_min_confidence", float(self.jev_min_confidence))

        if not isinstance(self.runtime_lane, RuntimeLane):
            raise TypeError("runtime_lane must be RuntimeLane")
        if not isinstance(self.gicc_mode, GiccMode):
            raise TypeError("gicc_mode must be GiccMode")
        validate_gicc_runtime_policy(self.runtime_lane, self.gicc_mode)

        camera_source = str(self.vision_default_camera).strip().lower()
        if camera_source not in {"lenovo", "pocket3"}:
            raise ValueError(
                "vision_default_camera must be either 'lenovo' or 'pocket3'"
            )
        object.__setattr__(self, "vision_default_camera", camera_source)

        for name in ("vision_lenovo_device_index", "vision_pocket3_device_index"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")

        for name in (
            "realtime_model",
            "realtime_voice",
            "gemini_realtime_model",
            "gemini_realtime_voice",
            "gemini_tts_model",
            "pocket3_ble_name",
        ):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)

        for name in (
            "wake_model_path",
            "vision_head_model_path",
            "active_speaker_model_path",
            "memory_candidate_extraction_model",
            "memory_semantic_recall_model",
            "hands_planner_model",
            "chatgpt_plan_model",
            "default_media_target",
            "work_orchestration_model",
            "work_dbos_database_url",
            "development_test_docker_image",
            "github_app_client_id",
            "github_repository_full_name",
            "github_app_secret_id",
        ):
            value = getattr(self, name)
            if value is not None:
                normalized_value = str(value).strip()
                object.__setattr__(self, name, normalized_value or None)

        if self.chatgpt_plan_enabled and self.chatgpt_plan_model is None:
            raise ValueError(
                "JARVIS_CHATGPT_PLAN_MODEL is required when ChatGPT-plan usage is enabled"
            )

        if self.default_media_target is not None:
            if len(self.default_media_target) > 160:
                raise ValueError("default_media_target must be at most 160 characters")
            if any(ord(character) < 32 for character in self.default_media_target):
                raise ValueError(
                    "default_media_target must not contain control characters"
                )

        if self.work_orchestration_enabled:
            if self.work_dbos_database_url is None:
                raise ValueError(
                    "JARVIS_WORK_DBOS_DATABASE_URL is required when "
                    "work orchestration is enabled"
                )
            normalized_db_url = self.work_dbos_database_url.casefold()
            if not normalized_db_url.startswith(
                ("postgresql://", "postgres://", "postgresql+psycopg://")
            ):
                raise ValueError(
                    "JARVIS_WORK_DBOS_DATABASE_URL must use Postgres "
                    "for production orchestration"
                )

        for name in ("github_base_branch", "github_workflow_file"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, value)

        if self.github_promotion_enabled:
            if self.github_app_client_id is None:
                raise ValueError(
                    "JARVIS_GITHUB_APP_CLIENT_ID is required when GitHub promotion is enabled"
                )
            if (
                self.github_app_installation_id is None
                or isinstance(self.github_app_installation_id, bool)
                or self.github_app_installation_id <= 0
            ):
                raise ValueError(
                    "JARVIS_GITHUB_APP_INSTALLATION_ID must be positive when GitHub promotion is enabled"
                )
            if self.github_repository_full_name is None:
                raise ValueError(
                    "JARVIS_GITHUB_REPOSITORY is required when GitHub promotion is enabled"
                )
            if self.github_app_secret_id is None:
                raise ValueError(
                    "JARVIS_GITHUB_APP_SECRET_ID is required when GitHub promotion is enabled"
                )
        if self.github_expected_ci_app_id is not None and (
            isinstance(self.github_expected_ci_app_id, bool)
            or self.github_expected_ci_app_id <= 0
        ):
            raise ValueError("github_expected_ci_app_id must be positive")

        if isinstance(self.work_global_concurrency, bool) or not isinstance(
            self.work_global_concurrency, int
        ):
            raise TypeError("work_global_concurrency must be an integer")
        if self.work_global_concurrency <= 0:
            raise ValueError("work_global_concurrency must be greater than zero")

        if self.memory_candidate_extraction_enabled:
            if not self.memory_enabled:
                raise ValueError(
                    "JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED requires "
                    "JARVIS_MEMORY_ENABLED"
                )
            if self.memory_candidate_extraction_model is None:
                raise ValueError(
                    "JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL is required when "
                    "candidate extraction is enabled"
                )

        if self.memory_semantic_recall_model is not None and not self.memory_enabled:
            raise ValueError(
                "JARVIS_MEMORY_SEMANTIC_RECALL_MODEL requires JARVIS_MEMORY_ENABLED"
            )

        if self.pocket3_native_tracking_enabled and not self.vision_enabled:
            raise ValueError(
                "JARVIS_POCKET3_NATIVE_TRACKING_ENABLED requires JARVIS_VISION_ENABLED"
            )

        for name in (
            "audio_input_device",
            "audio_output_device",
            "audio_output_wasapi_device",
        ):
            value = getattr(self, name)
            if value is not None:
                normalized_value = str(value).strip()
                object.__setattr__(self, name, normalized_value or None)

        if not 0 < self.wake_threshold <= 1:
            raise ValueError("wake_threshold must be greater than 0 and at most 1")
        positive_values = (
            "wake_debounce_seconds",
            "audio_ring_buffer_seconds",
            "wake_cooldown_seconds",
            "initial_request_timeout_seconds",
            "follow_up_timeout_seconds",
            "max_utterance_seconds",
            "pocket3_owner_evidence_max_age_seconds",
            "pocket3_subject_push_stale_seconds",
            "pocket3_lock_pending_timeout_seconds",
            "pocket3_resend_cooldown_seconds",
        )
        for name in positive_values:
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if isinstance(self.live_context_recent_turns, bool) or not isinstance(
            self.live_context_recent_turns, int
        ):
            raise TypeError("live_context_recent_turns must be an integer")
        if self.live_context_recent_turns <= 0:
            raise ValueError("live_context_recent_turns must be greater than zero")
        if not math.isfinite(self.audio_pre_roll_seconds):
            raise ValueError("audio_pre_roll_seconds must be finite")
        if not 0 <= self.audio_pre_roll_seconds <= self.audio_ring_buffer_seconds:
            raise ValueError("audio pre-roll must fit inside the ring buffer")

    @property
    def memory_semantic_recall_enabled(self) -> bool:
        return self.memory_enabled and self.memory_semantic_recall_model is not None

    @property
    def realtime_provider(self) -> str:
        """Deprecated read-only alias for the single active cloud-AI provider."""

        return self.ai_provider

    @classmethod
    def from_environment(cls) -> JarvisConfig:
        """Load persisted machine settings, then apply environment overrides.

        The method name is retained for compatibility. Environment variables are
        intentionally higher priority only in explicit diagnostic override mode.
        """

        machine = load_machine_settings()
        runtime_lane = configured_runtime_lane()
        gicc_mode = configured_gicc_mode(runtime_lane)
        return cls(
            log_level=_configured_required_text("JARVIS_LOG_LEVEL", "INFO", machine),
            ai_provider=configured_ai_provider(machine),
            chatgpt_plan_enabled=_configured_bool(
                "JARVIS_CHATGPT_PLAN_ENABLED", False, machine
            ),
            chatgpt_plan_model=_configured_optional_text(
                "JARVIS_CHATGPT_PLAN_MODEL", machine
            ),
            default_media_target=_configured_optional_text(
                "JARVIS_DEFAULT_MEDIA_TARGET", machine
            ),
            tts_provider=configured_tts_provider(machine),
            realtime_model=_configured_required_text(
                "JARVIS_REALTIME_MODEL", "gpt-realtime", machine
            ),
            realtime_voice=_configured_required_text(
                "JARVIS_REALTIME_VOICE", "marin", machine
            ),
            gemini_realtime_model=_configured_required_text(
                "JARVIS_GEMINI_REALTIME_MODEL",
                DEFAULT_GEMINI_REALTIME_MODEL,
                machine,
            ),
            gemini_realtime_voice=_configured_required_text(
                "JARVIS_GEMINI_REALTIME_VOICE", "Charon", machine
            ),
            gemini_tts_model=_configured_required_text(
                "JARVIS_GEMINI_TTS_MODEL",
                "gemini-3.8-flash-tts",
                machine,
            ),
            tts_project_billing_isolation_verified=_configured_bool(
                "JARVIS_TTS_PROJECT_BILLING_ISOLATION_VERIFIED",
                False,
                machine,
            ),
            hands_planner_model=_configured_optional_text(
                "JARVIS_HANDS_PLANNER_MODEL", machine
            ),
            autonomy_mode=_configured_autonomy_mode(machine),
            work_orchestration_enabled=_configured_bool(
                "JARVIS_WORK_ORCHESTRATION_ENABLED", False, machine
            ),
            work_orchestration_model=_configured_optional_text(
                "JARVIS_WORK_ORCHESTRATION_MODEL", machine
            ),
            development_engine_enabled=_configured_bool(
                "JARVIS_DEVELOPMENT_ENGINE_ENABLED",
                False,
                machine,
            ),
            development_engine_model=_configured_optional_text(
                "JARVIS_DEVELOPMENT_ENGINE_MODEL",
                machine,
            ),
            work_context_mode=_configured_required_text(
                "JARVIS_WORK_CONTEXT_MODE",
                "shadow",
                machine,
            ),
            global_brain_router_mode=_configured_required_text(
                "JARVIS_GLOBAL_BRAIN_ROUTER_MODE",
                "shadow",
                machine,
            ),
            jev_bounded_decisions_enabled=_configured_bool(
                "JARVIS_JEV_BOUNDED_DECISIONS_ENABLED",
                False,
                machine,
            ),
            jev_benchmark_admitted=_configured_bool(
                "JARVIS_JEV_BENCHMARK_ADMITTED",
                False,
                machine,
            ),
            jev_benchmark_report_path=_configured_optional_text(
                "JARVIS_JEV_BENCHMARK_REPORT_PATH",
                machine,
            ),
            jev_model=_configured_required_text(
                "JARVIS_JEV_MODEL",
                "jev-latest",
                machine,
            ),
            jev_endpoint=_configured_required_text(
                "JARVIS_JEV_ENDPOINT",
                "https://api.typesafe.ai/v1/systemone",
                machine,
            ),
            jev_min_confidence=_configured_float(
                "JARVIS_JEV_MIN_CONFIDENCE",
                0.0,
                machine,
            ),
            runtime_lane=runtime_lane,
            gicc_mode=gicc_mode,
            work_dbos_database_url=_configured_optional_text(
                "JARVIS_WORK_DBOS_DATABASE_URL", machine
            ),
            work_global_concurrency=_configured_int(
                "JARVIS_WORK_GLOBAL_CONCURRENCY", 4, machine
            ),
            development_test_docker_image=_configured_optional_text(
                "JARVIS_DEV_TEST_DOCKER_IMAGE", machine
            ),
            github_promotion_enabled=_configured_bool(
                "JARVIS_GITHUB_PROMOTION_ENABLED", False, machine
            ),
            github_app_client_id=_configured_optional_text(
                "JARVIS_GITHUB_APP_CLIENT_ID", machine
            ),
            github_app_installation_id=(
                None
                if configured_text("JARVIS_GITHUB_APP_INSTALLATION_ID", machine) is None
                else _configured_int("JARVIS_GITHUB_APP_INSTALLATION_ID", 0, machine)
            ),
            github_repository_full_name=_configured_optional_text(
                "JARVIS_GITHUB_REPOSITORY", machine
            ),
            github_app_secret_id=_configured_optional_text(
                "JARVIS_GITHUB_APP_SECRET_ID", machine
            ),
            github_base_branch=_configured_required_text(
                "JARVIS_GITHUB_BASE_BRANCH", "main", machine
            ),
            github_workflow_file=_configured_required_text(
                "JARVIS_GITHUB_WORKFLOW_FILE", "code-quality.yml", machine
            ),
            github_expected_ci_app_id=(
                None
                if configured_text("JARVIS_GITHUB_EXPECTED_CI_APP_ID", machine)
                == "none"
                else _configured_int(
                    "JARVIS_GITHUB_EXPECTED_CI_APP_ID",
                    15368,
                    machine,
                )
            ),
            visual_computer_use_enabled=_configured_bool(
                "JARVIS_VISUAL_COMPUTER_USE_ENABLED", False, machine
            ),
            show_transcript=_configured_bool("JARVIS_SHOW_TRANSCRIPT", True, machine),
            startup_greeting_enabled=_configured_bool(
                "JARVIS_STARTUP_GREETING", True, machine
            ),
            wake_model_path=_configured_optional_text(
                "JARVIS_WAKE_MODEL_PATH", machine
            ),
            wake_threshold=_configured_float("JARVIS_WAKE_THRESHOLD", 0.68, machine),
            wake_debounce_seconds=_configured_float(
                "JARVIS_WAKE_DEBOUNCE_SECONDS", 2.0, machine
            ),
            audio_input_device=_configured_optional_text(
                "JARVIS_AUDIO_INPUT_DEVICE", machine
            ),
            audio_output_device=_configured_optional_text(
                "JARVIS_AUDIO_OUTPUT_DEVICE", machine
            ),
            audio_output_wasapi_device=_configured_optional_text(
                "JARVIS_AUDIO_OUTPUT_WASAPI_DEVICE", machine
            ),
            audio_ring_buffer_seconds=_configured_float(
                "JARVIS_AUDIO_RING_BUFFER_SECONDS", 2.5, machine
            ),
            audio_pre_roll_seconds=_configured_float(
                "JARVIS_AUDIO_PRE_ROLL_SECONDS", 0.75, machine
            ),
            wake_cooldown_seconds=_configured_float(
                "JARVIS_WAKE_COOLDOWN_SECONDS", 1.0, machine
            ),
            initial_request_timeout_seconds=_configured_float(
                "JARVIS_INITIAL_REQUEST_TIMEOUT_SECONDS", 8.0, machine
            ),
            follow_up_timeout_seconds=_configured_float(
                "JARVIS_FOLLOW_UP_TIMEOUT_SECONDS", 15.0, machine
            ),
            max_utterance_seconds=_configured_float(
                "JARVIS_MAX_UTTERANCE_SECONDS", 15.0, machine
            ),
            live_context_recent_turns=_configured_int(
                "JARVIS_LIVE_CONTEXT_RECENT_TURNS", 24, machine
            ),
            memory_enabled=_configured_bool("JARVIS_MEMORY_ENABLED", False, machine),
            memory_candidate_extraction_enabled=_configured_bool(
                "JARVIS_MEMORY_CANDIDATE_EXTRACTION_ENABLED", False, machine
            ),
            memory_candidate_extraction_model=_configured_optional_text(
                "JARVIS_MEMORY_CANDIDATE_EXTRACTION_MODEL", machine
            ),
            memory_semantic_recall_model=_configured_optional_text(
                "JARVIS_MEMORY_SEMANTIC_RECALL_MODEL", machine
            ),
            vision_enabled=_configured_bool("JARVIS_VISION_ENABLED", False, machine),
            vision_head_model_path=_configured_optional_text(
                "JARVIS_BLAZEFACE_MODEL_PATH", machine
            ),
            vision_default_camera=_configured_required_text(
                "JARVIS_VISION_DEFAULT_CAMERA", "lenovo", machine
            ),
            vision_lenovo_device_index=_configured_int(
                "JARVIS_VISION_LENOVO_DEVICE_INDEX", 0, machine
            ),
            vision_pocket3_device_index=_configured_int(
                "JARVIS_VISION_POCKET3_DEVICE_INDEX", 1, machine
            ),
            speaker_shadow_enabled=_configured_bool(
                "JARVIS_SPEAKER_SHADOW_ENABLED", False, machine
            ),
            active_speaker_shadow_enabled=_configured_bool(
                "JARVIS_ACTIVE_SPEAKER_SHADOW_ENABLED", False, machine
            ),
            active_speaker_model_path=_configured_optional_text(
                "JARVIS_LR_ASD_MODEL_PATH", machine
            ),
            pocket3_native_tracking_enabled=_configured_bool(
                "JARVIS_POCKET3_NATIVE_TRACKING_ENABLED", False, machine
            ),
            pocket3_ble_name=_configured_required_text(
                "JARVIS_POCKET3_BLE_NAME", "OsmoPocket3-C36F", machine
            ),
            pocket3_owner_evidence_max_age_seconds=_configured_float(
                "JARVIS_POCKET3_OWNER_EVIDENCE_MAX_AGE_SECONDS", 2.0, machine
            ),
            pocket3_subject_push_stale_seconds=_configured_float(
                "JARVIS_POCKET3_SUBJECT_PUSH_STALE_SECONDS", 1.25, machine
            ),
            pocket3_lock_pending_timeout_seconds=_configured_float(
                "JARVIS_POCKET3_LOCK_PENDING_TIMEOUT_SECONDS", 2.5, machine
            ),
            pocket3_resend_cooldown_seconds=_configured_float(
                "JARVIS_POCKET3_RESEND_COOLDOWN_SECONDS", 1.0, machine
            ),
        )
