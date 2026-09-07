"""Upstream-contract GLiClass runtime sanity diagnostic for Phase 4.5D.

This is not a JARVIS acceptance benchmark. It intentionally uses only public
GLiClass model-card examples and never imports or scores the exposed JARVIS
Question-Role V1 corpus.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
from typing import Any, Final

OUTPUT_DEFAULT = Path(".step4-phase45d-gliclass-runtime-sanity-v1.json")
GLICLASS_PACKAGE_VERSION: Final = "0.1.20"

CANDIDATES: Final = (
    {
        "key": "gliclass_multilang_mini",
        "model_id": "knowledgator/gliclass-multilang-mini",
        "revision": "0bd888b6c3ef9fca5f0a9d407bddfbbc7623486b",
    },
    {
        "key": "gliclass_multilang_ultra",
        "model_id": "knowledgator/gliclass-multilang-ultra",
        "revision": "9d6ca10258a3bddcf05b88c89cb8a8390e87e90c",
    },
)

# Public examples copied from the GLiClass Multilang model card. These are not
# derived from any JARVIS benchmark, memory, user fact, or retired corpus.
PUBLIC_CASES: Final = (
    {
        "case_id": "model_card_topic_en",
        "text": "NASA launched a new Mars rover to search for signs of ancient life.",
        "labels": ("space", "politics", "sports", "technology", "health"),
        "expected_any": ("space",),
    },
    {
        "case_id": "model_card_intent_en",
        "text": "Can you set an alarm for 7am tomorrow?",
        "labels": (
            "set_alarm",
            "play_music",
            "get_weather",
            "send_message",
            "set_reminder",
        ),
        "expected_any": ("set_alarm",),
    },
    {
        "case_id": "model_card_topic_de",
        "text": (
            "Die NASA hat einen neuen Mars-Rover gestartet, um nach Spuren alten "
            "Lebens zu suchen."
        ),
        "labels": ("Weltraum", "Politik", "Sport", "Technologie", "Gesundheit"),
        "expected_any": ("Weltraum",),
    },
    {
        "case_id": "model_card_topic_ar_crosslingual",
        "text": "أطلقت ناسا مركبة جديدة للمريخ للبحث عن آثار الحياة القديمة.",
        "labels": ("space", "politics", "sports", "technology"),
        "expected_any": ("space",),
    },
    {
        "case_id": "model_card_government_fr_crosslingual",
        "text": "Le gouvernement français a annoncé de nouvelles mesures économiques.",
        "labels": ("economy", "politics", "sports", "technology"),
        "expected_any": ("economy", "politics"),
    },
)

# A shared-label batch made only from the public English NASA, French government,
# and Arabic NASA texts/labels. The union label set lets us test the exact
# shared-label batch path used by Question-Role V1 without reusing any JARVIS text.
SHARED_BATCH_LABELS: Final = (
    "space",
    "politics",
    "sports",
    "technology",
    "economy",
    "health",
)
SHARED_BATCH_CASES: Final = (
    {
        "case_id": "shared_topic_en",
        "text": PUBLIC_CASES[0]["text"],
        "expected_any": ("space",),
    },
    {
        "case_id": "shared_government_fr",
        "text": PUBLIC_CASES[4]["text"],
        "expected_any": ("economy", "politics"),
    },
    {
        "case_id": "shared_topic_ar",
        "text": PUBLIC_CASES[3]["text"],
        "expected_any": ("space",),
    },
)


def _one_prediction(output: object) -> dict[str, Any]:
    if not isinstance(output, list) or len(output) != 1:
        raise TypeError("single-label GLiClass output must contain exactly one item")
    item = output[0]
    if not isinstance(item, dict):
        raise TypeError("GLiClass prediction must be a mapping")
    label = item.get("label")
    score = item.get("score")
    if not isinstance(label, str) or not isinstance(score, (int, float)):
        raise TypeError("GLiClass prediction must contain string label and numeric score")
    return {"label": label, "score": float(score)}


def _run_candidate(candidate: dict[str, str]) -> dict[str, Any]:
    import torch
    from gliclass import GLiClassModel, ZeroShotClassificationPipeline
    from transformers import AutoTokenizer

    model = None
    tokenizer = None
    classifier = None
    try:
        model = GLiClassModel.from_pretrained(
            candidate["model_id"],
            revision=candidate["revision"],
            use_safetensors=True,
            trust_remote_code=False,
        )
        tokenizer = AutoTokenizer.from_pretrained(
            candidate["model_id"],
            revision=candidate["revision"],
            trust_remote_code=False,
        )
        classifier = ZeroShotClassificationPipeline(
            model,
            tokenizer,
            classification_type="single-label",
            device="cuda:0",
            progress_bar=False,
        )

        public_results: list[dict[str, Any]] = []
        for case in PUBLIC_CASES:
            output = classifier(
                str(case["text"]),
                list(case["labels"]),
                classification_type="single-label",
            )[0]
            prediction = _one_prediction(output)
            public_results.append(
                {
                    "case_id": case["case_id"],
                    "prediction": prediction,
                    "expected_any": list(case["expected_any"]),
                    "semantic_pass": prediction["label"] in case["expected_any"],
                }
            )

        shared_individual: list[dict[str, Any]] = []
        for case in SHARED_BATCH_CASES:
            output = classifier(
                str(case["text"]),
                list(SHARED_BATCH_LABELS),
                classification_type="single-label",
            )[0]
            prediction = _one_prediction(output)
            shared_individual.append(
                {
                    "case_id": case["case_id"],
                    "prediction": prediction,
                    "expected_any": list(case["expected_any"]),
                    "semantic_pass": prediction["label"] in case["expected_any"],
                }
            )

        batch_outputs = classifier(
            [str(case["text"]) for case in SHARED_BATCH_CASES],
            list(SHARED_BATCH_LABELS),
            batch_size=len(SHARED_BATCH_CASES),
            classification_type="single-label",
        )
        if not isinstance(batch_outputs, list) or len(batch_outputs) != len(
            SHARED_BATCH_CASES
        ):
            raise TypeError("GLiClass shared-label batch returned unexpected output shape")

        shared_batch: list[dict[str, Any]] = []
        for case, individual, output in zip(
            SHARED_BATCH_CASES,
            shared_individual,
            batch_outputs,
            strict=True,
        ):
            prediction = _one_prediction(output)
            shared_batch.append(
                {
                    "case_id": case["case_id"],
                    "prediction": prediction,
                    "expected_any": list(case["expected_any"]),
                    "semantic_pass": prediction["label"] in case["expected_any"],
                    "top_label_matches_individual": (
                        prediction["label"] == individual["prediction"]["label"]
                    ),
                }
            )

        distinct_shared_labels = sorted(
            {row["prediction"]["label"] for row in shared_batch}
        )
        checks = {
            "public_model_card_semantics": all(
                bool(row["semantic_pass"]) for row in public_results
            ),
            "shared_batch_semantics": all(
                bool(row["semantic_pass"]) for row in shared_batch
            ),
            "shared_batch_matches_individual_top_labels": all(
                bool(row["top_label_matches_individual"]) for row in shared_batch
            ),
            "shared_batch_not_single_label_collapse": len(distinct_shared_labels) >= 2,
        }
        return {
            "key": candidate["key"],
            "model_id": candidate["model_id"],
            "revision": candidate["revision"],
            "status": "COMPLETE",
            "public_results": public_results,
            "shared_individual": shared_individual,
            "shared_batch": shared_batch,
            "distinct_shared_batch_labels": distinct_shared_labels,
            "checks": checks,
            "runtime_sanity_pass": all(checks.values()),
        }
    except torch.cuda.OutOfMemoryError as exc:
        return {
            "key": candidate["key"],
            "model_id": candidate["model_id"],
            "revision": candidate["revision"],
            "status": "RESOURCE_REJECTED",
            "error": f"{type(exc).__name__}: {exc}",
            "runtime_sanity_pass": False,
        }
    finally:
        if classifier is not None:
            del classifier
        if model is not None:
            del model
        if tokenizer is not None:
            del tokenizer
        gc.collect()
        torch.cuda.empty_cache()


def run() -> dict[str, Any]:
    import gliclass
    import torch
    import transformers

    if not torch.cuda.is_available():
        raise RuntimeError("GLiClass runtime sanity requires the owner CUDA path")
    if getattr(gliclass, "__version__", None) != GLICLASS_PACKAGE_VERSION:
        raise RuntimeError(
            "unexpected GLiClass version: "
            f"{getattr(gliclass, '__version__', None)!r} != "
            f"{GLICLASS_PACKAGE_VERSION!r}"
        )

    results = [_run_candidate(candidate) for candidate in CANDIDATES]
    return {
        "status": "GLICLASS_UPSTREAM_CONTRACT_RUNTIME_SANITY_V1_COMPLETE",
        "diagnostic_only": True,
        "jarvis_question_role_v1_queries_used": False,
        "jarvis_task_prompt_used": False,
        "jarvis_custom_role_labels_used": False,
        "cloud_provider_calls": 0,
        "environment": {
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "gliclass": gliclass.__version__,
            "gpu": torch.cuda.get_device_name(0),
        },
        "candidates": results,
        "decision": {
            "mini_runtime_sanity_pass": bool(results[0]["runtime_sanity_pass"]),
            "ultra_runtime_sanity_pass": bool(results[1]["runtime_sanity_pass"]),
            "production_change_authorized": False,
            "question_role_v1_rerun_authorized": False,
            "phase45e_authorized": False,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output = Path(args.output)
    if output.exists():
        raise RuntimeError(f"refusing to overwrite GLiClass runtime sanity evidence: {output}")

    result = run()
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output}")
    print("STATUS:", result["status"])
    print(
        "SANITY_SUMMARY:",
        json.dumps(
            {
                row["key"]: {
                    "status": row["status"],
                    "runtime_sanity_pass": row["runtime_sanity_pass"],
                    "checks": row.get("checks"),
                    "public_results": row.get("public_results"),
                    "shared_batch": row.get("shared_batch"),
                }
                for row in result["candidates"]
            },
            ensure_ascii=False,
        ),
    )
    print("DECISION:", json.dumps(result["decision"], ensure_ascii=False))


if __name__ == "__main__":
    main()
