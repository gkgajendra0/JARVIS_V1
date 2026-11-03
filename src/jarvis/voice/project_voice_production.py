"""Owner-activated project conversation memory in normal Jarvis voice.

Disabled by default: ``JARVIS_PROJECT_MEMORY_MODE`` is ``off`` unless the owner
sets it to ``voice`` in the machine profile. With it off, nothing in this module
runs and Jarvis voice is unchanged.

With it on, the same tested path as the isolated voice lab is used: every
accepted owner turn of a wake conversation is saved to the encrypted project
archive by the application, the current project's recent history is preloaded
once per wake session, and project commands and cross-project questions go
through ``prepare_project_turn``. Differences from the lab are deliberate:

- the normal tool set stays available (no lab allowlist);
- a denied or timed-out Windows Hello approval at startup leaves Jarvis running
  as ordinary voice (logged), instead of stopping it;
- in a configuration not yet qualified with project memory, Jarvis starts as
  ordinary voice and logs the exact reasons at ERROR, before any Hello prompt
  (see :func:`activation_blockers`). ``python -m
  jarvis.voice.project_voice_production --check`` reports them without
  starting Jarvis.

Rollback: set ``JARVIS_PROJECT_MEMORY_MODE`` back to ``off`` (or remove it) and
restart Jarvis. No migration or data change is needed; saved project history
stays encrypted and unused.
"""

from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


def activation_blockers(config) -> list[str]:
    """Reasons ``project_memory_mode=voice`` cannot run with this configuration."""
    if config.project_memory_mode != "voice":
        return []
    blockers = []
    if not config.memory_enabled:
        blockers.append(
            "JARVIS_MEMORY_ENABLED must be true: project memory uses the canonical "
            "encrypted memory store and its Windows Hello history authority"
        )
    if config.ai_provider != "gemini":
        blockers.append(
            "JARVIS_AI_PROVIDER must be gemini: project memory needs native Gemini "
            "Live with blocking tool behaviour"
        )
    if config.gemini_fallback.enabled:
        blockers.append(
            "Gemini fallback/transport handoff must be disabled: a handoff starts a "
            "new model session without the preloaded project context or blocking "
            "tool behaviour (not yet qualified)"
        )
    if config.personal_context_mode != "off":
        blockers.append(
            "JARVIS_PERSONAL_CONTEXT_MODE (and personal learning) must be off: "
            "personal-context APPLY has its own response gate and session "
            "retirement that are not yet qualified together with project memory"
        )
    return blockers


def production_project_memory_factory(config):
    """The runtime's project-memory factory, or None when the flag is off."""
    if config.project_memory_mode != "voice":
        return None
    blockers = activation_blockers(config)
    if blockers:
        # Availability first: never stop or restart-loop Jarvis over this flag.
        LOGGER.error(
            "Project memory NOT active (JARVIS_PROJECT_MEMORY_MODE=voice): %s. "
            "Jarvis continues as ordinary voice.",
            "; ".join(blockers),
        )
        return None

    def factory(memory_runtime, capability_runtime):
        from jarvis.memory.project_history_source import standard_history_source
        from jarvis.voice.project_voice import VoiceProjectMemory

        return VoiceProjectMemory(
            memory_runtime,
            capability_runtime,
            source_clearance=standard_history_source,
            required=False,
        )

    return factory


def main(argv=None) -> int:
    """``--check``: report whether the configured flag can activate."""
    import argparse

    from jarvis.config import JarvisConfig

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args(argv)
    config = JarvisConfig.from_environment()
    if config.project_memory_mode != "voice":
        print("JARVIS_PROJECT_MEMORY_MODE=off: project memory is disabled.")
        return 0
    blockers = activation_blockers(config)
    if blockers:
        print("JARVIS_PROJECT_MEMORY_MODE=voice but it will NOT activate:")
        for item in blockers:
            print(" - " + item)
        return 1
    print(
        "JARVIS_PROJECT_MEMORY_MODE=voice: project memory will start with Jarvis "
        "(Windows Hello approval at startup)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
