"""Optional local prompt compression for model-facing Work payloads.

Canonical JARVIS state is never modified. This module preserves the JSON structure and
all non-compressible leaves byte-for-value while applying LLMLingua-2 only to long
natural-language evidence fields.
"""

from __future__ import annotations

import copy
import importlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

DEFAULT_LLMLINGUA2_MODEL = (
    "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank"
)
DEFAULT_LLMLINGUA2_REVISION = "5f0c827"
REVIEWED_LLMLINGUA_LIBRARY_REVISION = (
    "5a4c78ae18ab17a98cf997e8259354e546081d64"
)
DEFAULT_COMPRESSION_RATE = 0.5
DEFAULT_MIN_STRING_CHARS = 600

# These keys are deliberately semantic prose fields. Source/code payloads such as
# "text", diffs, schemas, IDs, digests, requests and tool parameters remain untouched.
_DEFAULT_COMPRESSIBLE_KEYS = frozenset(
    {
        "summary",
        "content",
        "body",
        "rationale",
        "description",
    }
)
_PROTECTED_ROOT_KEYS = frozenset({"work", "purpose", "allowed_actions"})


class PromptCompressionMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    APPLY = "apply"


def normalize_prompt_compression_mode(
    value: PromptCompressionMode | str,
) -> PromptCompressionMode:
    if isinstance(value, PromptCompressionMode):
        return value
    try:
        return PromptCompressionMode(str(value).strip().casefold())
    except ValueError as exc:
        raise ValueError(
            "prompt compression mode must be off, shadow, or apply"
        ) from exc


class PromptCompressionError(RuntimeError):
    """Local prompt compression failed validation and must not be used."""


class PromptCompressionDependencyError(PromptCompressionError):
    """The optional LLMLingua runtime is not installed or cannot be loaded."""


class LLMLinguaEngine(Protocol):
    def compress_prompt(self, context: list[str], **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class PromptCompressionResult:
    payload: dict[str, Any]
    provider: str
    model: str
    rate: float
    candidate_strings: int
    compressed_strings: int
    original_chars: int
    compressed_chars: int
    estimated_original_tokens: int
    estimated_compressed_tokens: int
    llmlingua_origin_tokens: int | None
    llmlingua_compressed_tokens: int | None
    latency_ms: float
    changed_paths: tuple[str, ...]

    @property
    def reduced(self) -> bool:
        return (
            self.compressed_strings > 0
            and self.compressed_chars < self.original_chars
            and self.estimated_compressed_tokens < self.estimated_original_tokens
        )

    @property
    def reduction_percent(self) -> float:
        if self.original_chars <= 0:
            return 0.0
        return round(
            (self.original_chars - self.compressed_chars) * 100.0 / self.original_chars,
            2,
        )


class WorkPayloadCompressor(Protocol):
    def compress_payload(self, payload: dict[str, Any]) -> PromptCompressionResult: ...


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: tuple[str | int, ...]
    value: str


def _serialized_chars(payload: dict[str, Any]) -> int:
    return len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
    )


