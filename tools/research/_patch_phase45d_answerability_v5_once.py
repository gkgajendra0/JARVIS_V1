from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"expected patch anchor missing: {label}")
    return text.replace(old, new, 1)


harness = Path("tools/research/step4_phase45d_answerability_bakeoff.py")
text = harness.read_text(encoding="utf-8")
text = replace_once(
    text,
    "MAX_ANSWER_LENGTH: Final = 16\nNLI_MAX_LENGTH: Final = 256",
    "MAX_ANSWER_LENGTH: Final = 16\nQA_MAX_SEQUENCE_LENGTH: Final = 256\nNLI_MAX_LENGTH: Final = 256",
    "QA max sequence constant",
)
text = replace_once(
    text,
    "    from transformers import AutoModelForQuestionAnswering, AutoTokenizer, pipeline\n",
    "    from transformers import AutoModelForQuestionAnswering, AutoTokenizer\n",
    "removed pipeline import",
)
marker = """def _run_qa_candidate(\n    candidate: dict[str, str],\n    rows: list[dict[str, object]],\n) -> dict[str, Any]:\n"""
helper = '''def _select_qa_answer(\n    *,\n    context: str,\n    input_ids: list[int],\n    sequence_ids: list[int | None],\n    offset_mapping: list[list[int]],\n    start_logits: list[float],\n    end_logits: list[float],\n    cls_token_id: int,\n    max_answer_len: int = MAX_ANSWER_LENGTH,\n) -> tuple[str, float]:\n    size = len(input_ids)\n    if not (\n        len(sequence_ids)\n        == len(offset_mapping)\n        == len(start_logits)\n        == len(end_logits)\n        == size\n    ):\n        raise ValueError("QA selector inputs must have identical token lengths")\n\n    try:\n        cls_index = input_ids.index(cls_token_id)\n    except ValueError as exc:\n        raise RuntimeError("QA tokenizer output does not contain its CLS token") from exc\n\n    context_indices = [\n        index\n        for index, sequence_id in enumerate(sequence_ids)\n        if sequence_id == 1 and offset_mapping[index][1] > offset_mapping[index][0]\n    ]\n    null_score = float(start_logits[cls_index] + end_logits[cls_index])\n    if not context_indices:\n        return "", null_score\n\n    best_start: int | None = None\n    best_end: int | None = None\n    best_score = float("-inf")\n    context_index_set = set(context_indices)\n\n    for start in context_indices:\n        max_end = start + max_answer_len - 1\n        for end in range(start, min(max_end, size - 1) + 1):\n            if end not in context_index_set:\n                continue\n            score = float(start_logits[start] + end_logits[end])\n            if score > best_score:\n                best_start = start\n                best_end = end\n                best_score = score\n\n    if best_start is None or best_end is None or null_score > best_score:\n        return "", null_score\n\n    start_char = int(offset_mapping[best_start][0])\n    end_char = int(offset_mapping[best_end][1])\n    if start_char < 0 or end_char <= start_char or end_char > len(context):\n        raise RuntimeError(\n            f"QA tokenizer returned invalid context offsets: {start_char}:{end_char}"\n        )\n    return context[start_char:end_char], best_score\n\n\n'''
text = replace_once(text, marker, helper + marker, "QA selector insertion")
text = replace_once(
    text,
    '''    qa = pipeline(\n        "question-answering",\n        model=model,\n        tokenizer=tokenizer,\n        device=0,\n    )\n    torch.cuda.synchronize()\n''',
    '''    if tokenizer.cls_token_id is None:\n        raise RuntimeError("QA tokenizer must define a CLS token for no-answer scoring")\n    torch.cuda.synchronize()\n''',
    "pipeline construction",
)
text = replace_once(
    text,
    '''    for row in rows:\n        output = qa(\n            question=str(row["question"]),\n            context=str(row["context"]),\n            handle_impossible_answer=True,\n            top_k=1,\n            max_answer_len=MAX_ANSWER_LENGTH,\n        )\n        if not isinstance(output, dict):\n            raise TypeError("QA pipeline returned an unexpected output type")\n        answer = str(output.get("answer", ""))\n        score = float(output.get("score", 0.0))\n        predictions.append(\n''',
    '''    for row in rows:\n        context = str(row["context"])\n        encoded = tokenizer(\n            str(row["question"]),\n            context,\n            return_tensors="pt",\n            return_offsets_mapping=True,\n            truncation="only_second",\n            max_length=QA_MAX_SEQUENCE_LENGTH,\n        )\n        sequence_ids = list(encoded.sequence_ids(0))\n        offset_mapping = encoded.pop("offset_mapping")[0].tolist()\n        input_ids = encoded["input_ids"][0].tolist()\n        device_inputs = {name: value.to("cuda") for name, value in encoded.items()}\n        with torch.inference_mode():\n            output = model(**device_inputs)\n        answer, score = _select_qa_answer(\n            context=context,\n            input_ids=input_ids,\n            sequence_ids=sequence_ids,\n            offset_mapping=offset_mapping,\n            start_logits=output.start_logits[0].detach().float().cpu().tolist(),\n            end_logits=output.end_logits[0].detach().float().cpu().tolist(),\n            cls_token_id=int(tokenizer.cls_token_id),\n        )\n        predictions.append(\n''',
    "per-row pipeline call",
)
text = replace_once(
    text,
    '''            "handle_impossible_answer": True,\n            "top_k": 1,\n            "max_answer_length": MAX_ANSWER_LENGTH,''',
    '''            "adapter": "transformers_v5_native_qa_logits",\n            "null_candidate": "cls_start_plus_end_logit",\n            "span_candidate": "best_valid_context_start_plus_end_logit",\n            "null_wins_only_when_strictly_greater": True,\n            "max_sequence_length": QA_MAX_SEQUENCE_LENGTH,\n            "max_answer_length": MAX_ANSWER_LENGTH,''',
    "decision contract",
)
text = replace_once(text, "    del qa, model, tokenizer\n", "    del model, tokenizer\n", "cleanup")
harness.write_text(text, encoding="utf-8")


