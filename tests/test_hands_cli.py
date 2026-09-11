from __future__ import annotations

from jarvis.computer import hands_cli


def test_hands_cli_integrated_routes_to_consolidated_acceptance(monkeypatch) -> None:
    monkeypatch.setattr(hands_cli, "run_integrated_acceptance", lambda: 17)

    assert hands_cli.main(["--integrated"]) == 17


def test_hands_cli_readiness_routes_to_complete_hands_readiness(monkeypatch) -> None:
    monkeypatch.setattr(hands_cli, "run_integrated_readiness", lambda: 18)

    assert hands_cli.main(["--readiness"]) == 18


def test_hands_cli_keeps_legacy_native_diagnostic(monkeypatch) -> None:
    seen: list[float] = []

    def native(volume: float) -> int:
        seen.append(volume)
        return 19

    monkeypatch.setattr(hands_cli, "run_native_core_acceptance", native)

    assert hands_cli.main(["--native", "--volume", "35"]) == 19
    assert seen == [35.0]


def test_hands_cli_keeps_legacy_default_notepad_diagnostic(monkeypatch) -> None:
    monkeypatch.setattr(hands_cli, "run_notepad_acceptance", lambda: 20)

    assert hands_cli.main([]) == 20
