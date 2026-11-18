# Personal-context evaluation: held-out scenario (do not run or tune on it)

Sealed on 2026-11-17 with the first two evaluation cases
(`--context-eval`, `src/jarvis/voice/project_personal_context_eval.py`).
It has never been run. It is encoded as `-ContextEvalCase device` (question
`video_app_after_device_correction`); it runs only when that case is named. Use it once, unchanged, to check a proposed prompt or
retrieval fix after the fix is written; do not adjust the fix to it afterwards.

**Shape:** a corrected owned-item fact used for advice while an unrelated project
is active, in a fresh session, without the owner naming the item.

1. Active project "Kitchen renovation" with fictional owner turns: "We are
   renovating the kitchen in March." / "The countertop will be grey granite."
   and one assistant acknowledgement.
2. Explicit fictional memory commands (fresh Hello each):
   "Remember that my devices are a Lenovo ThinkPad X1 Carbon laptop." then
   "Correct my devices to a MacBook Air M3 laptop." (predicate `devices`, a
   registered `owned_item.device` facet; "laptop" alone has no scope.)
3. Fresh session, new thread in "Kitchen renovation":
   "Which video editing app should I install for my travel vlogs?"

**Pass:** the answer is about video-editing software (not the renovation),
recommends software that runs on macOS on the current laptop, and does not rely
on the ThinkPad or recommend Windows-only software. Run with and without saved
facts; record the model input, requested scopes (expect `owned_item.device`),
selected facts (the MacBook assertion only) and the final answer.
