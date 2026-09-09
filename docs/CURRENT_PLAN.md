# JARVIS V1 Current Plan

## Active Work

**Step 7 — Governed Capability Runtime + Local Files/System/Project Safe Reads — OWNER ACCEPTED / DOCUMENTATION RECONCILIATION / FINAL MERGE GATE.**

Step 7 implementation and owner-machine acceptance are complete. The remaining lifecycle work is documentation reconciliation, final exact-head CI, and protected-main merge.

After that merge, **Step 8 — Notes, Tasks, Reminders, and Scheduling (CAP-027, CAP-028)** becomes the next roadmap slice and must begin research-first from the newly merged `main`.

## Current Stage

**STEP 4 BOUNDED COMPLETE — STEP 5 BOUNDED COMPLETE — STEP 6 BOUNDED COMPLETE — STEP 7 OWNER ACCEPTED — DOCUMENTATION RECONCILIATION / FINAL EXACT-HEAD CI / PROTECTED-MAIN MERGE — THEN STEP 8 REQUIREMENTS + RESEARCH.**

This file is the operational source of truth. `PRODUCT.md` owns permanent product intent, `ROADMAP.md` owns sequence, accepted architecture belongs in `CURRENT_ARCHITECTURE.md`, and detailed research/evidence belongs in `docs/research/`.

---

## Accepted foundations carried forward

Step 3 remains the canonical identity/authority foundation. T2 `CORROBORATED_OWNER` remains disabled; Windows Hello/T3 remains the accepted strong-verification path. CAM++ speaker identity and LR-ASD active-speaker evidence remain diagnostic/shadow only and do not grant authority.

Step 4 remains bounded complete with encrypted canonical memory, explicit remember/inspect/correct/forget, accepted FTS5 + Qwen retrieval/reranking, and bounded provider-assisted `recall_memory`. The strict independent 4.5D verifier and Phase-4.5E automatic semantic-memory injection remain deferred.

Step 5 remains bounded complete with deterministic terminal provider-failure diagnosis, Windows-local truthful status speech, safe failed-session closure, and return toward wake/idle. Full local/offline conversation remains deferred.

Step 6 remains bounded complete with provider-neutral source-aware web research, accepted Exa retrieval, JARVIS-owned evidence/provenance/truth status, deterministic research-warrant gating, and fail-closed source sufficiency behavior.

---

## Step 7 — accepted outcome

The accepted Step-7 path is:

```text
latest accepted USER request
        |
        v
active conversational brain
        |
        v
provider-neutral capability resolver/runtime
        |
        +-> discovery sources
        |     +-> Microsoft winapp CLI schema
        |     +-> Windows ODR when available
        |
        +-> executable Step-7 read adapters
              +-> local system reads
              +-> approved-root project/file reads
              +-> isolated document reads
        |
        v
PreparedCapability
        |
        v
canonical ActionProposal
        |
        v
existing AuthorityService
        |
        +-> routine metadata: bounded T0 path
        +-> private local/project content: Windows Hello / T3
        |
        v
one-time permit revalidation + consume
        |
        v
read-only execution
        |
        v
structured result + provenance + audit
```

Accepted executable operations:

- `system_status`
- `list_processes`
- `file_info`
- `list_directory`
- `list_project_files`
- `search_project`
- `read_file`
- `read_document`

Accepted boundaries and invariants:

- JARVIS decides what capability is useful; canonical authority decides whether it may execute; bounded adapters decide how the read occurs;
- no second authority or permission system was introduced;
- discovered capability metadata is untrusted and never grants execution authority;
- Microsoft `winapp` is dynamically discoverable but desktop/UI execution remains disabled in Step 7;
- Windows ODR discovery degrades truthfully when unavailable and does not block the catalog;
- no arbitrary shell, PowerShell, browser control, app/device control, file write, coding mutation, installation, or deletion is exposed;
- approved-root path handling rejects parent traversal and symlink escapes;
- hidden/sensitive credential-like paths are blocked;
- secret-like released text is blocked/redacted according to the bounded read path;
- project inventory prefers Git and project text search prefers ripgrep with bounded local fallback;
- private local/project reads use canonical `ActionProposal -> AuthorityService -> Windows Hello/T3 -> one-time permit revalidation`;
- cancel, timeout, denial, audit failure, malformed input, and unavailable capabilities fail closed;
- local file/document contents are untrusted data and may not change identity, memory, policy, permissions, or tool behavior;
- production voice exposes one generic `inspect_local` tool rather than hardcoding one function per user task.

