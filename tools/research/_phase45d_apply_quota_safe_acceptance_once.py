"""One-time patch helper for the quota-safe Phase 4.5D final acceptance transport."""

from __future__ import annotations

from pathlib import Path

HARNESS = Path("tools/research/step4_phase45d_final_composite_acceptance.py")
TESTS = Path("tests/test_phase45d_final_composite_acceptance.py")
METHOD = Path("docs/research/STEP_4_PHASE_4_5D_FINAL_COMPOSITE_ACCEPTANCE_METHOD.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one {label} marker, found {text.count(old)}")
    return text.replace(old, new, 1)


def patch_harness() -> None:
    text = HARNESS.read_text(encoding="utf-8")

    text = replace_once(text, "import itertools\nimport json\nimport re\nimport sqlite3\nimport tempfile\nimport time\n", "import itertools\nimport json\nimport math\nimport sqlite3\nimport subprocess\nimport tempfile\nimport time\n", "stdlib imports")
    text = replace_once(text, "from jarvis.memory.query_interpreters import build_memory_query_interpreter\n", "from jarvis.ai_provider import require_provider_api_key\nfrom jarvis.memory.query_interpreters import GeminiMemoryQueryInterpreter\n", "query interpreter import")

    text = replace_once(
        text,
        'DEFAULT_GEMINI_RPM = 12.0\nGEMINI_MAX_ATTEMPTS = 5\nOUTPUT_DEFAULT = Path(".step4-phase45d-final-composite-acceptance.json")\n',
        'DEFAULT_GEMINI_RPM = 12.0\nOUTPUT_DEFAULT = Path(".step4-phase45d-final-composite-acceptance.json")\nCHECKPOINT_DEFAULT = Path(".step4-phase45d-final-composite-acceptance.checkpoint.json")\nCHECKPOINT_SCHEMA_VERSION = 1\nMIN_QUOTA_RESERVE = 25\nQUOTA_RESERVE_FRACTION = 0.10\n',
        "quota constants",
    )

    retry_start = text.index("def _retry_after_seconds(message: str) -> float | None:\n")
    guard_start = text.index("class RecordingAnswerTypeGuard:", retry_start)
    replacement = '''class ProviderCallBudgetExceeded(RuntimeError):
    """Raised before a provider call would exceed the certified invocation budget."""


class PacedMemoryQueryInterpreter:
    """Single-attempt, rate-limited wrapper around the production provider adapter."""

    def __init__(self, delegate: Any, *, rpm: float, max_calls: int) -> None:
        if not callable(getattr(delegate, "interpret", None)):
            raise TypeError("delegate must implement memory query interpretation")
        if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls < 0:
            raise ValueError("max_calls must be a non-negative integer")
        self._delegate = delegate
        self._pacer = GeminiRequestPacer(rpm)
        self._max_calls = max_calls
        self.logical_calls = 0
        self.api_attempts = 0
        self.last_proposal: MemoryQueryProposal | None = None
        self.last_attempts = 0

    @property
    def provider_name(self) -> str:
        return str(self._delegate.provider_name)

    @property
    def model_name(self) -> str:
        return str(self._delegate.model_name)

    def reset_case(self) -> None:
        self.last_proposal = None
        self.last_attempts = 0

    async def interpret(
        self,
        *,
        text: str,
        catalog: MemoryFacetCatalog,
    ) -> MemoryQueryProposal:
        if self.logical_calls >= self._max_calls:
            raise ProviderCallBudgetExceeded(
                "certified Gemini provider-call budget exhausted before request"
            )
        await self._pacer.wait()
        self.logical_calls += 1
        self.api_attempts += 1
        proposal = await self._delegate.interpret(text=text, catalog=catalog)
        self.last_proposal = proposal
        self.last_attempts = 1
        return proposal


def _build_acceptance_gemini_interpreter() -> GeminiMemoryQueryInterpreter:
    """Build the frozen Gemini adapter with SDK retries disabled for acceptance."""

    from google import genai
    from google.genai import types

    api_key = require_provider_api_key(
        "gemini",
        purpose="Phase 4.5D final composite acceptance",
    )
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=0),
        ),
    )
    return GeminiMemoryQueryInterpreter(client=client, model=GEMINI_MODEL_ID)


def _quota_reserve(active_limit: int) -> int:
    if not isinstance(active_limit, int) or isinstance(active_limit, bool):
        raise TypeError("active RPD limit must be an integer")
    if active_limit <= 0:
        raise ValueError("active RPD limit must be positive")
    return max(MIN_QUOTA_RESERVE, math.ceil(active_limit * QUOTA_RESERVE_FRACTION))


def _quota_budget(
    *,
    active_limit: int,
    active_usage: int,
    required_provider_calls: int,
) -> dict[str, int | bool]:
    if not isinstance(active_usage, int) or isinstance(active_usage, bool):
        raise TypeError("active RPD usage must be an integer")
    if active_usage < 0:
        raise ValueError("active RPD usage must be non-negative")
    if active_usage > active_limit:
        raise ValueError("active RPD usage cannot exceed active RPD limit")
    if not isinstance(required_provider_calls, int) or isinstance(
        required_provider_calls, bool
    ):
        raise TypeError("required_provider_calls must be an integer")
    if required_provider_calls < 0:
        raise ValueError("required_provider_calls must be non-negative")
    reserve = _quota_reserve(active_limit)
    remaining = active_limit - active_usage
    minimum_remaining = required_provider_calls + reserve
    return {
        "active_limit_rpd": active_limit,
        "active_usage_rpd": active_usage,
        "remaining_rpd": remaining,
        "required_provider_calls": required_provider_calls,
        "reserve_rpd": reserve,
        "minimum_remaining_rpd": minimum_remaining,
        "sufficient": remaining >= minimum_remaining,
    }


def _repository_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _checkpoint_contract(repository_sha: str) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "repository_sha": repository_sha,
        "corpus_sha256": FROZEN_CORPUS_SHA256,
        "provider_model": GEMINI_MODEL_ID,
        "answer_type_model": ANSWER_TYPE_MODEL_ID,
        "answer_type_revision": ANSWER_TYPE_MODEL_REVISION,
    }


def _checkpoint_payload(
    *,
    repository_sha: str,
    results: list[AcceptanceCaseResult],
) -> dict[str, Any]:
    return {
        "contract": _checkpoint_contract(repository_sha),
        "completed_cases": [_public_case(row) for row in results],
    }


def _write_checkpoint(
    path: Path,
    *,
    repository_sha: str,
    results: list[AcceptanceCaseResult],
) -> None:
    payload = _checkpoint_payload(repository_sha=repository_sha, results=results)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_checkpoint(path: Path, *, repository_sha: str) -> list[AcceptanceCaseResult]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract") != _checkpoint_contract(repository_sha):
        raise RuntimeError("acceptance checkpoint contract does not match current run")
    raw_rows = payload.get("completed_cases")
    if not isinstance(raw_rows, list):
        raise RuntimeError("acceptance checkpoint completed_cases is invalid")
    rows = [AcceptanceCaseResult(**row) for row in raw_rows]
    case_ids = [row.case_id for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("acceptance checkpoint contains duplicate case IDs")
    return rows


'''
    text = text[:retry_start] + replacement + text[guard_start:]

    marker = "def _public_case(result: AcceptanceCaseResult) -> dict[str, Any]:\n"
    quota_plan_code = '''async def _plan_provider_calls(
    *,
    device: str,
    completed_case_ids: set[str],
) -> dict[str, int]:
    """Count cloud planner calls using only the frozen local guard, never labels."""

    payload = cases.build_payload()
    corpus_sha = cases.payload_sha256(payload)
    if corpus_sha != FROZEN_CORPUS_SHA256:
        raise RuntimeError(
            f"fresh corpus hash mismatch: {corpus_sha} != {FROZEN_CORPUS_SHA256}"
        )
    queries = payload.get("queries")
    if not isinstance(queries, list) or len(queries) != cases.TOTAL_CASES:
        raise RuntimeError("fresh acceptance query payload changed")

    guard = LocalZeroShotMemoryAnswerTypeGuard(device=device)
    remaining_cases = 0
    required_provider_calls = 0
    for item in queries:
        case_id = str(item["case_id"])
        if case_id in completed_case_ids:
            continue
        remaining_cases += 1
        decision = await guard.evaluate(str(item["query"]))
        if decision.allow:
            required_provider_calls += 1
    return {
        "remaining_cases": remaining_cases,
        "required_provider_calls": required_provider_calls,
    }


'''
    text = replace_once(text, marker, quota_plan_code + marker, "quota plan insertion")

    text = replace_once(
        text,
        "async def _run(*, device: str, gemini_rpm: float) -> dict[str, Any]:\n",
        "async def _run(\n    *,\n    device: str,\n    gemini_rpm: float,\n    provider_budget: int,\n    checkpoint_path: Path,\n    repository_sha: str,\n    checkpoint_results: list[AcceptanceCaseResult],\n    quota_budget: dict[str, int | bool],\n) -> dict[str, Any]:\n",
        "run signature",
    )

    text = replace_once(
        text,
        "            delegate_interpreter = build_memory_query_interpreter(\n                provider=\"gemini\",\n                model=GEMINI_MODEL_ID,\n            )\n            interpreter = PacedMemoryQueryInterpreter(\n                delegate_interpreter,\n                rpm=gemini_rpm,\n            )\n",
        "            delegate_interpreter = _build_acceptance_gemini_interpreter()\n            interpreter = PacedMemoryQueryInterpreter(\n                delegate_interpreter,\n                rpm=gemini_rpm,\n                max_calls=provider_budget,\n            )\n",
        "interpreter construction",
    )

    text = replace_once(
        text,
        "            results: list[AcceptanceCaseResult] = []\n            for index, item in enumerate(queries, start=1):\n",
        "            results: list[AcceptanceCaseResult] = list(checkpoint_results)\n            completed_case_ids = {row.case_id for row in results}\n            _write_checkpoint(\n                checkpoint_path,\n                repository_sha=repository_sha,\n                results=results,\n            )\n            for index, item in enumerate(queries, start=1):\n                if str(item[\"case_id\"]) in completed_case_ids:\n                    continue\n",
        "resume loop",
    )

    text = replace_once(
        text,
        "                results.append(result)\n                print(\n",
        "                results.append(result)\n                completed_case_ids.add(result.case_id)\n                _write_checkpoint(\n                    checkpoint_path,\n                    repository_sha=repository_sha,\n                    results=results,\n                )\n                print(\n",
        "checkpoint write",
    )

    text = replace_once(
        text,
        "    summary = _summarize(results, provider_calls=interpreter.logical_calls)\n",
        "    if len(results) != cases.TOTAL_CASES:\n        raise RuntimeError(\n            f\"acceptance ended without all cases: {len(results)} != {cases.TOTAL_CASES}\"\n        )\n    total_provider_calls = sum(1 for row in results if row.provider_called)\n    total_provider_attempts = sum(row.provider_attempts for row in results)\n    summary = _summarize(results, provider_calls=total_provider_calls)\n    summary[\"provider_api_attempts\"] = total_provider_attempts\n    summary[\"provider_attempts_equal_logical_calls\"] = (\n        total_provider_attempts == total_provider_calls\n    )\n    summary[\"continuation_checks\"][\"provider_attempts_equal_logical_calls\"] = (\n        total_provider_attempts == total_provider_calls\n    )\n    summary[\"acceptance_passed\"] = all(summary[\"continuation_checks\"].values())\n",
        "summary provider accounting",
    )

    text = replace_once(
        text,
        '        "statistical_contract": {\n',
        '        "quota_execution_contract": {\n            **quota_budget,\n            "sdk_retries": 0,\n            "harness_retries": 0,\n            "checkpoint_resume_enabled": True,\n            "checkpoint_persists_query_text": False,\n            "checkpoint_persists_canonical_memory_value": False,\n        },\n        "statistical_contract": {\n',
        "quota contract artifact",
    )

    old_parse = '''def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--gemini-rpm", type=float, default=DEFAULT_GEMINI_RPM)
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.gemini_rpm <= 0:
        raise ValueError("Gemini RPM must be positive")
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite fresh acceptance evidence: {output_path}"
        )

    result = asyncio.run(
        _run(
            device=str(args.device),
            gemini_rpm=float(args.gemini_rpm),
        )
    )
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", result["status"])
    print("SUMMARY:", json.dumps(result["summary"], ensure_ascii=False))
    print(
        "DECISION:",
        json.dumps(
            {
                "phase45d": result["phase45d"],
                "phase45e_authorized": False,
            }
        ),
    )
'''
    new_parse = '''def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--gemini-rpm", type=float, default=DEFAULT_GEMINI_RPM)
    parser.add_argument("--quota-plan-only", action="store_true")
    parser.add_argument("--quota-limit-rpd", type=int)
    parser.add_argument("--quota-used-rpd", type=int)
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    parser.add_argument("--checkpoint", default=str(CHECKPOINT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.gemini_rpm <= 0:
        raise ValueError("Gemini RPM must be positive")
    output_path = Path(args.output)
    checkpoint_path = Path(args.checkpoint)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite fresh acceptance evidence: {output_path}"
        )

    repository_sha = _repository_sha()
    checkpoint_results = _load_checkpoint(
        checkpoint_path,
        repository_sha=repository_sha,
    )
    completed_case_ids = {row.case_id for row in checkpoint_results}
    quota_plan = asyncio.run(
        _plan_provider_calls(
            device=str(args.device),
            completed_case_ids=completed_case_ids,
        )
    )
    print("QUOTA_PLAN:", json.dumps(quota_plan, ensure_ascii=False))

    if args.quota_plan_only:
        if args.quota_limit_rpd is not None and args.quota_used_rpd is not None:
            budget = _quota_budget(
                active_limit=int(args.quota_limit_rpd),
                active_usage=int(args.quota_used_rpd),
                required_provider_calls=int(quota_plan["required_provider_calls"]),
            )
            print("QUOTA_BUDGET:", json.dumps(budget, ensure_ascii=False))
        return

    if args.quota_limit_rpd is None or args.quota_used_rpd is None:
        raise RuntimeError(
            "acceptance requires current --quota-limit-rpd and --quota-used-rpd "
            "from Google AI Studio"
        )
    budget = _quota_budget(
        active_limit=int(args.quota_limit_rpd),
        active_usage=int(args.quota_used_rpd),
        required_provider_calls=int(quota_plan["required_provider_calls"]),
    )
    print("QUOTA_BUDGET:", json.dumps(budget, ensure_ascii=False))
    if not bool(budget["sufficient"]):
        raise RuntimeError(
            "insufficient certified Gemini RPD budget; refusing to start provider calls"
        )

    try:
        result = asyncio.run(
            _run(
                device=str(args.device),
                gemini_rpm=float(args.gemini_rpm),
                provider_budget=int(quota_plan["required_provider_calls"]),
                checkpoint_path=checkpoint_path,
                repository_sha=repository_sha,
                checkpoint_results=checkpoint_results,
                quota_budget=budget,
            )
        )
    except Exception as exc:
        print("STATUS: EXECUTION_PAUSED_PROVIDER")
        print(
            "RESUME:",
            json.dumps(
                {
                    "checkpoint": str(checkpoint_path),
                    "repository_sha": repository_sha,
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
            ),
        )
        raise

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\\n",
        encoding="utf-8",
    )
    checkpoint_path.unlink(missing_ok=True)
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", result["status"])
    print("SUMMARY:", json.dumps(result["summary"], ensure_ascii=False))
    print(
        "DECISION:",
        json.dumps(
            {
                "phase45d": result["phase45d"],
                "phase45e_authorized": False,
            }
        ),
    )
'''
    text = replace_once(text, old_parse, new_parse, "CLI/main")

    HARNESS.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    text += '''


def test_quota_reserve_uses_ten_percent_with_minimum_floor() -> None:
    assert harness._quota_reserve(500) == 50
    assert harness._quota_reserve(200) == 25


def test_quota_budget_refuses_insufficient_headroom() -> None:
    safe = harness._quota_budget(
        active_limit=500,
        active_usage=200,
        required_provider_calls=200,
    )
    assert safe["remaining_rpd"] == 300
    assert safe["reserve_rpd"] == 50
    assert safe["sufficient"] is True

    unsafe = harness._quota_budget(
        active_limit=500,
        active_usage=300,
        required_provider_calls=160,
    )
    assert unsafe["remaining_rpd"] == 200
    assert unsafe["minimum_remaining_rpd"] == 210
    assert unsafe["sufficient"] is False


def test_checkpoint_round_trip_is_contract_bound_and_query_free(tmp_path) -> None:
    rows = _perfect_results()[:2]
    checkpoint = tmp_path / "checkpoint.json"
    harness._write_checkpoint(
        checkpoint,
        repository_sha="abc123",
        results=rows,
    )

    raw = checkpoint.read_text(encoding="utf-8")
    assert "user_query" not in raw
    assert "canonical_memory_value" not in raw
    assert harness._load_checkpoint(
        checkpoint,
        repository_sha="abc123",
    ) == rows

    try:
        harness._load_checkpoint(checkpoint, repository_sha="different")
    except RuntimeError as exc:
        assert "checkpoint contract" in str(exc)
    else:
        raise AssertionError("checkpoint must be bound to the exact repository SHA")


class _OneShotDelegate:
    provider_name = "gemini"
    model_name = "gemini-3.5-flash-lite"

    def __init__(self) -> None:
        self.calls = 0

    async def interpret(self, *, text, catalog):
        self.calls += 1
        raise RuntimeError("429 quota exceeded")


def test_paced_interpreter_never_adds_its_own_retry() -> None:
    import asyncio

    delegate = _OneShotDelegate()
    interpreter = harness.PacedMemoryQueryInterpreter(delegate, rpm=60, max_calls=1)
    catalog = harness.MemoryFacetCatalog(facets=())
    try:
        asyncio.run(interpreter.interpret(text="test", catalog=catalog))
    except RuntimeError as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("delegate failure should propagate")

    assert delegate.calls == 1
    assert interpreter.logical_calls == 1
    assert interpreter.api_attempts == 1


def test_second_provider_call_is_blocked_before_delegate() -> None:
    import asyncio

    class Delegate:
        provider_name = "gemini"
        model_name = "gemini-3.5-flash-lite"

        def __init__(self) -> None:
            self.calls = 0

        async def interpret(self, *, text, catalog):
            self.calls += 1
            return harness.MemoryQueryProposal(intent="unsupported")

    delegate = Delegate()
    interpreter = harness.PacedMemoryQueryInterpreter(delegate, rpm=60, max_calls=1)
    catalog = harness.MemoryFacetCatalog(facets=())
    asyncio.run(interpreter.interpret(text="one", catalog=catalog))
    try:
        asyncio.run(interpreter.interpret(text="two", catalog=catalog))
    except harness.ProviderCallBudgetExceeded:
        pass
    else:
        raise AssertionError("second provider call must be blocked by certified budget")

    assert delegate.calls == 1
'''
    TESTS.write_text(text, encoding="utf-8")


