"""Zero-cloud owner-machine acceptance for C3 Global Brain Router.

This acceptance intentionally does not construct Gemini/OpenAI adapters and does not
open the production Work database. It exercises the real WorkEngine + BrainCoordinator
+ GlobalBrainRouterReasoner against an isolated temporary SQLite store. The model
reasoner raises if touched, proving that the accepted deterministic route bypasses
model reasoning.

With --apply, the machine profile is changed to JARVIS_GLOBAL_BRAIN_ROUTER_MODE=apply
only after every zero-cloud acceptance assertion passes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from jarvis.brain_routing.deterministic import default_work_deterministic_resolvers
from jarvis.brain_routing.store import BrainRouteStore
from jarvis.brain_routing.work import GlobalBrainRouterReasoner
from jarvis.machine_config import (
    configured_text,
    default_machine_config_path,
    load_machine_settings,
    runtime_environment_overrides_enabled,
    save_machine_settings,
)
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.work.brain import BrainAction, BrainCoordinator, BrainRequest
from jarvis.work.engine import WorkActionRegistry, WorkEngine
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore

_SETTING = "JARVIS_GLOBAL_BRAIN_ROUTER_MODE"


class _ForbiddenModelReasoner:
    """Acceptance sentinel: touching the model path is a hard failure."""

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, request: BrainRequest):
        del request
        self.calls += 1
        raise AssertionError("C3 acceptance unexpectedly invoked model reasoning")


class _PrepareWorkspaceExecutor:
    descriptor = BrainAction(
        name="dev_prepare_workspace",
        description="Prepare an isolated development workspace.",
        parameter_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict,
    ) -> dict[str, object]:
        del work
        if parameters != {}:
            raise AssertionError(
                f"deterministic acceptance parameters were not empty: {parameters!r}"
            )
        self.calls += 1
        return {
            "prepared": True,
            "verified": True,
            "acceptance_fixture": "c3-owner-zero-cloud",
        }


def _assert_equal(actual, expected, *, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


async def _run_zero_cloud_acceptance(root: Path) -> dict[str, object]:
    store_path = root / "c3-owner-acceptance.sqlite3"
    work_store = SQLiteWorkStore(store_path)
    model_store = ModelRoutingStore(work_store)
    route_store = BrainRouteStore(work_store)
    model_reasoner = _ForbiddenModelReasoner()
    executor = _PrepareWorkspaceExecutor()

    router = GlobalBrainRouterReasoner(
        model_reasoner,
        work_store=work_store,
        route_store=route_store,
        model_routing_store=model_store,
        resolvers=default_work_deterministic_resolvers(),
        mode="apply",
    )
    engine = WorkEngine(
        store=work_store,
        brain=BrainCoordinator(router),
        actions=WorkActionRegistry((executor,)),
    )
    work = WorkItem(
        request="C3 owner acceptance: prepare the isolated development workspace.",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="c3-owner-acceptance",
        source_turn_id="zero-cloud",
    )
    work_store.create(work)

    result = await engine.advance(work.work_id)
    steps = work_store.list_steps(work.work_id)
    routes = route_store.list_for_work(work.work_id)
    route_summary = route_store.summary_for_work(work.work_id)
    model_attempts = model_store.list_attempts_for_work(work.work_id)

    _assert_equal(result.progressed, True, label="work progressed")
    _assert_equal(executor.calls, 1, label="executor call count")
    _assert_equal(model_reasoner.calls, 0, label="model reasoner call count")
    _assert_equal(len(model_attempts), 0, label="model routing attempt count")
    _assert_equal(len(steps), 1, label="work step count")
    _assert_equal(steps[0].kind, "dev_prepare_workspace", label="executed action")
    _assert_equal(
        steps[0].observation.get("prepared"),
        True,
        label="workspace observation",
    )
    _assert_equal(len(routes), 1, label="brain route record count")
    _assert_equal(
        routes[0].route_kind.value,
        "deterministic",
        label="route kind",
    )
    _assert_equal(
        routes[0].outcome_code,
        "model_bypassed",
        label="route outcome",
    )
    _assert_equal(
        routes[0].resolver_id,
        "work.development.initial_workspace",
        label="resolver id",
    )
    _assert_equal(
        route_summary["model_calls_avoided"],
        1,
        label="model calls avoided",
    )

    return {
        "temporary_store": str(store_path),
        "work_id": work.work_id,
        "executed_action": steps[0].kind,
        "route_kind": routes[0].route_kind.value,
        "resolver_id": routes[0].resolver_id,
        "model_reasoner_calls": model_reasoner.calls,
        "model_routing_attempts": len(model_attempts),
        "model_calls_avoided": route_summary["model_calls_avoided"],
        "status": "PASS",
    }


def _machine_status() -> dict[str, object]:
    path = default_machine_config_path()
    settings = load_machine_settings(path)
    persisted = settings.get(_SETTING)
    resolved = configured_text(_SETTING, settings, "shadow")
    return {
        "path": str(path),
        "persisted": persisted,
        "resolved": resolved,
        "environment_overrides_enabled": runtime_environment_overrides_enabled(),
    }


def _persist_apply_mode() -> dict[str, object]:
    path = default_machine_config_path()
    settings = load_machine_settings(path)
    previous = settings.get(_SETTING)
    settings[_SETTING] = "apply"
    save_machine_settings(settings, path)

    reloaded = load_machine_settings(path)
    persisted = reloaded.get(_SETTING)
    resolved = configured_text(_SETTING, reloaded, "shadow")
    _assert_equal(persisted, "apply", label="persisted C3 router mode")
    if resolved != "apply":
        raise RuntimeError(
            "C3 machine setting was persisted as apply but does not resolve to apply. "
            "JARVIS_RUNTIME_ENV_OVERRIDES is enabled and an environment override is "
            "taking precedence; disable/correct that override before production use."
        )

    return {
        "path": str(path),
        "previous": previous,
        "persisted": persisted,
        "resolved": resolved,
        "environment_overrides_enabled": runtime_environment_overrides_enabled(),
    }


async def _run(*, apply_machine_setting: bool) -> dict[str, object]:
    before = _machine_status()
    with tempfile.TemporaryDirectory(prefix="jarvis-c3-owner-acceptance-") as temp:
        acceptance = await _run_zero_cloud_acceptance(Path(temp))

    machine = before
    if apply_machine_setting:
        machine = _persist_apply_mode()

    return {
        "acceptance": acceptance,
        "machine_before": before,
        "machine_after": machine,
        "production_database_touched": False,
        "cloud_provider_called": False,
        "status": "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run zero-cloud C3 owner acceptance and optionally enable apply mode."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "persist JARVIS_GLOBAL_BRAIN_ROUTER_MODE=apply only after acceptance passes"
        ),
    )
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(_run(apply_machine_setting=args.apply))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - owner acceptance must report boundary
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
