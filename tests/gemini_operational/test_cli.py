import pytest


def test_no_provider_client_in_status_or_admin(op_env, capsys):
    from jarvis.model_routing.live_budget_admin import LiveBudgetAdministration
    from jarvis.paid_budget_cli import main

    assert (
        main(
            ["status"],
            administration=LiveBudgetAdministration(op_env.runtime, broker=None),
        )
        == 0
    )
    text = capsys.readouterr().out
    assert "estimate" in text and "invoice" in text
    assert "35000" in text


@pytest.mark.parametrize("bad", ["reset", "force-clear", "set-spend"])
def test_no_unsafe_cli_escape_hatches(bad):
    from jarvis.paid_budget_cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args([bad])


def test_status_reports_known_held_unknown_and_policy_without_provider(op_env, capsys):
    import json

    from jarvis.model_routing.live_budget_admin import LiveBudgetAdministration
    from jarvis.paid_budget_cli import main

    from .admin_helpers import unknown_complete

    unknown_complete(op_env)
    main(
        ["status"], administration=LiveBudgetAdministration(op_env.runtime, broker=None)
    )
    data = json.loads(capsys.readouterr().out)
    row = data["operational_live"][0]
    assert (row["known_minor"], row["held_minor"], row["state"]) == (
        850,
        150,
        "uncertain",
    )
    assert row["policy_ref"] == op_env.policy.fingerprint
    assert "usage" not in row  # bounded telemetry, no raw provider payload
