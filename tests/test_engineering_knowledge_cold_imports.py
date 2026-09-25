from __future__ import annotations

import multiprocessing


def _import_target(module_name: str, result_queue) -> None:
    __import__(module_name)
    result_queue.put("ok")


def _assert_fresh_import(module_name: str) -> None:
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_import_target,
        args=(module_name, result_queue),
    )
    process.start()
    process.join(timeout=30)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        raise AssertionError(f"cold import timed out: {module_name}")
    assert process.exitcode == 0
    result = result_queue.get(timeout=5)
    assert result == "ok"


def test_engineering_knowledge_acceptance_cold_import_has_no_cycle() -> None:
    _assert_fresh_import("jarvis.engineering_knowledge.acceptance")


def test_engineering_knowledge_package_cold_import_has_no_cycle() -> None:
    _assert_fresh_import("jarvis.engineering_knowledge")
