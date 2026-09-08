# Step 7A / 9A — Governed Computer Use Research and Bounded Implementation

Status: **IMPLEMENTED FOR OWNER-MACHINE TECHNOLOGY SMOKE — NOT PRODUCTION-VOICE ENABLED**

Date: 2026-09-09

## Why this bounded interlude exists

The owner approved a narrow sequencing experiment before broad Step 7 local-file work:
use the smallest provider-neutral computer-use boundary and mature provider computer-use
technology instead of building custom GUI intelligence.

This does not mark Step 7 or Step 9 complete and does not change the protected roadmap
sequence by itself.

## Research decision

The implementation follows the research-first rule.

### Gemini

Google's current Gemini Computer Use supports `desktop` as a first-class environment.
The application supplies the current screenshot, Gemini returns bounded UI function
calls, the application executes them, captures a new screenshot, and returns a
`function_result`. Gemini 3.x uses normalized 0..999 screen coordinates and exposes
provider safety decisions including `require_confirmation` and blocked outcomes.

Selected default model: `gemini-3.6-flash`.

Important implementation choices:

- use the existing active provider credential;
- enable Gemini screenshot prompt-injection detection;
- never disable Gemini safety policies;
- never auto-acknowledge `require_confirmation`;
- use the same provider-neutral local executor contract as OpenAI.

Reference:
https://ai.google.dev/gemini-api/docs/computer-use

### OpenAI

The pinned OpenAI SDK already contains the current Responses `{"type": "computer"}`
tool plus `computer_call`, batched actions, pending safety checks, and
`computer_call_output` screenshot contracts. No SDK replacement is required.

Selected default model: `gpt-5.6-terra` for the cost-balanced OpenAI path. The model
remains replaceable.

Important implementation choices:

- pending provider safety checks stop execution;
- safety checks are never silently acknowledged;
- screenshot/action mechanics remain local and replaceable.

Reference:
https://platform.openai.com/docs/guides/tools-computer-use

### Windows bridge

The first replaceable local bridge uses:

- MSS 10.2.0 for fast all-monitor screenshot capture;
- PyAutoGUI 0.9.54 only as the bounded mouse/keyboard input driver;
- existing OpenCV/Numpy for PNG encoding.

MSS is imported before PyAutoGUI to avoid DPI-awareness interference. PyAutoGUI's
upper-left emergency fail-safe remains enabled. The bridge is isolated behind the
`ComputerExecutor` protocol so Microsoft UI Automation / `winapp ui` can replace or
supplement input mechanics later without changing Gemini/OpenAI provider logic.

References:
https://pypi.org/project/mss/
https://pyautogui.readthedocs.io/
https://learn.microsoft.com/windows/apps/dev-tools/winapp-cli/ui-automation

## Implemented contract

```text
ComputerUseService
    |
    +-- ComputerUseProvider
    |      +-- GeminiComputerUseProvider
    |      `-- OpenAIComputerUseProvider
    |
    `-- ComputerExecutor
           `-- MssPyAutoGuiExecutor
```

The provider owns model-specific computer-use protocol mechanics.
JARVIS owns the bounded local execution adapter and normalized truthful result.

The normal realtime Gemini/OpenAI voice brain is not replaced by this code.

## Safety boundary

This commit deliberately does **not** register `computer_use` as a production voice
tool yet.

Accepted Step-3 authority policy classifies reversible local changes as requiring at
least T2 `CORROBORATED_OWNER` plus direct intent for direct-user actions. Step 3
deliberately closed with T2 unpromoted. The current normal voice runtime also does not
yet assemble `AuthorityService` into arbitrary action tools.

The implementation therefore refuses to solve the integration problem by:

- pretending T1 is T2;
- reclassifying real computer actions as routine merely to avoid authority;
- adding a second ad-hoc permission system;
- relying only on provider safety;
- silently acknowledging provider safety checkpoints.

Production voice exposure remains a separate authority-binding task.

## Owner-machine smoke

Install the optional bridge:

```powershell
pip install -e ".[computer-use]"
```

Gemini smoke:

```powershell
jarvis-computer-smoke notepad-type --provider gemini
```

Read-only Settings navigation smoke:

```powershell
jarvis-computer-smoke settings-bluetooth-readonly --provider gemini
```

OpenAI can be selected with `--provider openai`.

The smoke harness:

- exposes only fixed non-consequential scenarios;
- requires the owner to type `RUN` before any action;
- keeps PyAutoGUI emergency fail-safe enabled;
- never runs from normal `jarvis-voice`;
- does not constitute production authority acceptance.

## Acceptance gate before live voice wiring

The next patch may expose a high-level canonical-user-turn `computer_use` tool only
after all of the following are true:

1. owner-machine Gemini or OpenAI smoke completes reliably;
2. multi-monitor coordinates are correct on the actual Windows setup;
3. provider safety confirmation/block paths halt before local execution;
4. a real Step-3 authority context can be supplied without inventing/promoting trust;
5. proposal -> approval -> permit -> immediate pre-execution revalidation is bound to
   the same material computer task;
6. no arbitrary shell, deletion, installation, communication, payment, security,
   account, or self-modification authority enters this slice.

Until then this is a technology-validating execution core, not a claim that JARVIS
has production hands.