### Isolated document-reader decision

Owner testing exposed an ONNX dependency conflict between the accepted JARVIS vision runtime and MarkItDown/Magika on Windows.

The accepted correction keeps Microsoft MarkItDown but runs it in a disposable isolated sidecar environment provisioned by `jarvis-setup-document-reader`.

Accepted owner-machine environment separation:

- main JARVIS ONNX Runtime: `1.29.0`;
- isolated document sidecar MarkItDown: `0.1.7`;
- isolated sidecar NumPy: `2.4.6`;
- isolated sidecar ONNX Runtime: `1.20.1`.

The sidecar is recreated cleanly, installs with Python/pip isolation, strips inherited Python/pip and common secret-bearing environment variables, executes with `shell=False`, uses bounded timeout/output, and validates dependency closure before reporting ready.

### Owner acceptance evidence

Owner-machine acceptance on 2026-09-09 proved:

1. dynamic `winapp` discovery and truthful unavailable ODR discovery;
2. routine local CPU/RAM/system status through the generic runtime;
3. positive private read of `docs/ROADMAP.md` through Windows Hello + canonical authority with `roadmap_verified=true`;
4. explicit Windows Hello cancel produced `DENIED`, `roadmap_verified=false`, and zero returned private characters;
5. a real temporary XLSX was read through `Microsoft MarkItDown isolated sidecar` and contained the expected acceptance marker;
6. a transient Windows Hello helper timeout failed closed before document execution; immediate retry succeeded;
7. live `jarvis-voice` used `system_status` successfully;
8. live `jarvis-voice` used `read_file` successfully and summarized the actual local Step-7 roadmap text;
9. ambiguous meeting speech did not gain local-read permission: an attempted local inspection was rejected with `user turn does not explicitly authorize inspect`.

Detailed evidence:

- `docs/research/STEP_7_CAPABILITY_DISCOVERY_RUNTIME_IMPLEMENTATION.md`
- `docs/research/STEP_7_GOVERNED_CAPABILITY_RUNTIME_ACCEPTANCE.md`

### Known residuals / explicit deferrals

Step 7 does not claim completion of:

- file/document writes;
- browser execution;
- desktop/application/device control;
- arbitrary shell/PowerShell execution;
- coding/project mutation;
- calendar/email/external communication;
- Windows ODR availability on the current owner OS;
- Windows App Actions consumption;
- Playwright browser execution;
- T2 `CORROBORATED_OWNER` promotion;
- production CAM++/LR-ASD speaker/active-speaker admission thresholds;
- elimination of ambient-meeting false USER turns;
- plugin/skill lifecycle extensibility.

The meeting-audio false-turn observation remains a voice/identity admission issue, not Step-7 capability authority. Step-7 grounding correctly prevented ambiguous speech from authorizing a local inspection.

---

## Next roadmap slice after merge

**Step 8 — Notes, Tasks, Reminders, and Scheduling (CAP-027, CAP-028).**

The next work slice must start research-first from the newly merged protected `main`:

1. recover Step-8 requirements from `PRODUCT.md`, accepted decisions, and prior lessons;
2. inspect merged conversation/memory/authority/capability-runtime boundaries before designing scheduling state;
3. research current mature note/task/reminder/scheduling technologies and platform APIs;
4. prefer mature existing technology over custom infrastructure where it fits;
5. reuse Step-7 capability/authority patterns instead of inventing parallel execution or permissions;
6. define the smallest provider-neutral Step-8 architecture;
7. obtain owner architecture approval before implementation.

Step 8 must not quietly pull browser automation, desktop control, email/calendar integration, or file-write/coding authority forward from their assigned roadmap steps.

---

## Immediate Next Action

**FINAL EXACT-HEAD CI FOR PR #28 -> PROTECTED-MAIN MERGE -> MARK STEP 7 DONE -> START STEP 8 REQUIREMENTS / RESEARCH FROM NEW `main`.**
