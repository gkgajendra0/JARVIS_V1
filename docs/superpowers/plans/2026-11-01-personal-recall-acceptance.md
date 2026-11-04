# Personal recall and correction acceptance implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline. The owner has authorized continuous implementation and isolated testing; retain the existing draft PR and Free-only lane.

**Goal:** qualify successful canonical personal recall across two projects and after a correction, separately from the completed no-match case.

**Architecture:** add an explicitly invoked fresh-profile acceptance sequence to the existing text lab. Use MemoryAgentTools and PersonalContextSession for approved fictional remember/correct operations, then the existing project coordinator/provider for three questions. No alternate fact store, policy bypass or extraction request.

**Tech stack:** existing Python, SQLCipher/DPAPI, OPA, Windows Hello and Gemini runtime.

**Spec:** [project memory contract](../../PROJECT_CONVERSATION_MEMORY.md), especially G4 and Task 5. This bounded fixture does not qualify automatic learning, native speech, process restart or the frozen held-out set.

## Design and approaches

The owner approved testing a known personal fact across projects including corrections. Reuse the existing explicit memory mutation path in an opt-in fictional fixture. Direct SQL seeding would skip authority and provenance; asking the model to create fixture data adds cost and conflates admission with recall. The implementation choice is a fixed three-question sequence, with zero setup inference calls.

Start with an empty isolated archive and canonical memory. Print each synthetic memory command before its fresh owner approval. Save diet preference vegetarian, ask from Travel acceptance and Study acceptance, correct to vegan, then ask from a new Travel acceptance thread. Mutation commands remain outside project archives, so project text alone cannot supply the initial answer. Existing first-thread assistant echoes may remain during the final correction check; the corrected canonical fact must reach the final provider context. The fixture is supplemental and must not alter frozen development/held-out data.

## Global constraints

- Fresh marked profile only; reject resume, seed-acceptance and development-batch combinations before filesystem/Windows work.
- Exactly three questions; existing four-step bound per question, Free-only, no automatic retries, paid expansion or activation.
- Remember and correction require existing exact consent and transaction guards; denied setup stops before inference.
- Durable append-only JSONL after every committed mutation and completed/failed question; stop on first operational/evidence failure. Keep earlier evidence on cleanup failure.
- Report actual tool statuses, expected/stale personal assertion coverage and final-payload coverage separately from manual answer grading. Never infer answer correctness from coverage.
- Do not expose expected answers in model instructions, titles, questions or project seed text. Expected facts enter provider input only through normal authorized personal retrieval or prior actual answers.
- No unredacted exception messages or owner profile data in diagnostic failure records.

## Review focus

Denied/revoked mutation grants; accidental fixture reuse; model answering without personal evidence; stale assertion after correction; partial journal and cleanup failures.

## Task 1: bounded personal acceptance sequence and entry points

**Files:** create `src/jarvis/voice/project_personal_acceptance.py`, `tests/learning/test_project_personal_acceptance.py`; modify `project_memory_lab.py`, Windows launcher and acceptance guide.

**Interface:** `run_personal_acceptance(root, *, memory, capability, coordinator, access, provider)` returns a summary. The lab owns resource cleanup; the sequence owns exclusive JSONL output and incremental sanitized records.

- [x] RED: real SQLite/lifecycle/project coordinator with fake OS/Hello/provider proves three final payloads select the expected assertion and correction removes the previous assertion; foreign project history and answer keys absent.
- [x] RED: denial before remember/correct and missing personal evidence stop without subsequent inference; retained prior rows remain valid. Existing output is not overwritten.
- [x] Implement fixed source-grounded mutations, project selection and independent questions; inspect canonical projection IDs and final dispatched personal payload, not answer wording.
- [x] RED→GREEN CLI isolation validation and lab cleanup integration; extend PowerShell switch forwarding.
- [x] Run scoped memory/lab regressions (exclude real OPA locally), Ruff and formatting; record actual owner p5 timing evidence and this gate in docs.
- [ ] One fresh final review, one TDD repair pass for Important/Critical findings, publish exact tree to draft PR303, verify exact-head hosted gates. Owner Windows/Hello run remains unrun until handoff.
