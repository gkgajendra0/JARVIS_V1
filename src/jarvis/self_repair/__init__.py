"""Deterministic Self-Repair foundation."""

from jarvis.self_repair.domain import (
    MAX_EVIDENCE_REFERENCES,
    RepairAction,
    RepairActionKind,
    RepairAttempt,
    RepairAuthorizationError,
    RepairEscalation,
    RepairPolicy,
    RepairPolicyConflictError,
    RepairPolicyError,
    RepairRiskClass,
    RepairTrigger,
    RepairVerdict,
)
from jarvis.self_repair.registry import RepairRegistry

__all__ = [
    "MAX_EVIDENCE_REFERENCES",
    "RepairAction",
    "RepairActionKind",
    "RepairAttempt",
    "RepairAuthorizationError",
    "RepairEscalation",
    "RepairPolicy",
    "RepairPolicyConflictError",
    "RepairPolicyError",
    "RepairRegistry",
    "RepairRiskClass",
    "RepairTrigger",
    "RepairVerdict",
]
