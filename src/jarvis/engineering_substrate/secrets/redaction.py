"""In-memory exact-value redaction for trusted secret-bearing adapter output."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SecretRedactor:
    """Redact exact secret values before trusted adapter output reaches logs/evidence."""

    _values: list[str] = field(default_factory=list, repr=False)
    replacement: str = "[REDACTED_SECRET]"

    @classmethod
    def from_values(
        cls,
        values: tuple[str | bytes, ...],
        *,
        replacement: str = "[REDACTED_SECRET]",
    ) -> SecretRedactor:
        normalized: list[str] = []
        for value in values:
            if isinstance(value, bytes):
                try:
                    text = value.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError(
                        "secret redaction values must be valid UTF-8"
                    ) from exc
            elif isinstance(value, str):
                text = value
            else:
                raise TypeError("secret redaction values must be str or bytes")
            if not text:
                raise ValueError("secret redaction values must not be empty")
            if text not in normalized:
                normalized.append(text)
        normalized.sort(key=len, reverse=True)
        marker = str(replacement)
        if not marker:
            raise ValueError("redaction replacement must not be empty")
        return cls(_values=normalized, replacement=marker)

    def redact_text(self, value: str) -> str:
        result = str(value)
        for secret in self._values:
            result = result.replace(secret, self.replacement)
        return result

    def redact_bytes(self, value: bytes) -> bytes:
        if not isinstance(value, bytes):
            raise TypeError("redact_bytes requires bytes")
        result = value
        replacement = self.replacement.encode("utf-8")
        for secret in self._values:
            result = result.replace(secret.encode("utf-8"), replacement)
        return result

    def clear(self) -> None:
        for index in range(len(self._values)):
            self._values[index] = ""
        self._values.clear()
