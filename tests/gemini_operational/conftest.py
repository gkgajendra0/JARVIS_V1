from types import SimpleNamespace

import pytest
from tests.gemini_fallback.conftest import isolate_inference

__all__ = ["isolate_inference"]


@pytest.fixture
def op_env(tmp_path):
    from tests.gemini_live.helpers import Endpoint
    from tests.gemini_live.test_budget import live_env

    from .helpers import policy, profile

    _, runtime, target, price = live_env(tmp_path)
    return SimpleNamespace(
        governor=runtime.paid_budget,
        store=runtime.store,
        runtime=runtime,
        target=target,
        price=price,
        policy=policy(),
        profile=profile(),
        endpoint=Endpoint(runtime),
        clock=runtime.clock,
    )
