# Current implementation and remaining limits

Reconciled 26 October 2026. This describes the integration candidate; merge and hosted-check status belong to its pull request. Earlier dated milestone reports are historical evidence, not current deployment instructions.

| Intended behavior | What the code implements | Remaining limit |
| --- | --- | --- |
| Use Gemini Free first, then Paid when Free quota is unavailable | Shared routing and voice handoff use separate Free/Paid credential references. With fallback enabled and budget enforcement disabled, Paid admission does not require internal monetary reservations. | Fallback is for eligible quota/rate pressure, not every provider error. Paid credentials, target health and authority/context checks still apply. |
| Return to Free when available | Recovery uses the existing health policy at a safe idle/demand boundary. | It does not immediately interrupt an active Paid response or continuously probe Free. |
| Keep the current automatic mode after restart | Machine configuration can preserve fallback enabled and budget enforcement disabled. | Repository defaults remain fallback off and budget enforcement on. A lost machine profile changes effective behavior. No exact Google invoice reconciliation is claimed. |
| Run Hands actions | Production constructs the capability runtime and routed planning settings. | A working action does not establish which credential was used; routing evidence is needed. Permission and application-specific acceptance remain separate. |
| Use the custom wake word | OpenWakeWord inference and a full-window compatibility validator are included, alongside reproducible training scripts. | Trained model binaries are external assets. Compatibility tests alone do not measure microphone false accepts/rejects. |
| Preserve installation assets across a Windows reimage | Persistent storage/bootstrap, restore launcher and training backup recipes are included. | Restore requires an existing Python environment and installed Jarvis commands. It is not a complete operating-system/dependency rebuild. Training backup is not a general recurring backup of all runtime data. |
| Recover protected owner memory and identity after reinstall | Encrypted files can remain on the persistent drive. | Windows DPAPI-sealed keys need a tested recovery path or fresh enrollment. Keeping the database file alone is insufficient. |
| Enroll the owner securely | Face templates are encrypted; Windows Hello approves the enrollment commitment. Raw enrollment frames are not persisted. | Native IR face matching is not implemented merely by connecting an IR camera. Windows controls its own Hello verification. Face evidence alone does not grant higher authority. |
| Include the latest UI | Production observer hooks and a read-only loopback UI server are integrated. | The UI remains opt-in through `JARVIS_UI_ENABLED`; merging source does not start it. |
| Use personal context and natural learning | Owner-authorized contextual projection, extraction, resolution and reconciliation are implemented. | Memory/context/learning are off by default. Learning uses bounded approved sessions, not continuous background learning or qualified speaker verification. Restore's context switch does not enable learning. |
| Become a broader autonomous assistant | The repository includes governed Work, routing and research foundations. | Source presence and historical tests are not proof of activation or whole-product acceptance. Older experimental branches are preserved separately. |

## Verification boundaries

The combined application source passed 3,353 automated tests with 8 skips before this documentation/publication-scope update. Ruff, PowerShell parsing and browser UI checks also passed. No source behavior is changed by excluding unpublished reports. Hosted checks must run on the published candidate before merge.

Automated checks do not replace owner acceptance for voice quality, wake sensitivity, every Hands action, IR hardware, learning quality or a fresh Windows reimage. Configuration, implementation, activation and acceptance are separate facts.

## Sources and setup

- [Windows recovery source layout](WINDOWS_E_DRIVE_RECOVERY.md)
- Routing: `src/jarvis/model_routing/gemini.py`, `runtime.py`, `invoker.py` and `src/jarvis/voice/gemini_handoff.py`
- Automatic admission: `src/jarvis/voice/gemini_automatic_fallback.py`
- Identity: `src/jarvis/identity/owner_enrollment.py`, `store.py` and the Windows Hello helper
- Personal learning: `src/jarvis/voice/canonical_active_speaker_runtime.py` and `src/jarvis/authority/personal_learning.py`

Unpublished historical implementation reports and original local commit history remain in local backups. Previously published history is retained without rewriting it. API keys, machine profiles, trained weights and personal databases are excluded from Git.
