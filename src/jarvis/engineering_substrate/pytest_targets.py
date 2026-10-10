"""Shared executable-target validation for acquisition and development tickets."""

from __future__ import annotations

import pathlib


def normalize_pytest_targets(values: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize relative paths/node selectors without accepting pytest options."""
    targets: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            raise ValueError("verification_target must not be empty")
        path, separator, selector = text.partition("::")
        if any(character.isspace() for character in path) or "\x00" in text:
            raise ValueError("verification_target must be a repository-relative path")
        path = path.replace("\\", "/")
        posix = pathlib.PurePosixPath(path)
        windows = pathlib.PureWindowsPath(path)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or bool(windows.root)
            or ".." in posix.parts
            or path.startswith("-")
            or posix.as_posix() in {"", "."}
        ):
            raise ValueError(
                "verification_target must be a safe repository-relative path"
            )
        if separator and (not selector or "\n" in selector or "\r" in selector):
            raise ValueError("verification_target has an invalid pytest selector")
        targets.append(posix.as_posix() + (separator + selector if separator else ""))
    if len(set(targets)) != len(targets):
        raise ValueError("verification_target values must be unique")
    return tuple(sorted(targets))
