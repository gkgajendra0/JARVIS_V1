# Personal intelligence: enablement and validation record

Last reconciled: 22 October 2026. This is the permanent record of what is implemented, how it is enabled and which experience has actually been validated. Update this page when a merge, persistent-setting change, normal-app acceptance or dependent milestone changes the status. Do not infer deployment settings from code defaults.

## Feature status

| Feature | Implementation / integration | Code default | Actual owner validation | Enable for one normal-app launch |
| --- | --- | --- | --- | --- |
| Saved personal context, recall and existing-memory correction | PR #294 and dependencies #292/#293 merged | OFF |21 October: owner confirmed saved-diet recall, correction, process restart and restoration in the whole Windows app; bounded scope only | `--personal-learning off --personal-context apply` |
| Automatic conversational learning without per-fact save prompts | Implemented/software-verified; PR #295 still OPEN/DRAFT at this checkpoint | OFF |Full normal-app owner acceptance pending; extended provider benchmark deferred, not passed | `--personal-learning apply` |
| Question-bound relevant context for ordinary advice (PI-3A) | Implemented on dependent candidate; software-verified; independent review in progress | OFF; shares learning mode | Actual-model selection and normal-app spoken acceptance pending | `--personal-learning apply` on the PI-3A candidate |

The earlier acceptance explicitly states: APPLY is opt-in; OFF remains default; no saved machine setting changes. See the [21 October owner acceptance](acceptance/PERSONAL_MEMORY_OWNER_ACCEPTANCE_2026-10-21.md). It does not accept automatic learning or all personal-intelligence behavior. The newer candidate's [handoff](research/PERSONAL_AUTO_LEARNING_IMPLEMENTED_HANDOFF_2026-10-22.md) and [qualification](research/PERSONAL_AUTO_LEARNING_QUALIFICATION_2026-10-22.md) retain its actual scope and pending gates.

## What default OFF means

The normal app reads its configured settings. Both personal-context and personal-learning code defaults are OFF; an explicit machine/environment setting or command-line override can differ. A plain launch is therefore not evidence that either feature was enabled on that specific machine.

An APPLY command enables the selected behavior for that process. It does not edit the saved machine profile, change the repository default or permanently enable future plain launches. Repeat the intended flags after a process restart unless an explicitly approved persistent setting has been configured. Existing facts remain in canonical encrypted memory; stopping/disabling a feature is not forgetting/deleting stored facts.

Merging code, enabling a feature for a test, completing owner acceptance and enabling it by default are separate recorded events. A merged feature can be default OFF and fully enabled in a specific test launch.

## Whole-JARVIS test launches

Use the configured Desktop checkout after confirming it contains the intended candidate/merged commit. PR #295 must be present for learning behavior, and the PI-3A candidate must also be present for the new question-bound context tool. An older main or PI-2-only checkout does not contain the new selector. See the [PI-3A implementation/whole-app acceptance protocol](research/PI3_CONTEXT_QUERY_IMPLEMENTATION_2026-10-22.md).

For the previously accepted personal-context path with automatic learning explicitly disabled:

```powershell
.\.venv\Scripts\jarvis-voice.exe --personal-learning off --personal-context apply
```

The historical 21 October command was `--personal-context apply` before the newer learning mode existed. The explicit learning-OFF flag above makes the intended isolation clear in a build that includes PR #295.

For normal JARVIS with automatic learning AND personal context enabled:

```powershell
.\.venv\Scripts\jarvis-voice.exe --personal-learning apply
```

Learning APPLY also enables context APPLY and canonical memory and suppresses transcript logging for the process. It opens one local Windows Hello private owner-operated delegation, maximum 15 minutes / 5 minutes idle. It does not biometrically authenticate each later speaker. Standard eligible facts may be learned without per-fact save questions; explicit private/destructive operations keep their existing approvals. Fresh wakes can reuse the active grant; private provider history still retires after a personal answer. Expiry/lock/stop revoke access; the model cannot open a new grant itself.

To disable automatic learning while retaining the accepted personal-context path, use the first command. To disable both automatic paths on a compatible build:

```powershell
.\.venv\Scripts\jarvis-voice.exe --personal-learning off --personal-context off
```

These controls do not delete memory or imply that separately configured explicit memory tools are disabled. Preserve schema 3 compatibility; no owner-database downgrade/deletion is part of switching modes.

## Required workflow for the next dependent milestone

1. Verify candidate/merged SHA and actual resolved modes before interpreting results. Keep keys, personal values and raw transcripts out of the activation record.
2. Exercise the whole normal JARVIS app in the learning-APPLY launch. Automatic learning/context must be ON when validating a milestone that depends on them. An OFF-only or mocked test does not establish the enabled experience.
3. Establish the dependency with general fictional conversation: learn ordinary facts, ask a later relevant question after a fresh wake, restart/re-enable, correct a fact, and forget it. Preserve actual canonical outcomes plus the owner's spoken-result observations. Do not require owner-authored examples or a standalone microphone demo.
4. Exercise the new milestone with the same enabled memory/context setup and the existing Authority/Work boundaries. Also retain relevant OFF/failure regressions so optional integration does not break ordinary operation.
5. Record failures/unavailable/unrun cases honestly. A quota failure is not a model-quality pass; deferred broad benchmarks are not fulfilled by a small local check. No future milestone is called end-to-end accepted while its required dependency remains unvalidated.
6. Update this status table, Current Plan, the candidate handoff and the appropriate dated acceptance record with the actual decision. Record default-OFF versus per-process APPLY versus any explicitly approved persistent activation separately. Do not silently turn a temporary launch flag into a machine setting.

Current pending work is implementation integration/normal-app validation as the owner elects, followed by the dependent milestone. Broad quota-bound qualification is deferred by owner direction. No extra provider batch, account/billing/model change, automatic schedule, activation or protected merge is performed by writing this guide.

## Source of truth

- [Current Plan](CURRENT_PLAN.md): active owner priority and deferrals.
- [Earlier bounded owner acceptance](acceptance/PERSONAL_MEMORY_OWNER_ACCEPTANCE_2026-10-21.md): the completed opt-in saved-preference test.
- [Automatic-learning handoff](research/PERSONAL_AUTO_LEARNING_IMPLEMENTED_HANDOFF_2026-10-22.md): delivered code and remaining gates.
- `src/jarvis/config.py`: defaults, environment/machine settings and APPLY implications.
- `src/jarvis/voice/production_runtime.py`: CLI overrides, runtime startup and incompatible-mode checks.
