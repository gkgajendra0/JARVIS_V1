# Native topic continuity acceptance

**HISTORICAL candidate guide — not current acceptance.** The owner’s 30 October run restored the Nepal topic with empty details and failed the desired connected-conversation behavior. This launcher remains diagnostic evidence, not a command to activate the replacement. Read the [current contract](PROJECT_CONVERSATION_MEMORY.md) and [build plan](superpowers/plans/2026-10-31-project-conversation-memory.md).

This mode tests saved topic state in the **spoken response path**. The older
`semantic_smoke_lab` only tests transient extraction; its applied event never
established connected replies.

Run `tools/windows/Start-JarvisTopicContinuity.ps1 -Commit <exact-feature-sha>`
after fetching the feature branch once. The launcher does not fetch again or
install dependencies. The main Windows checkout is unchanged. Source, SQLCipher
memory, DPAPI key, authority audit and logs use a separate temporary lab root.
Windows Hello opens the existing standard owner-learning delegation; later
speaker identity is not independently verified.

The optional blocking `prepare_conversation_topic` tool proposes grounded changes
from the latest canonical transcript. The application validates, saves, then
returns actual selected topic data as the function result before the answer.
There is no second extraction-model request. Exact script matching is not used
in this mode, although the current admission policy deliberately restricts
storage to standard plan/task discussion and excludes known restricted data.
This policy is not a universal natural-language privacy classifier.

1. Wake and say “I am planning a Nepal trip.” Expect a topic-tool `ready` status
   and a response about Nepal.
2. Say “My vehicle is a Jimny.” Expect `ready` and a response connecting the
   vehicle to Nepal. If recognized as Gemini, expect a clarification, not a
   silently substituted vehicle. Repeat the full corrected field statement.
3. Sleep, wake, say “The permits are already sorted.” Within ten minutes and the
   same authorized process, the selected topic can continue. Expect a response
   connecting permits to Nepal and retaining Jimny.
4. Stop with Ctrl+C. Run the same launcher with the printed `-LabRoot`, same
   `-Commit` and `-Resume`. Approve Hello again. Say “Continue my Nepal trip.”
   A named request restores the existing isolated encrypted checkpoint. A bare
   “continue” after restart/expiry must ask which topic, not guess.
5. Say “Departure is 9 November”, then “Correction, departure is 10 November”.
   A subsequent named read must use 10 November, without claiming the date/year
   is independently verified.
6. Say “We still need to plan the route”, then “The route is already planned”.
   The completed route must not be listed as pending.
7. Say “Forget Nepal trip”. A later named read must return no matching topic.
   Old response buffers, cached selections and delayed writes cannot revive it.
8. Test Windows lock/revoke while a tool/answer is pending: no old private
   response may continue; reopening requires genuine owner authorization.

The short continuation selection is process-local and revision-bound. It is not
a serialized authority handle. Restart/expiry requires a named topic. Generic
personal memories and explicit remember/correct/forget controls keep their
existing authorization. Normal production startup has no continuity factory
unless explicitly configured; this mode is the isolated qualification path.

Evidence must include the model-facing tool result and context/revision guards
in automated tests, exact-head hosted CI, and actual connected spoken replies
in this native sequence. A tool `ready` line alone does not establish answer
quality or latency. Measure voice end-to-first-audio and tool duration separately.
