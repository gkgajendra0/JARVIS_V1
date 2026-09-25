"""Stable REPAIR knowledge contract identifiers.

This module intentionally depends on no incident, persistence, lifecycle, or projector
implementation so shared constants can be imported safely during cold process startup.
"""

PROJECTOR_ID = "repair-knowledge-projector:v1"
PROJECTION_POLICY_ID = "verified-repair-to-candidate:v1"
REPAIR_KIND_NAMESPACE = "jarvis.repair"
REPAIR_VERIFICATION_PREDICATE = "urn:jarvis:attestation:repair-verification:v1"
