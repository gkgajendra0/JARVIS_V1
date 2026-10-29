# PR 303 scripted transient voice lab

This is a transport/semantic-observer smoke test, not full conversational-intelligence acceptance. Normal startup has no semantic factory and remains unchanged.

## Preconditions

Run the updated automated Windows verifier at the candidate commit first. Require green hosted CI at that commit. Close the normal Jarvis voice process so the lab owns the microphone. Use the installed `E:\Jarvis\App\.venv` with existing Gemini credentials, configured wake model, OPA, Hello helper, and qualified SQLCipher/DPAPI. No dependencies are installed by the launcher.

`Start-JarvisSemanticSmoke.ps1` requires a full candidate commit and the approved configured semantic model. It creates a detached checkout and fresh profile under a unique temporary directory. Optional `-MachineProfile` selects the existing settings file to copy. Only non-secret machine settings are copied; memory, encryption keys and prior conversation data are never copied. The lab reuses executable/model assets read-only and the existing process credentials. It writes its own encrypted memory/routing stores, audit database and bounded JSONL log. The inherited free/paid routing policy still applies; routed API calls can incur the configured provider charges.

The existing owner-operated memory-session approval is intentionally broader in wording than this lab: the lab starts no learning worker, creates no checkpoint writer and issues no persistence child permits. Denied Hello stops startup. Windows-session continuity is rechecked for semantic dispatch; no grant is inferred from an unlocked desktop.

Camera, speaker-shadow, active-speaker and Pocket3 tracking observers are disabled in this microphone lab to avoid opening the installed biometric store. This lab does not qualify camera-based identity diagnostics.

## Script

After owner approval, wake Jarvis and say each sentence separately, waiting for the response and inference log:

1. I am planning a Nepal trip
2. I will travel in my Jimny
3. The permits are already sorted
4. Budget is unrestricted
5. We still need to plan the route
6. Correction, we will leave on 10 November
7. The route is already planned
8. Nepal trip ka budget fixed nahi hai

Only exact reviewed utterances with case/terminal punctuation variation enter semantic extraction. An ASR paraphrase is denied. Normal Gemini Live microphone audio remains the usual provider channel; this gate does not filter that audio. Speak synthetic test information only.

Look for `Semantic script smoke inference` and `Semantic script smoke applied`. The latter reports only aggregate topic/constraint/step counts, with `checkpoint_write=False`; it does not log source text or authorization tokens. Save `profile/smoke.jsonl` and the console output. Missing applied events or zero proposals are findings, not a pass. These aggregate diagnostics require manual inspection and do not prove the semantic content is correct.

Ctrl+C ends the lab. A new wake must construct fresh transient state. Nothing is injected into Gemini from the reducer; Gemini's ordinary conversational responses cannot prove this observer's correctness. Topic resume, encrypted checkpoint save/forget, restart recovery, protected follow-up handoff, latency qualification and general privacy classification remain separate unfinished gates. Do not merge or activate from this smoke result.
