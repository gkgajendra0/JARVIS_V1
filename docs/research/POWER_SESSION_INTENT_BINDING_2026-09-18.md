# Power/Session Intent Binding — Research and Safety Decision (2026-09-18)

## Incident

A live owner-machine run exposed a safety gap: a Windows power/session operation could be proposed by Hands and then pass Windows Hello even when the accepted USER utterance did not actually request that Windows operation.

The important distinction is:

- Windows Hello establishes the owner's identity/consent at the verification prompt.
- It does not independently determine whether the planner selected the operation the USER intended.

## External guidance reviewed

- OWASP Transaction Authorization Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html
  - significant transaction data should be identifiable and acknowledged;
  - authentication and transaction authorization should be distinguishable;
  - authorization credentials/state should be bound to the specific operation;
  - execution should re-check that the exact transaction was properly authorized.

- Microsoft Windows Hello / UserConsentVerifier:
  https://learn.microsoft.com/en-us/windows/apps/develop/security/windows-hello
  - Windows Hello/UserConsentVerifier is a user verification mechanism;
  - the application remains responsible for deciding which protected action is being authorized.

- NIST SP 800-63B:
  https://pages.nist.gov/800-63-4/sp800-63b.html
  - authentication intent is an explicit response from the claimant during authentication and does not replace application-level authorization semantics.

## Repository root cause

Before this fix, Hands verified only that planner `evidence` was a verbatim substring of the latest accepted canonical USER turn. Power/session normalization then discarded the evidence and returned an empty parameter set:

```python
if action.operation in _POWER_OPERATIONS or not action.parameters:
    return NormalizedAction(action.operation, {})
```

Therefore a planner-selected `restart_workstation` could be authorized even when its evidence was a copied conversational phrase such as “That's all for now.” The later Windows Hello check proved who approved the proposal, not that the proposal matched the USER's requested operation.

## Decision

Power/session actions now use defense in depth.

1. **Canonical USER semantic guard**
   - planner evidence must still be an exact substring of the latest canonical USER turn;
   - that exact evidence must also explicitly identify the proposed power/session operation;
   - it must explicitly identify the local computer/Windows target;
   - conversational phrases about JARVIS sleeping, standing by or ending a conversation are rejected.

2. **Proposal-bound strong authorization**
   - `intent_operation` and bounded `intent_evidence` are carried into `PreparedCapability.parameters`;
   - those parameters are included in the immutable `ActionProposal` fingerprint;
   - the Windows Hello prompt material summary shows both the operation and the exact USER evidence;
   - the one-time permit is therefore bound to that exact proposal fingerprint.

3. **Executor fail-closed**
   - `PowerSessionExecutor` refuses every unbound power/session request;
   - operation substitution between the intent binding and requested executor operation is rejected.

4. **Incident reconstruction**
   - Authority audit events record capability, operation and, for power/session proposals only, the bounded `intent_operation` and `intent_evidence`;
   - result events remain linked by proposal ID/fingerprint.

## Privacy boundary

The Authority audit does not persist arbitrary proposal parameters. Only the bounded power/session intent phrase (maximum 240 characters) is added for this critical safety domain. Existing forbidden audit metadata rules for secrets/tokens/biometrics remain unchanged.

## Acceptance boundary

Automated acceptance requires:

- standby-like text cannot execute `sleep_workstation` or `restart_workstation`;
- a shutdown phrase cannot be substituted into restart;
- “Restart Jarvis” cannot be treated as “restart the computer”;
- valid lock/sleep/sign-out/restart/shutdown evidence binds to the exact operation;
- unbound direct executor calls fail closed;
- Authority audit preserves the bound intent;
- Windows Hello helper and Windows Hands regressions remain green.

Owner-machine acceptance must additionally verify:

- standby phrases do not open Windows Hello for power/session actions;
- a real explicit restart/shutdown request shows the exact operation/evidence in Windows Hello;
- canceling Windows Hello causes no power action;
- local wake/standby behavior remains intact.

Actual restart/shutdown execution is not required for acceptance.
