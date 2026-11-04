# Six-case project-memory development measurement

Spec: [project conversation memory contract](../../PROJECT_CONVERSATION_MEMORY.md).
This is a bounded measurement step in the existing implementation plan, not an
architecture change or activation of the installed application.

## Constraints

- Run only p0-q0, p1-q1, p2-q2, p3-q3, p4-q4, p5-q5 from the frozen development
  questions. Leave all held-out questions unrun. Validate normalized fixture hashes.
- One new profile and fresh owner Hello approval per case. Seed 60 fictional
  original events in three projects through existing source-bound authority.
  Preserve original evidence IDs and roles. Do not seed owner's personal memory.
- Ask one question per case through the existing Free-only text runtime. Preserve
  all policy, grant, child capacity, context and provider-step bounds. No automatic
  rerun, model grader, extraction calls or new paid allowance.
- Store each completed result immediately. Stop on first failure; retain partial
  results and mark remaining cases unrun. Fresh roots only, no batch resume.
- Report answer and manual rubric, source IDs, foreign-project evidence, observed
  usage and both provider and turn latency. Missing usage stays unknown. Never
  infer answer accuracy from source presence. Label p50/p95 with sample counts.

## Tasks

1. RED→GREEN fixed case selection, source-bound seeding, evidence and metrics.
2. RED→GREEN exclusive batch runner and text-lab/PowerShell entry points; stop on
   failure, cleanup existing runtime, write partial JSONL and final summary.
3. Document owner procedure and limits; run scoped regressions and Ruff. One fresh
   final review, then one TDD fix pass for Important/Critical findings if any.
4. Publish reviewed files to the existing draft branch; verify exact-head CI.
   Actual model/Windows qualification remains an owner-machine dependency.

## Shared interfaces

Task 1 provides validated cases and per-case evidence; Task 2 consumes them without
putting expected answers in provider input. Task 2 returns completed/error records;
Task 1 metrics count successful turns separately from failures and unrun cases.

## Review focus

Check answer-key leakage, project-scope leakage, expired/revoked authority during
seeding, partial setup or output failure, Hello denial, report overwrites, Windows
line endings, unknown telemetry, capacity exhaustion, and cleanup on early exit.
Fake-provider tests are not actual-model accuracy, Windows encryption or latency
qualification. Existing interactive and seeded acceptance modes must keep working.
