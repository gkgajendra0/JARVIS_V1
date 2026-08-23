# JARVIS V1 Product

JARVIS V1 is a clean implementation of a personal JARVIS assistant. It will be
built incrementally from explicit product slices rather than speculative
subsystems.

The previous JARVIS project is engineering reference only. JARVIS V1 does not
import from it or depend on it at runtime.

## Architectural Constraints

1. One authoritative owner per responsibility.
2. Provider SDKs live behind JARVIS-owned adapters and contracts.
3. There is no giant `main.py`.
4. Models do not receive unrestricted system-execution authority.
5. Models do not write directly to persistent memory.
6. Conversation and context have no duplicate owners.
7. Legacy compatibility requires explicit approval.
8. Accepted replacements remove abandoned implementations.
9. Git history is the archive.
10. Each change builds only what the current product slice needs.
