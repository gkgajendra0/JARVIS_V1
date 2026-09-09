# Step 7 — Governed Capability Runtime + Local Files/System/Project Safe Reads — Acceptance

Date: 2026-09-09

Owner acceptance: **PASS**

Accepted feature branch: `feat/step7-governed-runtime-v1`

Accepted implementation head before documentation reconciliation: `0fa09198a80b9ee3d2840e7d714b53e0cd96a4c4`

Step 7 closes the first provider-neutral governed capability runtime slice together with bounded local system/project/document reads. It remains deliberately read-focused; file writes, browser execution, desktop/app control, external communication, installation, deletion, and coding mutation remain later roadmap work.

## Accepted architecture

```text
latest accepted USER request
        |
        v
active JARVIS conversational brain
        |
        v
provider-neutral capability resolver/runtime
        |
        +-> dynamic discovery sources
        |     +-> Microsoft winapp CLI schema
        |     +-> Windows ODR when available
        |
        +-> executable Step-7 read adapters
              +-> local system reads
              +-> approved-root project/file reads
              +-> isolated document conversion
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

Permanent Step-7 boundary:

- JARVIS decides **what** capability is useful;
- the existing authority system decides **whether** execution is allowed;
- a bounded mature adapter decides **how** the read is performed;
- discovered metadata is untrusted and never grants execution authority;
- `windows.winapp:desktop.ui` remains discoverable but `execution_enabled=false` in Step 7;
- no arbitrary shell or generic command execution is exposed to the model;
- private local reads remain proposal-bound and strong-verification gated;
- returned local file/document content is untrusted data and gains no identity, memory, policy, or tool authority.

## Accepted capability surface

Executable Step-7 operations:

- `system_status`
- `list_processes`
- `file_info`
- `list_directory`
- `list_project_files`
- `search_project`
- `read_file`
- `read_document`

Dynamic discovery observed on the owner machine:

- `windows.winapp` — `AVAILABLE`;
- `windows.odr` — `UNAVAILABLE`, truthfully degraded without failing the catalog;
- `windows.winapp:desktop.ui` exposed its current semantic UI operation list but remained execution-disabled.

## Read/runtime safety properties accepted

- approved-root path resolution uses resolved-path containment and rejects traversal/symlink escapes;
- hidden/sensitive credential-like paths are blocked before release;
- secret-like text is withheld rather than released;
- text and document reads are size/output bounded;
- binary files require a supported document reader;
- project inventory prefers Git when available;
- project text search prefers ripgrep when available with a bounded Python fallback;
- system status uses bounded local telemetry and does not require private-content authorization;
- private process/project/file/document reads use canonical authority;
- authority failure produces `DENIED` and does not execute the read;
- execution results are privacy-aware audited;
- audit failure withholds the result.

## Isolated document-reader correction

Initial owner-machine setup exposed an important dependency conflict:

- JARVIS vision intentionally uses `onnxruntime==1.29.0`;
- MarkItDown `0.1.7` pulls Magika `0.6.x`, whose Windows dependency path selects ONNX Runtime `1.20.1`.

The accepted correction does **not** downgrade the JARVIS inference environment. Microsoft MarkItDown runs in a disposable isolated virtual environment created by `jarvis-setup-document-reader`.

Accepted isolation properties:

- main JARVIS environment retained ONNX Runtime `1.29.0`;
- document sidecar independently installed NumPy `2.4.6` and ONNX Runtime `1.20.1`;
- setup recreates the disposable sidecar to avoid partial-install residue;
- sidecar installation uses its own interpreter with Python isolated mode and pip isolated mode;
- inherited `PYTHONHOME`, `PYTHONPATH`, `VIRTUAL_ENV`, `PIP_*`, and common secret-bearing environment variables are stripped from the sidecar environment;
- conversion runs with `shell=False`, bounded timeout, bounded JSON output, and sanitized environment;
- setup validates MarkItDown, NumPy, ONNX Runtime, and converter import before reporting ready.

## Automated validation

Exact-head CI after the hermetic document-reader correction passed all required repository jobs:

- Ruff formatting/lint: **PASS**
- full pytest suite: **PASS**
- Windows Hello helper build/JSON contract: **PASS**
- Windows DPAPI smoke: **PASS**

## Owner-machine acceptance evidence

### 1. Positive governed Step-7 smoke — PASS

`jarvis-step7-smoke` on the owner Windows machine proved:

- dynamic capability discovery succeeded;
- `windows.winapp` discovered successfully;
- unavailable ODR degraded truthfully without blocking the runtime;
- `system_status` succeeded through the generic capability runtime;
- the private exact read `project/docs/ROADMAP.md` required Windows Hello;
- owner approval succeeded;
- the file read completed through canonical authority;
- `roadmap_verified=true`;
- no desktop/browser/write capability was enabled.

Observed final acceptance summary:

```json
{
  "ok": true,
  "operation": "step7_owner_acceptance",
  "read_only": true,
  "dynamic_discovery": true,
  "routine_system_read": true,
  "private_project_read": true,
  "canonical_authority": true,
  "writes_or_control_enabled": false
}
```

### 2. Windows Hello cancel / fail-closed — PASS

The same smoke was rerun and Windows Hello was explicitly canceled.

Observed result:

- routine `system_status`: `succeeded`;
- private `read_file`: `denied`;
- reason: `strong owner verification was not granted: user_canceled`;
- `roadmap_verified=false`;
- `returned_characters=0`.

This proves private content is not released when strong verification is canceled.

### 3. Real XLSX document read — PASS

A temporary owner-generated XLSX containing the marker `JARVIS Step 7 document acceptance` was placed under an explicitly approved temporary read root and read through `read_document`.

Observed result:

```json
{
  "status": "succeeded",
  "reason": null,
  "provenance": ["Microsoft MarkItDown isolated sidecar"],
  "contains_marker": true,
  "returned_characters": 80,
  "truncated": false
}
```

One earlier attempt returned `helper_timeout` before document execution. That attempt failed closed with no released content. An immediate retry completed successfully. This transient helper timeout is retained as a reliability observation, not hidden or treated as a successful execution.

### 4. Live `jarvis-voice` system read — PASS

During normal production voice runtime, the owner intentionally asked for current CPU and RAM status.

Observed production log:

```text
Step-7 local read completed | operation=system_status | status=succeeded
```

JARVIS answered from the real local system telemetry.

### 5. Live `jarvis-voice` private project read — PASS

The owner intentionally asked JARVIS to read the Step-7 section from `docs/ROADMAP.md` and summarize it.

Observed production log:

```text
Step-7 local read completed | operation=read_file | status=succeeded
```

JARVIS summarized the actual local roadmap content, including the governed read-only Step-7 scope and later-step exclusions.

### 6. Ambiguous meeting speech did not authorize local inspection — PASS for Step-7 grounding

The live acceptance occurred while an unrelated meeting was audible. Several meeting utterances were incorrectly admitted as conversational USER turns because the existing speaker/active-speaker layers remain diagnostic/shadow only.

This is a known voice/turn-admission limitation outside Step 7 and does not become capability authority.

Importantly, when ambiguous meeting speech caused the model to attempt a local inspection, the Step-7 grounding guard rejected it:

```text
ToolError while executing tool: user turn does not explicitly authorize inspect
```

Intentional owner local-read requests still succeeded.

The ambient-meeting false-turn problem remains assigned to future speaker/active-speaker admission work; Step 7 does not promote CAM++/LR-ASD shadow evidence or create a second identity gate.

## Accepted closure matrix

| Acceptance item | Result |
| --- | --- |
| Dynamic capability discovery | PASS |
| Generic provider-neutral capability runtime | PASS |
| Routine system status read | PASS |
| Canonical AuthorityService binding | PASS |
| Windows Hello positive path | PASS |
| Windows Hello cancel/fail-closed path | PASS |
| Approved-root private project read | PASS |
| Real XLSX document conversion | PASS |
| Hermetic MarkItDown/ONNX dependency separation | PASS |
| Secret/path/symlink protections | PASS (automated) |
| winapp desktop execution remains disabled | PASS |
| Live voice -> system read | PASS |
| Live voice -> private project read | PASS |
| Ambiguous local-inspection request denied | PASS |

## Explicit deferrals / non-goals

Step 7 does **not** claim completion of:

- file writes or document mutation;
- browser execution;
- desktop/application/device control;
- arbitrary shell/PowerShell execution;
- coding/project mutation;
- calendar/email/external communication;
- Windows ODR availability on the current owner OS;
- Windows App Actions consumption;
- Playwright browser control;
- T2 `CORROBORATED_OWNER` promotion;
- production CAM++/LR-ASD speaker/active-speaker admission thresholds;
- elimination of ambient-meeting false USER turns;
- universal/plugin lifecycle extensibility.

Those remain assigned to their later roadmap steps or previously documented identity/voice deferrals.

## Closure decision

**Step 7 is OWNER ACCEPTED and may proceed through documentation reconciliation and protected-main merge.**

The next roadmap slice after merge is **Step 8 — Notes, Tasks, Reminders, and Scheduling (CAP-027, CAP-028)**, which must begin research-first from the newly merged protected `main`.
