# Proposed bounded recovery for intermittent provider failures

Status: owner approval pending. This changes the prior stop-on-provider-failure execution rule, not product behavior, credentials, model configuration, admission authority or quality targets.

Evidence: new answering availability returned in3.51s; remaining-only continuation then completed10 new memory cases and six pairs before answering again returned actual503. Combined v4:11 semantic episodes,14/14 expected effects, zero context mismatches, six complete pairs, two failed answer pairs,79unrun. Six blind author-reviewed supported answers used the right facts; empty-context arms made no unsupported owner claims. Only relevant questions have returned pairs so far; no broad usefulness claim.

Proposed rules:

1. Use only the239 already-authorized requests remaining under conservative cumulative ceiling532 (current upper293). No budget increase or paid fallback/account/model/key change.
2. At most THREE automatic recovery opportunities total. Wait at least60s,120s,240s respectively before each opportunity; each uses at most ONE new small fictional answering health request. Never replay a failed benchmark/health question. Retain every health outcome.
3. If a health request returns, continue only never-attempted frozen v4 IDs,15s spacing, same10s per-inference deadline and single-send SDK boundary. If it fails, stop that segment and wait for the next opportunity; no immediate retry. Any exhausted recovery count or request cap ends all live work.
4. If a continued segment fails, preserve its completed semantic row and unavailable answer. The next recovery opportunity may continue only yet-unattempted IDs. Earlier failures never become fresh successes, and exposed rows/gold are never changed.
5. Keep all failures/unavailability in attempted counts. Do not manufacture30complete pairs: two v4 pairs already failed. Complete remaining cases, review returned shuffled arms before keys, and report usefulness with failures visible in denominators. Unrun work, lifecycle/permission failures, hardware/voice and owner acceptance remain separate gates.
6. No local owner JARVIS activation/mic/camera/Hello, automatic merge or protected promotion.

Rationale: answering availability is intermittent, not a proved free-tier quota/billing problem. A successful one-off probe does not guarantee the full cohort remains available. This bounded protocol reduces repeated manual continuation while preventing uncontrolled retries or score replacement. Cost if wrong: up to3health calls and some permitted cohort calls on an unhealthy service; all consume the same finite239-request envelope and all failures remain evidence.
