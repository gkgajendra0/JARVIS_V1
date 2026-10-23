"""Reviewed, versioned prices/FX and conservative bounded inference exposure."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType

from jarvis.model_routing.models import CostProfile, ModelTarget


class PricingUnavailable(ValueError):
    pass


def _decimal(value) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PricingUnavailable("Price/FX is unavailable") from None
    if not result.is_finite() or result < 0:
        raise PricingUnavailable("Price/FX is not finite and nonnegative")
    return result


def _epoch(value) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise PricingUnavailable("Invalid effective time")
    return float(value)


@dataclass(frozen=True, slots=True)
class PaidExposure:
    usage_bounds: Mapping[str, int]
    scope_kind: str
    scope_id: str
    max_seconds: float | None = None

    def __post_init__(self):
        if (
            self.scope_kind not in {"work", "voice", "hands", "memory"}
            or not isinstance(self.scope_id, str)
            or not self.scope_id.strip()
        ):
            raise PricingUnavailable("Invalid paid exposure scope")
        values = dict(self.usage_bounds)
        if not values or any(
            not isinstance(k, str) or type(v) is not int or v < 0
            for k, v in values.items()
        ):
            raise PricingUnavailable("Invalid paid usage bounds")
        if not any(k.startswith("output_") and v > 0 for k, v in values.items()):
            raise PricingUnavailable("Paid output bound required")
        if self.max_seconds is not None and _epoch(self.max_seconds) <= 0:
            raise PricingUnavailable("Paid duration bound required")
        object.__setattr__(self, "usage_bounds", MappingProxyType(values))

    def to_payload(self):
        return {
            "usage_bounds": dict(self.usage_bounds),
            "scope_kind": self.scope_kind,
            "scope_id": self.scope_id,
            "max_seconds": self.max_seconds,
        }


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    profile: CostProfile
    model_id: str
    service_key: str
    source: str
    inr_per_usd: Decimal
    fx_source: str
    fx_version: str
    fx_effective_from_epoch: float
    fx_effective_to_epoch: float
    margin_bps: int = 0

    def __post_init__(self):
        if not isinstance(self.profile, CostProfile):
            raise PricingUnavailable("CostProfile required")
        for key in ("model_id", "source", "fx_source", "fx_version"):
            if (
                not isinstance(getattr(self, key), str)
                or not getattr(self, key).strip()
            ):
                raise PricingUnavailable("Price/FX identity is unavailable")
        if self.service_key not in {"structured", "live"}:
            raise PricingUnavailable("Unsupported priced service")
        rate = _decimal(self.inr_per_usd)
        if rate <= 0:
            raise PricingUnavailable("Positive FX required")
        object.__setattr__(self, "inr_per_usd", rate)
        if _epoch(self.fx_effective_to_epoch) <= _epoch(self.fx_effective_from_epoch):
            raise PricingUnavailable("Invalid FX effective interval")
        if type(self.margin_bps) is not int or not 0 <= self.margin_bps <= 10000:
            raise PricingUnavailable("Invalid price margin")

    def validate_at(self, now_epoch):
        now = _epoch(now_epoch)
        if (
            self.profile.effective_to_epoch is None
            or not self.profile.effective_from_epoch
            <= now
            < self.profile.effective_to_epoch
        ):
            raise PricingUnavailable(
                "Price profile is missing an effective interval or expired"
            )
        if not self.fx_effective_from_epoch <= now < self.fx_effective_to_epoch:
            raise PricingUnavailable("FX profile expired")

    def rates(self):
        if self.profile.usage_rates_usd_per_million:
            rates = dict(self.profile.usage_rates_usd_per_million)
            if (
                self.service_key == "structured"
                and not {"input_tokens", "output_tokens"} <= rates.keys()
            ):
                raise PricingUnavailable(
                    "Complete structured input/output prices required"
                )
            return rates
        if self.service_key == "live":
            raise PricingUnavailable("Live modality prices required")
        return {
            "input_tokens": self.profile.input_usd_per_million_tokens,
            "output_tokens": self.profile.output_usd_per_million_tokens,
        }

    def quote(
        self, usage: Mapping[str, int], *, now_epoch: float, target: ModelTarget
    ) -> int:
        self.validate_at(now_epoch)
        if target.provider_id != "gemini" or target.model_id != self.model_id:
            raise PricingUnavailable("Price model does not match target")
        if target.cost_profile is not None and target.cost_profile != self.profile:
            raise PricingUnavailable("Target price/version does not match snapshot")
        return self.quote_usage(usage, now_epoch=now_epoch)

    def quote_usage(self, usage: Mapping[str, int], *, now_epoch: float) -> int:
        """Price observed units using an already pinned admission snapshot."""
        self.validate_at(now_epoch)
        rates = self.rates()
        if not rates.keys() <= usage.keys():
            raise PricingUnavailable("Incomplete usage dimensions")
        if any(
            k not in rates
            and k not in {"total_tokens", "input_tokens", "output_tokens"}
            for k in usage
        ):
            raise PricingUnavailable("Unpriced usage dimension")
        usd = Decimal(0)
        for key, rate in rates.items():
            count = usage[key]
            if type(count) is not int or count < 0 or rate is None:
                raise PricingUnavailable("Unknown price or usage")
            usd += Decimal(count) * _decimal(rate) / Decimal(1000000)
        inr_minor = (
            usd
            * self.inr_per_usd
            * 100
            * (Decimal(1) + Decimal(self.margin_bps) / 10000)
        )
        return int(inr_minor.to_integral_value(rounding=ROUND_CEILING))

    def to_payload(self):
        value = asdict(self)
        value["schema_version"] = 1
        value["inr_per_usd"] = str(self.inr_per_usd)
        return value

    @classmethod
    def from_payload(cls, payload):
        try:
            value = dict(payload)
            if (
                type(value.pop("schema_version")) is not int
                or payload["schema_version"] != 1
            ):
                raise PricingUnavailable("Unsupported pricing schema")
            value["profile"] = CostProfile(**value["profile"])
            return cls(**value)
        except (KeyError, TypeError, ValueError) as exc:
            raise PricingUnavailable("Invalid pricing snapshot") from exc


def load_pricing_snapshot(path: Path, *, now_epoch: float) -> PricingSnapshot:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshot = PricingSnapshot.from_payload(payload)
        snapshot.validate_at(now_epoch)
        return snapshot
    except (OSError, ValueError, TypeError) as exc:
        raise PricingUnavailable("Reviewed pricing snapshot unavailable") from exc