tests = Path("tests/test_phase45d_answerability_bakeoff.py")
test_text = tests.read_text(encoding="utf-8")
test_text = replace_once(
    test_text,
    '    assert harness.NLI_CANDIDATE["model_id"] == (',
    '    assert harness.QA_MAX_SEQUENCE_LENGTH == 256\n    assert harness.MAX_ANSWER_LENGTH == 16\n\n    assert harness.NLI_CANDIDATE["model_id"] == (',
    "test contract constants",
)
test_text += '''\n\ndef test_native_qa_selector_returns_exact_context_span() -> None:\n    answer, score = harness._select_qa_answer(\n        context="Mosaic-4 enabled",\n        input_ids=[0, 10, 2, 20, 21, 2],\n        sequence_ids=[None, 0, None, 1, 1, None],\n        offset_mapping=[[0, 0], [0, 4], [0, 0], [0, 8], [9, 16], [0, 0]],\n        start_logits=[0.0, 99.0, 50.0, 5.0, 1.0, 50.0],\n        end_logits=[0.0, 99.0, 50.0, 1.0, 5.0, 50.0],\n        cls_token_id=0,\n    )\n    assert answer == "Mosaic-4 enabled"\n    assert score == 10.0\n\n\ndef test_native_qa_selector_returns_null_when_cls_wins() -> None:\n    answer, score = harness._select_qa_answer(\n        context="Mosaic-4 enabled",\n        input_ids=[0, 10, 2, 20, 21, 2],\n        sequence_ids=[None, 0, None, 1, 1, None],\n        offset_mapping=[[0, 0], [0, 4], [0, 0], [0, 8], [9, 16], [0, 0]],\n        start_logits=[7.0, 99.0, 50.0, 5.0, 1.0, 50.0],\n        end_logits=[7.0, 99.0, 50.0, 1.0, 5.0, 50.0],\n        cls_token_id=0,\n    )\n    assert answer == ""\n    assert score == 14.0\n\n\ndef test_native_qa_selector_ignores_non_context_logits() -> None:\n    answer, _ = harness._select_qa_answer(\n        context="Mosaic-4 enabled",\n        input_ids=[0, 10, 2, 20, 21, 2],\n        sequence_ids=[None, 0, None, 1, 1, None],\n        offset_mapping=[[0, 0], [0, 4], [0, 0], [0, 8], [9, 16], [0, 0]],\n        start_logits=[0.0, 500.0, 400.0, 6.0, 1.0, 300.0],\n        end_logits=[0.0, 500.0, 400.0, 1.0, 6.0, 300.0],\n        cls_token_id=0,\n    )\n    assert answer == "Mosaic-4 enabled"\n\n\ndef test_native_qa_selector_span_wins_exact_tie_with_null() -> None:\n    answer, _ = harness._select_qa_answer(\n        context="Mosaic-4",\n        input_ids=[0, 10, 2, 20, 2],\n        sequence_ids=[None, 0, None, 1, None],\n        offset_mapping=[[0, 0], [0, 4], [0, 0], [0, 8], [0, 0]],\n        start_logits=[5.0, 0.0, 0.0, 5.0, 0.0],\n        end_logits=[5.0, 0.0, 0.0, 5.0, 0.0],\n        cls_token_id=0,\n    )\n    assert answer == "Mosaic-4"\n'''
tests.write_text(test_text, encoding="utf-8")


