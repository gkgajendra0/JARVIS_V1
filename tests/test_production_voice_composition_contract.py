from __future__ import annotations

import ast
import inspect
import textwrap

from jarvis.voice.canonical_active_speaker_runtime import (
    CanonicalActiveSpeakerRuntimeController,
)
from jarvis.voice.production_runtime import build_production_voice_runtime
from jarvis.voice.runtime import VoiceRuntimeController


def _constructor_keywords_used_by_production_builder() -> set[str]:
    source = textwrap.dedent(inspect.getsource(build_production_voice_runtime))
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (
                isinstance(node.func, ast.Name)
                and node.func.id == "CanonicalActiveSpeakerRuntimeController"
            )
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "CanonicalActiveSpeakerRuntimeController"
            )
        )
    ]
    assert len(calls) == 1
    return {keyword.arg for keyword in calls[0].keywords if keyword.arg is not None}


def _explicit_keyword_parameters(callable_object) -> set[str]:
    return {
        name
        for name, parameter in inspect.signature(callable_object).parameters.items()
        if name != "self"
        and parameter.kind
        in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
    }


def test_production_controller_composition_keywords_have_an_explicit_owner() -> None:
    """Every production keyword must be owned by the child or base constructor.

    CanonicalActiveSpeakerRuntimeController intentionally forwards ordinary voice
    dependencies to VoiceRuntimeController. Production-only dependencies therefore
    must be declared explicitly by the child before they can reach **kwargs. This
    contract catches composition drift without constructing cameras, DBOS, or audio.
    """

    production_keywords = _constructor_keywords_used_by_production_builder()
    child_keywords = _explicit_keyword_parameters(
        CanonicalActiveSpeakerRuntimeController.__init__
    )
    base_keywords = _explicit_keyword_parameters(VoiceRuntimeController.__init__)

    unowned = production_keywords - child_keywords - base_keywords

    assert unowned == set(), (
        "build_production_voice_runtime passes constructor keywords with no explicit "
        f"owner: {sorted(unowned)}"
    )



def _call_by_name(tree: ast.AST, name: str) -> ast.Call:
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]
    assert len(calls) == 1
    return calls[0]


def test_production_runtime_wires_bounded_jev_into_work_runtime() -> None:
    source = textwrap.dedent(inspect.getsource(build_production_voice_runtime))
    tree = ast.parse(source)

    jev_call = _call_by_name(tree, "build_jev_acquisition_candidate_advisor")
    jev_kwargs = {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in jev_call.keywords
        if keyword.arg is not None
    }

    assert jev_kwargs == {
        "enabled": "config.jev_bounded_decisions_enabled",
        "benchmark_admitted": "config.jev_benchmark_admitted",
        "minimum_confidence": "config.jev_min_confidence",
        "model": "config.jev_model",
        "endpoint": "config.jev_endpoint",
        "benchmark_report_path": "config.jev_benchmark_report_path or ''",
    }

    work_call = _call_by_name(tree, "build_work_runtime")
    work_kwargs = {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in work_call.keywords
        if keyword.arg is not None
    }

    assert (
        work_kwargs["acquisition_candidate_advisor"]
        == "acquisition_candidate_advisor"
    )
