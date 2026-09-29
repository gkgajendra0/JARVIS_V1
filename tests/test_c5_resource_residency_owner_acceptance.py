from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from jarvis.model_routing.local_residency import LocalResidencyPolicy

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "research" / "c5_resource_residency_owner_acceptance.py"


def _load_module():
    name = "jarvis_c5_resource_residency_acceptance_test_module"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_production_policy_keeps_accepted_c5_thresholds() -> None:
    policy = LocalResidencyPolicy()

    assert policy.min_free_to_load_mib == 5600
    assert policy.max_util_to_load_percent == 45.0
    assert policy.pressure_free_mib == 1800
    assert policy.pressure_util_percent == 80.0
    assert policy.recovery_free_mib == 5600
    assert policy.recovery_util_percent == 35.0
    assert policy.pressure_samples == 2
    assert policy.recovery_samples == 3


def test_owner_acceptance_module_imports_without_side_effects() -> None:
    module = _load_module()

    assert callable(module._run)
    assert callable(module.main)
