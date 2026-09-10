"""Generic installed-application discovery for JARVIS Hands on Windows."""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

_APPS_FOLDER = "shell:::{4234d49b-0245-4df3-b780-3893943456e1}"
_MAX_APP_NAME = 160
_MAX_CATALOG_ITEMS = 2_000


class AppCatalogError(RuntimeError):
    """Raised when the bounded installed-app catalogue cannot resolve a target."""


@dataclass(frozen=True, slots=True)
class InstalledApp:
    """One Windows Start/AppsFolder application identity."""

    display_name: str
    app_id: str
    source: str = "windows_apps_folder"

    @property
    def ui_target(self) -> str:
        """Human-readable target suitable for winapp fuzzy app matching."""

        return self.display_name

    def payload(self) -> dict[str, str]:
        return {
            "display_name": self.display_name,
            "app_id": self.app_id,
            "source": self.source,
            "ui_target": self.ui_target,
        }


class AppCatalog(Protocol):
    def entries(self) -> tuple[InstalledApp, ...]: ...

    def resolve(self, query: str) -> InstalledApp: ...

    def launch(self, app: InstalledApp) -> None: ...


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())


def _bounded_query(value: str) -> str:
    query = " ".join(str(value).split())
    if not query or len(query) > _MAX_APP_NAME:
        raise ValueError("application name must be a non-empty bounded string")
    return query


def _score(query: str, app: InstalledApp) -> int:
    needle = _normalized(query)
    name = _normalized(app.display_name)
    if not needle or not name:
        return -1
    if name == needle:
        return 1_000
    if name.startswith(f"{needle} ") or needle.startswith(f"{name} "):
        return 850
    query_tokens = tuple(needle.split())
    name_tokens = set(name.split())
    if query_tokens and all(token in name_tokens for token in query_tokens):
        return 700
    if needle in name:
        return 600
    return -1


class WindowsAppsFolderCatalog:
    """Discover and launch Start-menu apps through the Windows Shell AppsFolder.

    The model never supplies an executable, path, shell command, verb, or arguments.
    JARVIS resolves a user-facing app name against Windows-owned Shell items, then
    invokes only that resolved item's default verb.
    """

    def __init__(self, *, dispatch: Callable[[str], Any] | None = None) -> None:
        self._dispatch = dispatch

    def _shell(self):
        if platform.system() != "Windows" and self._dispatch is None:
            raise AppCatalogError("Windows installed-app discovery requires Windows")
        if self._dispatch is not None:
            return self._dispatch("Shell.Application")
        try:
            from win32com.client import Dispatch
        except ImportError as exc:
            raise AppCatalogError(
                "installed-app discovery requires the jarvis[windows-hands] extra"
            ) from exc
        return Dispatch("Shell.Application")

    def _folder(self):
        shell = self._shell()
        folder = shell.NameSpace(_APPS_FOLDER)
        if folder is None:
            raise AppCatalogError("Windows AppsFolder is unavailable")
        return folder

    @staticmethod
    def _collection_items(collection: Any) -> tuple[Any, ...]:
        count = int(getattr(collection, "Count", 0) or 0)
        if count < 0 or count > _MAX_CATALOG_ITEMS:
            raise AppCatalogError("Windows AppsFolder returned an invalid item count")
        return tuple(collection.Item(index) for index in range(count))

    def entries(self) -> tuple[InstalledApp, ...]:
        try:
            items = self._collection_items(self._folder().Items())
        except AppCatalogError:
            raise
        except Exception as exc:  # COM failures surface through pywin32-specific types.
            raise AppCatalogError(f"Windows AppsFolder enumeration failed: {exc}") from exc

        discovered: dict[tuple[str, str], InstalledApp] = {}
        for item in items:
            display_name = " ".join(str(getattr(item, "Name", "") or "").split())
            app_id = str(getattr(item, "Path", "") or "").strip()
            if not display_name or not app_id:
                continue
            app = InstalledApp(display_name=display_name, app_id=app_id)
            discovered[(_normalized(display_name), app_id.casefold())] = app
        return tuple(
            sorted(discovered.values(), key=lambda item: item.display_name.casefold())
        )

    def resolve(self, query: str) -> InstalledApp:
        bounded = _bounded_query(query)
        ranked = sorted(
            ((score, app) for app in self.entries() if (score := _score(bounded, app)) >= 0),
            key=lambda pair: (-pair[0], pair[1].display_name.casefold()),
        )
        if not ranked:
            raise AppCatalogError(f"installed application was not found: {bounded}")
        best_score = ranked[0][0]
        best = tuple(app for score, app in ranked if score == best_score)
        if len(best) != 1:
            names = ", ".join(item.display_name for item in best[:5])
            raise AppCatalogError(
                f"installed application name is ambiguous: {bounded}; matches={names}"
            )
        return best[0]

    def launch(self, app: InstalledApp) -> None:
        if not isinstance(app, InstalledApp):
            raise TypeError("app must be an InstalledApp resolved by the catalogue")
        try:
            items = self._collection_items(self._folder().Items())
            for item in items:
                item_path = str(getattr(item, "Path", "") or "").strip()
                item_name = " ".join(str(getattr(item, "Name", "") or "").split())
                if item_path == app.app_id and _normalized(item_name) == _normalized(
                    app.display_name
                ):
                    item.InvokeVerb()
                    return
        except AppCatalogError:
            raise
        except Exception as exc:
            raise AppCatalogError(
                f"Windows AppsFolder launch failed for {app.display_name}: {exc}"
            ) from exc
        raise AppCatalogError(
            f"resolved application disappeared before launch: {app.display_name}"
        )
