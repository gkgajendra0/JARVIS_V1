"""C4/C5 bounded-decision benchmark for JARVIS.

The same frozen corpus can be evaluated with:
- abstain: deterministic/code-only semantic baseline (no fuzzy decision);
- ollama: local structured-output model through localhost;
- jev: TypeSafe System One Choice questions.

This tool is research scaffolding. It never grants Authority, executes JARVIS actions,
or mutates production routing state.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CASES = Path(__file__).with_name("c4_c5_benchmark_cases.json")
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    name: str
    instructions: str
    choices: dict[str, str]
    expected: str
    order: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("question name must not be empty")
        if not self.instructions.strip():
            raise ValueError(f"{self.name}: instructions must not be empty")
        if len(self.choices) < 2:
            raise ValueError(f"{self.name}: at least two choices are required")
        if self.expected not in self.choices:
            raise ValueError(f"{self.name}: expected answer is not a choice")
        if self.order:
            if set(self.order) != set(self.choices):
                raise ValueError(
                    f"{self.name}: order must contain every choice exactly once"
                )


@dataclass(frozen=True, slots=True)
class CaseSpec:
    case_id: str
    state: str
    questions: tuple[QuestionSpec, ...]

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case id must not be empty")
        if not self.state.strip():
            raise ValueError(f"{self.case_id}: state must not be empty")
        if not self.questions:
            raise ValueError(f"{self.case_id}: questions must not be empty")


@dataclass(frozen=True, slots=True)
class Prediction:
    value: str
    confidence: float | None = None
    probabilities: dict[str, float] | None = None


@dataclass(frozen=True, slots=True)
class RunnerResult:
    predictions: dict[str, Prediction]
    latency_ms: float
    usage: dict[str, int]
    model: str
    api_cost_usd: float | None
    raw_metadata: dict[str, Any]


class BenchmarkRunner:
    name: str

    def run(self, case: CaseSpec) -> RunnerResult:
        raise NotImplementedError


def _load_cases(path: Path) -> tuple[str, tuple[CaseSpec, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported benchmark corpus schema_version")
    suite = str(payload.get("suite", "")).strip()
    if not suite:
        raise ValueError("benchmark suite name is missing")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("benchmark cases are missing")

    cases: list[CaseSpec] = []
    seen: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise TypeError("benchmark case must be an object")
        case_id = str(raw_case.get("id", "")).strip()
        if case_id in seen:
            raise ValueError(f"duplicate benchmark case id: {case_id}")
        seen.add(case_id)
        raw_questions = raw_case.get("questions")
        if not isinstance(raw_questions, dict):
            raise TypeError(f"{case_id}: questions must be an object")
        questions: list[QuestionSpec] = []
        for name, raw_question in raw_questions.items():
            if not isinstance(raw_question, dict):
                raise TypeError(f"{case_id}/{name}: question must be an object")
            choices_raw = raw_question.get("choices")
            if not isinstance(choices_raw, dict):
                raise TypeError(f"{case_id}/{name}: choices must be an object")
            choices = {
                str(key).strip(): str(value).strip()
                for key, value in choices_raw.items()
            }
            order_raw = raw_question.get("order") or ()
            if not isinstance(order_raw, (list, tuple)):
                raise TypeError(f"{case_id}/{name}: order must be a list")
            questions.append(
                QuestionSpec(
                    name=str(name).strip(),
                    instructions=str(raw_question.get("instructions", "")).strip(),
                    choices=choices,
                    expected=str(raw_question.get("expected", "")).strip(),
                    order=tuple(str(item).strip() for item in order_raw),
                )
            )
        cases.append(
            CaseSpec(
                case_id=case_id,
                state=str(raw_case.get("state", "")).strip(),
                questions=tuple(questions),
            )
        )
    return suite, tuple(cases)


def _json_request(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float,
) -> tuple[dict[str, Any], float]:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail[:2000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Unable to reach {url}: {exc.reason}") from exc
    latency_ms = (time.perf_counter() - started) * 1000.0
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TypeError(f"Unexpected non-object response from {url}")
    return parsed, latency_ms


class AbstainRunner(BenchmarkRunner):
    name = "abstain"

    def run(self, case: CaseSpec) -> RunnerResult:
        return RunnerResult(
            predictions={
                question.name: Prediction("abstain") for question in case.questions
            },
            latency_ms=0.0,
            usage={},
            model="deterministic-no-semantic-decision",
            api_cost_usd=0.0,
            raw_metadata={"semantic_decision_invoked": False},
        )


class OllamaRunner(BenchmarkRunner):
    name = "ollama"

    def __init__(
        self,
        *,
        host: str,
        model: str,
        num_ctx: int,
        timeout: float,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model.strip()
        self.num_ctx = int(num_ctx)
        self.timeout = float(timeout)
        if not self.model:
            raise ValueError("Ollama model must not be empty")
        if self.num_ctx <= 0:
            raise ValueError("Ollama num_ctx must be positive")

    @staticmethod
    def _response_schema(case: CaseSpec) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for question in case.questions:
            properties[question.name] = {
                "type": "string",
                "enum": [*question.choices.keys(), "abstain"],
            }
        return {
            "type": "object",
            "properties": {
                "answers": {
                    "type": "object",
                    "properties": properties,
                    "required": [question.name for question in case.questions],
                    "additionalProperties": False,
                }
            },
            "required": ["answers"],
            "additionalProperties": False,
        }

    @staticmethod
    def _prompt_payload(case: CaseSpec) -> dict[str, Any]:
        return {
            "state": case.state,
            "questions": {
                question.name: {
                    "instructions": question.instructions,
                    "choices": question.choices,
                    "abstain": (
                        "Use abstain only when supplied state is genuinely insufficient "
                        "to choose among the listed options."
                    ),
                }
                for question in case.questions
            },
        }

    def run(self, case: CaseSpec) -> RunnerResult:
        schema = self._response_schema(case)
        response, latency_ms = _json_request(
            f"{self.host}/api/chat",
            {
                "model": self.model,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a bounded routing classifier inside JARVIS. "
                            "Hard policy, Authority, privacy and deterministic rules have "
                            "already run. Choose only among each question's supplied "
                            "choices or abstain. Do not execute actions, invent options, "
                            "or add prose."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            self._prompt_payload(case),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    },
                ],
                "format": schema,
                "options": {
                    "temperature": 0,
                    "num_ctx": self.num_ctx,
                },
            },
            timeout=self.timeout,
        )
        message = response.get("message")
        if not isinstance(message, dict):
            raise TypeError("Ollama response is missing message object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama response contains no structured content")
        decoded = json.loads(content)
        answers = decoded.get("answers") if isinstance(decoded, dict) else None
        if not isinstance(answers, dict):
            raise ValueError("Ollama structured response is missing answers")

        predictions: dict[str, Prediction] = {}
        for question in case.questions:
            value = str(answers.get(question.name, "")).strip()
            allowed = {*question.choices.keys(), "abstain"}
            if value not in allowed:
                raise ValueError(
                    f"Ollama returned unsupported answer for {question.name}: {value!r}"
                )
            predictions[question.name] = Prediction(value)

        usage: dict[str, int] = {}
        for source, target in (
            ("prompt_eval_count", "input_tokens"),
            ("eval_count", "output_tokens"),
        ):
            raw = response.get(source)
            if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
                usage[target] = raw
        if "input_tokens" in usage or "output_tokens" in usage:
            usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get(
                "output_tokens", 0
            )

        metadata: dict[str, Any] = {}
        for key in (
            "done_reason",
            "total_duration",
            "load_duration",
            "prompt_eval_duration",
            "eval_duration",
        ):
            if key in response:
                metadata[key] = response[key]

        return RunnerResult(
            predictions=predictions,
            latency_ms=latency_ms,
            usage=usage,
            model=self.model,
            api_cost_usd=0.0,
            raw_metadata=metadata,
        )


class JevRunner(BenchmarkRunner):
    name = "jev"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        api_key: str,
        timeout: float,
        input_usd_per_million: float | None,
    ) -> None:
        self.endpoint = endpoint
        self.model = model.strip()
        self.api_key = api_key.strip()
        self.timeout = float(timeout)
        self.input_usd_per_million = input_usd_per_million
        if not self.model:
            raise ValueError("Jev model must not be empty")
        if not self.api_key:
            raise ValueError("Jev API key must not be empty")
        if input_usd_per_million is not None and input_usd_per_million < 0:
            raise ValueError("Jev input price must not be negative")

    def run(self, case: CaseSpec) -> RunnerResult:
        questions = {
            question.name: {
                "type": "choice",
                "instructions": question.instructions,
                "criteria": question.choices,
            }
            for question in case.questions
        }
        response, latency_ms = _json_request(
            self.endpoint,
            {
                "state": case.state,
                "model": self.model,
                "questions": questions,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        )
        raw_answers = response.get("answers")
        if not isinstance(raw_answers, dict):
            raise TypeError("Jev response is missing answers object")
        predictions: dict[str, Prediction] = {}
        for question in case.questions:
            answer = raw_answers.get(question.name)
            if not isinstance(answer, dict) or answer.get("type") != "choice":
                raise TypeError(
                    f"Jev response missing Choice answer for {question.name}"
                )
            value = str(answer.get("choice", "")).strip()
            if value not in question.choices:
                raise ValueError(
                    f"Jev returned unsupported answer for {question.name}: {value!r}"
                )
            confidence_raw = answer.get("confidence")
            confidence = (
                float(confidence_raw)
                if isinstance(confidence_raw, (int, float))
                and not isinstance(confidence_raw, bool)
                else None
            )
            probabilities_raw = answer.get("probabilities")
            probabilities = None
            if isinstance(probabilities_raw, dict):
                probabilities = {
                    str(key): float(value)
                    for key, value in probabilities_raw.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
            predictions[question.name] = Prediction(
                value=value,
                confidence=confidence,
                probabilities=probabilities,
            )

        usage_raw = response.get("usage")
        usage: dict[str, int] = {}
        if isinstance(usage_raw, dict):
            for source, target in (
                ("input_tokens", "input_tokens"),
                ("output_tokens", "output_tokens"),
            ):
                raw = usage_raw.get(source)
                if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
                    usage[target] = raw
        if "input_tokens" in usage or "output_tokens" in usage:
            usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get(
                "output_tokens", 0
            )

        cost = None
        if self.input_usd_per_million is not None and "input_tokens" in usage:
            cost = (usage["input_tokens"] / 1_000_000.0) * self.input_usd_per_million

        return RunnerResult(
            predictions=predictions,
            latency_ms=latency_ms,
            usage=usage,
            model=str(response.get("model") or self.model),
            api_cost_usd=cost,
            raw_metadata={},
        )


def _effective_value(
    prediction: Prediction,
    *,
    confidence_threshold: float,
) -> str:
    if (
        prediction.confidence is not None
        and prediction.confidence < confidence_threshold
    ):
        return "abstain"
    return prediction.value


def _score(
    cases: tuple[CaseSpec, ...],
    raw_results: list[dict[str, Any]],
    *,
    confidence_threshold: float,
) -> dict[str, Any]:
    expected_lookup = {
        (case.case_id, question.name): question
        for case in cases
        for question in case.questions
    }
    total = 0
    covered = 0
    exact = 0
    unsafe_downgrades = 0
    conservative_escalations = 0
    abstained = 0
    latencies: list[float] = []
    input_tokens = 0
    output_tokens = 0
    known_cost = 0.0
    all_cost_known = True

    for result in raw_results:
        latencies.append(float(result["latency_ms"]))
        usage = result.get("usage") or {}
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
        cost = result.get("api_cost_usd")
        if cost is None:
            all_cost_known = False
        else:
            known_cost += float(cost)

        case_id = str(result["case_id"])
        predictions = result["predictions"]
        for question_name, prediction_raw in predictions.items():
            spec = expected_lookup[(case_id, question_name)]
            prediction = Prediction(
                value=str(prediction_raw["value"]),
                confidence=(
                    None
                    if prediction_raw.get("confidence") is None
                    else float(prediction_raw["confidence"])
                ),
                probabilities=prediction_raw.get("probabilities"),
            )
            value = _effective_value(
                prediction,
                confidence_threshold=confidence_threshold,
            )
            total += 1
            if value == "abstain":
                abstained += 1
                continue
            covered += 1
            if value == spec.expected:
                exact += 1
                continue
            if spec.order and value in spec.order:
                predicted_index = spec.order.index(value)
                expected_index = spec.order.index(spec.expected)
                if predicted_index < expected_index:
                    unsafe_downgrades += 1
                elif predicted_index > expected_index:
                    conservative_escalations += 1

    p50 = statistics.median(latencies) if latencies else 0.0
    p95 = 0.0
    if latencies:
        ordered = sorted(latencies)
        p95_index = min(
            len(ordered) - 1,
            max(0, int(round(0.95 * len(ordered) + 0.5)) - 1),
        )
        p95 = ordered[p95_index]

    return {
        "confidence_threshold": confidence_threshold,
        "questions": total,
        "covered": covered,
        "coverage": (covered / total if total else 0.0),
        "abstained": abstained,
        "exact": exact,
        "accuracy_over_covered": (exact / covered if covered else None),
        "unsafe_downgrades": unsafe_downgrades,
        "unsafe_downgrade_rate": (unsafe_downgrades / total if total else 0.0),
        "conservative_escalations": conservative_escalations,
        "conservative_escalation_rate": (
            conservative_escalations / total if total else 0.0
        ),
        "latency_ms_p50": p50,
        "latency_ms_p95": p95,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "known_api_cost_usd": known_cost,
        "complete_api_cost_usd": known_cost if all_cost_known else None,
    }


def _prediction_payload(prediction: Prediction) -> dict[str, Any]:
    return {
        "value": prediction.value,
        "confidence": prediction.confidence,
        "probabilities": prediction.probabilities,
    }


def _select_cases(
    cases: tuple[CaseSpec, ...],
    selected_ids: tuple[str, ...],
) -> tuple[CaseSpec, ...]:
    if not selected_ids:
        return cases
    by_id = {case.case_id: case for case in cases}
    missing = tuple(case_id for case_id in selected_ids if case_id not in by_id)
    if missing:
        raise ValueError(f"Unknown benchmark case(s): {', '.join(missing)}")
    return tuple(by_id[case_id] for case_id in selected_ids)


def _build_runner(args: argparse.Namespace) -> BenchmarkRunner:
    if args.runner == "abstain":
        return AbstainRunner()
    if args.runner == "ollama":
        return OllamaRunner(
            host=args.ollama_host,
            model=args.model,
            num_ctx=args.num_ctx,
            timeout=args.timeout,
        )
    if args.runner == "jev":
        api_key = os.getenv(args.jev_api_key_env, "")
        if not api_key.strip():
            raise RuntimeError(
                f"Jev API key missing from environment variable {args.jev_api_key_env}"
            )
        return JevRunner(
            endpoint=args.jev_endpoint,
            model=args.model,
            api_key=api_key,
            timeout=args.timeout,
            input_usd_per_million=args.jev_input_usd_per_million,
        )
    raise AssertionError(f"Unhandled runner: {args.runner}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen JARVIS C4/C5 bounded decision benchmark."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES,
        help="benchmark case JSON",
    )
    parser.add_argument(
        "--runner",
        choices=("abstain", "ollama", "jev"),
        required=True,
    )
    parser.add_argument(
        "--model",
        default="",
        help="model id for ollama/jev runner",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="run only one named case; may be repeated",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--jev-endpoint", default=DEFAULT_JEV_ENDPOINT)
    parser.add_argument("--jev-api-key-env", default="JEV_API_KEY")
    parser.add_argument(
        "--jev-input-usd-per-million",
        type=float,
        default=None,
        help=(
            "dated Jev input-token price; omit to keep monetary cost explicitly unknown"
        ),
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        action="append",
        default=[],
        help=(
            "score predictions below this reported confidence as abstain; "
            "may be repeated"
        ),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.repeat <= 0:
        parser.error("--repeat must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.runner in {"ollama", "jev"} and not args.model.strip():
        parser.error("--model is required for ollama/jev")
    for threshold in args.confidence_threshold:
        if not 0.0 <= threshold <= 1.0:
            parser.error("--confidence-threshold must be between 0 and 1")

    suite, all_cases = _load_cases(args.cases)
    cases = _select_cases(all_cases, tuple(args.case_id))
    runner = _build_runner(args)

    raw_results: list[dict[str, Any]] = []
    for repetition in range(1, args.repeat + 1):
        for case in cases:
            result = runner.run(case)
            raw_results.append(
                {
                    "case_id": case.case_id,
                    "repetition": repetition,
                    "runner": runner.name,
                    "model": result.model,
                    "latency_ms": result.latency_ms,
                    "usage": result.usage,
                    "api_cost_usd": result.api_cost_usd,
                    "predictions": {
                        name: _prediction_payload(prediction)
                        for name, prediction in result.predictions.items()
                    },
                    "raw_metadata": result.raw_metadata,
                }
            )

    thresholds = tuple(args.confidence_threshold) or (0.0,)
    report = {
        "suite": suite,
        "runner": runner.name,
        "requested_model": args.model or None,
        "case_count": len(cases),
        "repeat": args.repeat,
        "summaries": [
            _score(
                cases,
                raw_results,
                confidence_threshold=threshold,
            )
            for threshold in thresholds
        ],
        "results": raw_results,
    }

    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(encoded, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
