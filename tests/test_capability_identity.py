from __future__ import annotations

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.models import CapabilityDescriptor, CapabilityKind
from jarvis.capabilities.runtime import CapabilityRuntime


class NoopAuthority:
    def close(self) -> None:
        pass


class MismatchedExecutor:
    capability_key = "browser:playwright"
    operations = ("execute_browser_plan",)
    descriptor = CapabilityDescriptor.create(
        capability_id="navigation.execution",
        source_id="browser",
        kind=CapabilityKind.STRUCTURED_AUTOMATION,
        name="Mismatched browser executor",
        description="Intentional mismatch used to protect the runtime identity invariant.",
        operations=list(operations),
        execution_enabled=True,
    )

    def prepare(self, request):
        raise AssertionError("mismatched executor must be rejected before prepare")

    def execute(self, prepared):
        raise AssertionError("mismatched executor must be rejected before execute")


def test_runtime_rejects_executor_descriptor_identity_mismatch() -> None:
    executor = MismatchedExecutor()

    with pytest.raises(
        ValueError,
        match="executor key must exactly match its descriptor identity",
    ):
        CapabilityRuntime(
            executors=(executor,),
            resolver=CapabilityResolver((), builtins=(executor.descriptor,)),
            authority=NoopAuthority(),
        )