def patch_method() -> None:
    text = METHOD.read_text(encoding="utf-8")
    appendix = '''

## Quota-safe transport amendment — 2026-09-07

The first owner execution ended in provider quota failure before a complete artifact. Per the already-frozen rule above, that is execution failure rather than model-quality evidence. A research-backed transport amendment is therefore frozen before any complete final result exists.

Durable research:

- `docs/research/STEP_4_PHASE_4_5D_GEMINI_FREE_TIER_QUOTA_RESEARCH.md`.

The semantic/statistical acceptance contract above is unchanged. Execution now additionally requires:

1. a local-only answer-type-guard planning pass that counts exactly how many **remaining** queries can reach Gemini, without consulting expected labels;
2. current active RPD limit and usage copied from Google AI Studio for the same project/model;
3. remaining RPD >= required planner calls + `max(25, 10% of active RPD limit)` safety reserve before the first Gemini request;
4. pinned `google-genai==2.22.0` configured with `HttpRetryOptions(attempts=0)` for acceptance so the SDK cannot amplify retries;
5. no JARVIS retry loop around the provider call;
6. exactly one API attempt per logical provider call;
7. an atomic, exact-SHA-bound checkpoint after each completed case so provider transport interruption resumes without repeating completed cases;
8. checkpoint persistence contains no query text and no canonical memory value;
9. Batch API remains excluded from final acceptance because the frozen acceptance validates the production-shaped one-query-per-Interactions-request path.

Changing transport safety in this way does not tune the corpus, semantic models, prompt/schema, memory policy, or acceptance gates and therefore does not convert the preserved fresh corpus into development data.
'''
    if "## Quota-safe transport amendment — 2026-09-07" not in text:
        text += appendix
    METHOD.write_text(text, encoding="utf-8")


def main() -> None:
    patch_harness()
    patch_tests()
    patch_method()


if __name__ == "__main__":
    main()
