from dataclasses import replace

import pytest
from google.genai.errors import APIError
from tests.gemini_fallback.helpers import exposure
from tests.gemini_fallback.test_invocation import environment, invoke

from jarvis.model_routing.budget import PaidBudgetDenied


@pytest.mark.parametrize("bounds", [(1, 1), (30000, 5000)])
def test_automatic_fallback_keeps_request_limits(tmp_path, monkeypatch, bounds):
    e = environment(
        tmp_path,
        monkeypatch,
        {"free-private-canary": [APIError(429, {})]},
        pricing_enabled=False,
    )
    e[2].config = replace(e[2].config, budget_enforced=False)
    with pytest.raises(PaidBudgetDenied):
        invoke(e, bound=exposure(*bounds))
    assert [key for key, _, _ in e[3]] == ["free-private-canary"]
