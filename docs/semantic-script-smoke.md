# PR 303 scripted transient voice lab

This is a transport/semantic-observer smoke test, not full conversational-intelligence acceptance. Normal startup has no semantic factory and remains unchanged.

## Preconditions

Run the updated automated Windows verifier at the candidate commit first. Require green hosted CI at that commit. Close the normal Jarvis voice process so the lab owns the microphone. Use the installed `E:\Jarvis\App\.venv` with existing Gemini credentials, configured wake model, OPA, Hello helper, and qualified SQLCipher/DPAPI. No dependencies are installed by the launcher.

`Start-JarvisSemanticSmoke.ps1` requires a full candidate commit and the approved configured semantic model. It creates a detached checkout and fresh profile under a unique temporary directory. Optional `-MachineProfile` selects the existing settings file to copy. Only non-secret machine settings are copied; memory, encryption keys and prior conversation data are never copied. The lab reuses executable/model assets read-only and the existing process credentials. It writes its own encrypted memory/routing stores, audit database and bounded JSONL log. The inherited free/paid routing policy still applies; routed API calls can incur the configured provider charges.

The existing owner-operated memory-session approval is intentionally broader in wording than this lab: the lab starts no learning worker, creates no checkpoint writer and issues no persistence child permits. Denied Hello stops startup. Windows-session continuity is rechecked for semantic dispatch; no grant is inferred from an unlocked desktop.

Camera, speaker-shadow, active-speaker and Pocket3 tracking observers are disabled in this microphone lab to avoid opening the installed biometric store. This lab does not qualify camera-based identity diagnostics.

The lab's initial and follow-up inactivity windows are at least 30 seconds so an otherwise idle wake does not close before extraction's 20-second cancellation deadline. Longer configured windows are preserved. Explicit standby and Ctrl+C still close immediately.

The model wire schema requires a `value` field; topic titles belong in `value`, while `topic` identifies the target of a dependent update. The parser retains a decode default only for bounded recovery. Before returning proposals, the producer checks action-specific required values and keys. Missing content permits one additional routed correction operation, under the same total extraction deadline, with a different operation ID and fresh source/authority checks. The correction sends only the original cleared utterance and fixed schema guidance, never the malformed model payload. Both operations follow the existing free/paid router policy. A second incomplete response is rejected; no empty value is invented or admitted to the reducer.

## Script

After owner approval, wake Jarvis and say each sentence separately, waiting for the response and inference log:

1. I am planning a Nepal trip
2. My vehicle is a Jimny
3. The permits are already sorted
4. Budget is unrestricted
5. We still need to plan the route
6. Departure is 9 November
7. Correction, departure is 10 November
8. The route is already planned
9. Budget ka issue nahi hai

Only exact reviewed utterances with case/terminal punctuation variation enter semantic extraction. An ASR paraphrase is denied. Normal Gemini Live microphone audio remains the usual provider channel; this gate does not filter that audio. Speak synthetic test information only.

The cloud lab uses a 20-second cancellation deadline per asynchronous extraction, rather than the original attachment's five-second default. A client that suppresses cancellation can take longer to return. Voice callbacks do not wait for extraction. Closing the bridge still immediately revokes state and requests bounded worker cleanup; authorization is rechecked at dispatch, response and apply. This diagnostic setting is not a demonstrated latency target. Ordinary opt-in attachments retain the five-second default.

The script explicitly names field labels and establishes an original departure before correcting it. These constraints follow the current conservative evidence validator; this lab does not demonstrate unrestricted natural-language semantics. The producer may move one introduced topic before dependent proposals only when every dependent explicitly names that same topic; unbound or foreign proposals are never reassigned. Atomic reducer validation remains authoritative.

Look for `Semantic script smoke inference` and `Semantic script smoke applied`. The latter reports only aggregate topic/constraint/step counts, with `checkpoint_write=False`; it does not log source text or authorization tokens. Save `profile/smoke.jsonl` and the console output. Missing applied events or zero proposals are findings, not a pass. These aggregate diagnostics require manual inspection and do not prove the semantic content is correct.

Ctrl+C ends the lab. A new wake must construct fresh transient state. Nothing is injected into Gemini from the reducer; Gemini's ordinary conversational responses cannot prove this observer's correctness. Topic resume, encrypted checkpoint save/forget, restart recovery, protected follow-up handoff, latency qualification and general privacy classification remain separate unfinished gates. Do not merge or activate from this smoke result.
