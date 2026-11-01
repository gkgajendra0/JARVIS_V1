"""Regression tests for reproducible synthetic experiment fingerprints."""

from __future__ import annotations

import unittest

from experiments.librarian_parallel.bridge import ExperimentConfig
from experiments.librarian_parallel.fingerprints import config_fingerprint, fingerprint


class FingerprintTests(unittest.TestCase):
    def test_deterministic_and_key_order_independent(self) -> None:
        a = fingerprint({"second": [1, 2], "first": "value"})
        b = fingerprint({"first": "value", "second": [1, 2]})
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("sha256:"))
        self.assertEqual(len(a), 71)

    def test_changes_when_configuration_changes(self) -> None:
        first = ExperimentConfig(["python", "-m", "fixture"], ".", 5, {})
        second = ExperimentConfig(["python", "-m", "fixture"], ".", 10, {})
        self.assertNotEqual(config_fingerprint(first), config_fingerprint(second))

    def test_reject_non_json_values(self) -> None:
        with self.assertRaises(TypeError):
            fingerprint({"unsupported": object()})


if __name__ == "__main__":
    unittest.main()