def _estimated_tokens(chars: int) -> int:
    return max(1, (int(chars) + 3) // 4)


def _path_text(path: tuple[str | int, ...]) -> str:
    parts: list[str] = []
    for item in path:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        elif not parts:
            parts.append(item)
        else:
            parts.append(f".{item}")
    return "".join(parts)


def _path_is_protected(path: tuple[str | int, ...]) -> bool:
    return bool(path) and isinstance(path[0], str) and path[0] in _PROTECTED_ROOT_KEYS


def _collect_candidates(
    value: Any,
    *,
    path: tuple[str | int, ...],
    min_string_chars: int,
    compressible_keys: frozenset[str],
    output: list[_Candidate],
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = (*path, str(key))
            if (
                isinstance(item, str)
                and str(key) in compressible_keys
                and len(item) >= min_string_chars
                and not _path_is_protected(child)
            ):
                output.append(_Candidate(path=child, value=item))
            else:
                _collect_candidates(
                    item,
                    path=child,
                    min_string_chars=min_string_chars,
                    compressible_keys=compressible_keys,
                    output=output,
                )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _collect_candidates(
                item,
                path=(*path, index),
                min_string_chars=min_string_chars,
                compressible_keys=compressible_keys,
                output=output,
            )


def _set_path(payload: Any, path: tuple[str | int, ...], value: str) -> None:
    current = payload
    for item in path[:-1]:
        current = current[item]
    current[path[-1]] = value


def _validate_structure(
    original: Any,
    compressed: Any,
    *,
    path: tuple[str | int, ...] = (),
    changed_paths: frozenset[tuple[str | int, ...]],
) -> None:
    if type(original) is not type(compressed):
        raise PromptCompressionError(
            f"compression changed value type at {_path_text(path) or '<root>'}"
        )
    if isinstance(original, dict):
        if tuple(original.keys()) != tuple(compressed.keys()):
            raise PromptCompressionError(
                f"compression changed object keys at {_path_text(path) or '<root>'}"
            )
        for key in original:
            _validate_structure(
                original[key],
                compressed[key],
                path=(*path, str(key)),
                changed_paths=changed_paths,
            )
        return
    if isinstance(original, list):
        if len(original) != len(compressed):
            raise PromptCompressionError(
                f"compression changed list length at {_path_text(path) or '<root>'}"
            )
        for index, item in enumerate(original):
            _validate_structure(
                item,
                compressed[index],
                path=(*path, index),
                changed_paths=changed_paths,
            )
        return
    if path in changed_paths:
        if not isinstance(original, str) or not isinstance(compressed, str):
            raise PromptCompressionError(
                f"only string leaves may be compressed at {_path_text(path)}"
            )
        if not compressed.strip():
            raise PromptCompressionError(
                f"compressor returned an empty semantic field at {_path_text(path)}"
            )
        return
    if original != compressed:
        raise PromptCompressionError(
            f"compression changed protected value at {_path_text(path)}"
        )


class LLMLingua2WorkPayloadCompressor:
    """Structure-preserving LLMLingua-2 adapter for Work provider payloads."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_LLMLINGUA2_MODEL,
        rate: float = DEFAULT_COMPRESSION_RATE,
        min_string_chars: int = DEFAULT_MIN_STRING_CHARS,
        device_map: str = "cpu",
        engine_factory: Callable[[], LLMLinguaEngine] | None = None,
        compressible_keys: frozenset[str] = _DEFAULT_COMPRESSIBLE_KEYS,
    ) -> None:
        normalized_model = str(model_name).strip()
        normalized_device = str(device_map).strip()
        if not normalized_model:
            raise ValueError("LLMLingua model_name must not be empty")
        if not 0.0 < float(rate) <= 1.0:
            raise ValueError("LLMLingua compression rate must be within (0, 1]")
        if int(min_string_chars) < 200:
            raise ValueError("min_string_chars must be at least 200")
        if not normalized_device:
            raise ValueError("device_map must not be empty")
        if not compressible_keys:
            raise ValueError("compressible_keys must not be empty")

        self._model_name = normalized_model
        self._rate = float(rate)
        self._min_string_chars = int(min_string_chars)
        self._device_map = normalized_device
        self._engine_factory = engine_factory
        self._compressible_keys = frozenset(str(item) for item in compressible_keys)
        self._engine: LLMLinguaEngine | None = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def device_map(self) -> str:
        return self._device_map

    def _build_engine(self) -> LLMLinguaEngine:
        if self._engine_factory is not None:
            return self._engine_factory()
        try:
            module = importlib.import_module("llmlingua")
            compressor_type = module.PromptCompressor
        except (ImportError, AttributeError) as exc:
            raise PromptCompressionDependencyError(
                "LLMLingua is unavailable. Install the optional "
                "JARVIS context-compression dependencies first."
            ) from exc

        try:
            return compressor_type(
                model_name=self._model_name,
                use_llmlingua2=True,
                device_map=self._device_map,
                model_config={
                    "revision": DEFAULT_LLMLINGUA2_REVISION,
                    "trust_remote_code": False,
                },
            )
        except Exception as exc:
            raise PromptCompressionDependencyError(
                "LLMLingua-2 could not initialize with the configured local model"
            ) from exc

    def _require_engine(self) -> LLMLinguaEngine:
        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    def compress_payload(self, payload: dict[str, Any]) -> PromptCompressionResult:
        if not isinstance(payload, dict):
            raise TypeError("Work provider payload must be an object")

        original = copy.deepcopy(payload)
        compressed = copy.deepcopy(payload)
        candidates: list[_Candidate] = []
        _collect_candidates(
            original,
            path=(),
            min_string_chars=self._min_string_chars,
            compressible_keys=self._compressible_keys,
            output=candidates,
        )

        original_chars = _serialized_chars(original)
        if not candidates:
            return PromptCompressionResult(
                payload=compressed,
                provider="llmlingua2",
                model=self._model_name,
                rate=self._rate,
                candidate_strings=0,
                compressed_strings=0,
                original_chars=original_chars,
                compressed_chars=original_chars,
                estimated_original_tokens=_estimated_tokens(original_chars),
                estimated_compressed_tokens=_estimated_tokens(original_chars),
                llmlingua_origin_tokens=None,
                llmlingua_compressed_tokens=None,
                latency_ms=0.0,
                changed_paths=(),
            )

        engine = self._require_engine()
        started = time.perf_counter()
        try:
            raw = engine.compress_prompt(
                [item.value for item in candidates],
                rate=self._rate,
                use_context_level_filter=False,
                use_token_level_filter=True,
                force_reserve_digit=True,
                force_tokens=["\n"],
            )
        except Exception as exc:
            raise PromptCompressionError("LLMLingua-2 compression failed") from exc
        latency_ms = (time.perf_counter() - started) * 1000.0

        outputs = raw.get("compressed_prompt_list")
        if not isinstance(outputs, list) or len(outputs) != len(candidates):
            raise PromptCompressionError(
                "LLMLingua-2 returned an unexpected compressed_prompt_list shape"
            )

        changed: list[tuple[str | int, ...]] = []
        for candidate, replacement in zip(candidates, outputs, strict=True):
            if not isinstance(replacement, str) or not replacement.strip():
                raise PromptCompressionError(
                    "LLMLingua-2 returned an invalid compressed string"
                )
            # A compressor that makes a field larger provides no benefit. Keep the
            # canonical model-facing value for that leaf instead.
            if len(replacement) >= len(candidate.value):
                continue
            _set_path(compressed, candidate.path, replacement)
            changed.append(candidate.path)

        _validate_structure(
            original,
            compressed,
            changed_paths=frozenset(changed),
        )
        compressed_chars = _serialized_chars(compressed)
        return PromptCompressionResult(
            payload=compressed,
            provider="llmlingua2",
            model=self._model_name,
            rate=self._rate,
            candidate_strings=len(candidates),
            compressed_strings=len(changed),
            original_chars=original_chars,
            compressed_chars=compressed_chars,
            estimated_original_tokens=_estimated_tokens(original_chars),
            estimated_compressed_tokens=_estimated_tokens(compressed_chars),
            llmlingua_origin_tokens=(
                int(raw["origin_tokens"])
                if isinstance(raw.get("origin_tokens"), int)
                and not isinstance(raw.get("origin_tokens"), bool)
                else None
            ),
            llmlingua_compressed_tokens=(
                int(raw["compressed_tokens"])
                if isinstance(raw.get("compressed_tokens"), int)
                and not isinstance(raw.get("compressed_tokens"), bool)
                else None
            ),
            latency_ms=latency_ms,
            changed_paths=tuple(_path_text(path) for path in changed),
        )


__all__ = [
    "DEFAULT_LLMLINGUA2_MODEL",
    "DEFAULT_LLMLINGUA2_REVISION",
    "LLMLingua2WorkPayloadCompressor",
    "REVIEWED_LLMLINGUA_LIBRARY_REVISION",
    "PromptCompressionMode",
    "PromptCompressionDependencyError",
    "PromptCompressionError",
    "PromptCompressionResult",
    "WorkPayloadCompressor",
    "normalize_prompt_compression_mode",
]
