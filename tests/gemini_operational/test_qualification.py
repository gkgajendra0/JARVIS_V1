import pytest


def test_plan_only_qualification_constructs_no_client(capsys):
    from tools.research.gemini_operational_live_qualification import main

    assert main([]) == 0
    assert "plan-only" in capsys.readouterr().out


def test_execute_without_concrete_plan_does_not_request_authority():
    from tools.research.gemini_operational_live_qualification import main

    with pytest.raises(SystemExit):
        main(["--execute"])
