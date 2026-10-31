import importlib.util
from pathlib import Path


def test_production_smoke_gate_requires_the_packaged_current_schema():
    path = (
        Path(__file__).resolve().parents[1]
        / "tools/research/step4_sqlcipher_production_adapter_smoke.py"
    )
    spec = importlib.util.spec_from_file_location("project_sqlcipher_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.migration_checks(5, 5) == {
        "migration_version": True,
        "migration_ledger_complete": True,
    }
    assert not all(module.migration_checks(4, 4).values())
