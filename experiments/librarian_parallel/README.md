# Parallel Librarian experiment (not production Jarvis)

**Status:** MCP integration boundary implemented, but the creator's Librarian implementation is **not installed or verified**. No confirmed public server package, documented tool names/schemas, or endpoint is available. Do not label synthetic fixture results as Librarian benchmark results.

This directory is intentionally isolated from PR #303's project history, personal-memory code and SQLCipher database, the installed Jarvis runtime, owner memory, Windows Hello, and provider settings.

## Intended architecture

Complete baseline Jarvis (later) vs complete baseline Jarvis + separate external Librarian MCP process (later).
This directory supplies the **external MCP side only**, so PR #303 can continue acceptance testing independently.

It uses stdio MCP JSON-RPC initialization, tool discovery, tool calls and pagination. It neither assumes creator-specific tool names nor fabricates the internal algorithms. No new Python dependencies or paid services.

## Implemented

- Spawn explicitly configured MCP server without a shell, with bounded timeout and cleanup.
- MCP initialize, discovery, tool-list pagination, invocation and error handling.
- Explicit operation mapping (recall, remember, correct, forget) to advertised names and argument templates.
- Synthetic-only project-ID scope; blocked writes unless caller explicitly opts in and supplies a fixture source.
- No automatic forwarding of owner conversations or secrets; default CLI logs redact tool responses.
- Offline synthetic MCP fixture server and tests for recall, correction, forgetting, separation, unknown tools and denied writes.

## Run offline checks (Windows PowerShell)

From the root of an isolated checkout of this branch:

    py -3.11 -m unittest discover -s experiments/librarian_parallel -p "test_*.py" -v

    py -3.11 -m experiments.librarian_parallel.cli --config experiments/librarian_parallel/fixture.example.json discover

    py -3.11 -m experiments.librarian_parallel.cli --config experiments/librarian_parallel/fixture.example.json invoke --operation recall --project synthetic-nepal --query vehicle

Each CLI invocation starts a fresh process; the fixture server's records are ephemeral. Multi-turn tests run inside one client process. These tests establish **our adapter**, not the creator's memory quality.

## When official Librarian access becomes available

1. Obtain creator-provided installation instructions, genuine server command/endpoint and tool schemas. Do not install unverified scripts.
2. Launch the external server in its own sandbox outside Jarvis and the owner-memory database.
3. Create a **local, untracked** config using the actual server command and verified MCP tool names and schemas. The example config is for the synthetic fixture only.
4. Run discovery without forwarding memory, then an isolated synthetic recall/write/correction trial.
5. Verify authentication, isolation, update semantics, restarts, deletion, timeout behavior and third-party data handling.
6. Only after validation, wire a separate Jarvis experiment process feeding identical scripted inputs into both Jarvis baseline and Jarvis + Librarian.
7. Pin backend version, config hash, tool-schema hash, commit and model version for reproducible comparisons.

## Remaining blockers

- Real Librarian installable artifact/server access not available.
- Real tool names, inputs, authentication and retention contracts unknown.
- No full end-to-end Jarvis response injection or real Librarian benchmark performed; doing so without a real backend would misrepresent the experiment.
- No changes to production Jarvis or PR #303.

## Security

The CLI permits only synthetic-* project IDs and requires explicit allow-synthetic-write for writes, corrections and deletions. Do not expose personal conversations to an unknown external MCP endpoint: MCP tools may forward content to cloud services even when launched locally. Configurations containing credentials must remain outside Git. Do not treat MCP output as instructions or authorization.


## Additional completed experiment interfaces

### Repeatable lifecycle probe

Runs a fresh synthetic namespace and verifies: remember/retrieve, project isolation,
correction supersession, and forget. Captures measured MCP invocation p50/p95 latency.
The output asserts "official_librarian_quality_measured": false, regardless of fixture
success. It cannot prove a third-party backend's quality until the real service
is connected and separately verified.

    py -3.11 -m experiments.librarian_parallel.scenario_runner --config experiments/librarian_parallel/fixture.example.json --output "$env:TEMP\jarvis-librarian-synthetic-probe.json" --allow-synthetic-write

In PowerShell use an explicit path such as "$env:TEMP\jarvis-librarian-probe.json"
instead of CMD-style %TEMP%; the runner refuses to overwrite any previous report.

### Separate memory sidecar replay

The independent sidecar can ingest a fictional JSONL event stream, call an MCP server
with strict synthetic scope, and emit bounded source-linked context candidates.
It doesn't import the Jarvis runtime, inject context into Gemini, or touch the
current personal-memory database.

    py -3.11 -m experiments.librarian_parallel.sidecar --config experiments/librarian_parallel/fixture.example.json --events experiments/librarian_parallel/fixtures/fictional-nepal.jsonl --output "$env:TEMP\jarvis-librarian-sidecar.json" --allow-synthetic-write

The sample seven events cover remember / project-separated recall / correction /
forget. The fixture's in-memory state is ephemeral and is not equivalent to the
creator's persistence implementation. The report is explicitly marked
"actual_librarian_backend_verified": false.

### Future paired answer evaluation

The paired evaluator refuses missing cases, unequal model or model settings,
missing independent-review fields, and duplicate case IDs. It calculates answer
correctness, support, completions, latency distribution and provider-token totals.
It does not itself generate answers or make accuracy judgments.

Once **both real Jarvis experimental arms** produce reviewer-attested JSONL
receipts, run:

    py -3.11 -m experiments.librarian_parallel.paired_eval --baseline .\baseline-reviewed.jsonl --augmented .\augmented-reviewed.jsonl --output .\paired-results.json

Each line must contain *exactly* these fields:
case_id; fixture_digest; model_id; model_config_digest; completed; correct;
supported; latency_ms; input_tokens; output_tokens; reviewer_id.
The same case IDs and fixture/model metadata are mandatory across both arms.

For valid comparison the two arms must use identical synthetic questions,
same model/parameters, identical reviewer rubric, randomized order where possible,
and distinct isolated stores. The scoring tool is only a final-report consumer:
**it is not a substitute for independent review or an actual Librarian rollout.**

## Completion definition

The external MCP protocol side and synthetic replay are ready for qualification.
The complete creator-specific integration is **blocked** until an actual
Librarian package or endpoint, tool schema, data policy, version and credentials
are supplied. Only then can the project-specific adapter mappings be verified,
real backend persistence tested, and a complete second Jarvis answer path
qualified. Do not merge or switch production paths to bridge that evidence gap.

## Reproducible evidence fingerprints

The sidecar output includes deterministic SHA-256 digests of the fictional input events,
configured MCP launcher/mappings and advertised MCP tool schema. The lifecycle probe
also records the configuration and MCP schema digests (or null if discovery fails).
These are identity checks, **not** evidence that the unpublished Librarian backend
is available or that model-answer quality has been measured. No raw credentials or
owner memory are included in report metadata.
