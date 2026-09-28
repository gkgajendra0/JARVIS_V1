"""Lightweight autonomy runtime mode contract.

This module intentionally has no JARVIS subsystem imports so core configuration can
load without pulling network, audio, model, Authority, or engineering runtime code.
"""

from __future__ import annotations

from enum import StrEnum


class AutonomyMode(StrEnum):
    OFF = "off"
    OBSERVE = "observe"
    SHADOW = "shadow"
    ASSISTED = "assisted"
    ACTIVE_BOUNDED = "active_bounded"
