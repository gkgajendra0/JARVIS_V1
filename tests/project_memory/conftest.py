"""Reuse canonical approval fixtures; only Windows/Hello are simulated."""

import importlib.util
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "learning/conftest.py"
spec = importlib.util.spec_from_file_location("project_memory_authority_fixtures", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
clock = module.clock
authority_parts = module.authority_parts