method = Path("docs/research/STEP_4_PHASE_4_5D_ANSWERABILITY_BAKEOFF_METHOD.md")
method_text = method.read_text(encoding="utf-8")
method_text = replace_once(
    method_text,
    "This method replaces the unexecuted custom eight-class fine-tune V3. It is frozen before any owner model result exists.\n",
    "This method replaces the unexecuted custom eight-class fine-tune V3. It was frozen before any owner model result existed.\n\n### Pre-scoring Transformers v5 compatibility amendment\n\nThe first owner launch at repository SHA `f488a1b26a13f00ef78ba3239f919da77c47438a` stopped before the first QA case was scored because Transformers `5.16.1` no longer registers the legacy text `question-answering` pipeline. The environment, frozen corpus hash, first model revision, Safetensors load and CUDA path all succeeded; no output evidence file was written. Therefore the V1 corpus remains unexposed to model results.\n\nResearch confirmed that Transformers v5 still supports `AutoModelForQuestionAnswering` and native `start_logits` / `end_logits` inference. V1 is amended only at the execution-adapter layer: the removed convenience pipeline is replaced with a JARVIS-local deterministic adapter over those native logits. Corpus, candidate checkpoints, gates, tie-breaks, languages and no-threshold rule are unchanged.\n",
    "method amendment",
)
method_text = replace_once(
    method_text,
    "The Hugging Face QuestionAnsweringPipeline is used with `handle_impossible_answer=True`, `top_k=1` and no JARVIS-fitted probability threshold. The model's native impossible-answer candidate competes with extractive answer spans.\n",
    "Transformers v5 native `AutoModelForQuestionAnswering` logits are used directly. Valid context spans compete with the tokenizer CLS/no-answer position. The decision compares `start_logit + end_logit` for CLS against the best valid context span; because the same start/end softmax denominators apply to every candidate, this preserves the native SQuAD-2 ranking without introducing a fitted threshold.\n",
    "method pipeline description",
)
method_text = replace_once(
    method_text,
    "- https://huggingface.co/docs/transformers/main_classes/pipelines#transformers.QuestionAnsweringPipeline\n",
    "- https://huggingface.co/docs/transformers/main/tasks/question_answering\n- https://github.com/huggingface/course/issues/1211\n",
    "method reference",
)
method_text = replace_once(
    method_text,
    "handle_impossible_answer = true\ntop_k = 1\nmax_answer_length = 16\nfitted probability threshold = none",
    "adapter = transformers_v5_native_qa_logits\nnull candidate = CLS start_logit + end_logit\nspan candidate = best valid context start_logit + end_logit\nnull wins only when strictly greater\nmax_sequence_length = 256\nmax_answer_length = 16\nfitted probability threshold = none",
    "method frozen QA contract",
)
method.write_text(method_text, encoding="utf-8")


plan = Path("docs/CURRENT_PLAN.md")
plan_text = plan.read_text(encoding="utf-8")
plan_text = replace_once(
    plan_text,
    "Frozen QA contract:\n\n- Hugging Face question-answering pipeline;\n- `handle_impossible_answer=True`;\n- `top_k=1`;\n- max answer length `16`;",
    "Frozen QA contract (pre-scoring Transformers-v5 execution amendment):\n\n- first owner launch on `f488a1b26a13f00ef78ba3239f919da77c47438a` failed before scoring because Transformers `5.16.1` removed the legacy text QA pipeline; no result file was written and the corpus remains unexposed;\n- native `AutoModelForQuestionAnswering` start/end logits;\n- deterministic CLS/no-answer vs best valid context-span comparison;\n- strict null-win rule (`null_score > best_span_score`);\n- max sequence length `256`;\n- max answer length `16`;",
    "current plan QA contract",
)
plan.write_text(plan_text, encoding="utf-8")
