# Phase 9 — Owner-Requested Capability Acquisition Research

## Status

**FOUNDATION + TECHNOLOGY RESEARCH COMPLETE — ARCHITECTURE NOT YET OWNER-APPROVED — 2026-09-27**

Phase 9 is the first complete **capability-to-build-capabilities** milestone.

Target behavior:

> Owner: "JARVIS, I want to control this TV through you. Get that capability."

JARVIS should determine whether the capability already exists, discover the best available integration path, research it, propose an architecture, wait for required owner approval, implement/adapt it in isolation, handle dependencies/secrets through the accepted substrate, verify it, perform owner-assisted real-world acceptance where needed, package it through Phase 8, promote it through Phase 7, observe it, and retain verified EngineeringKnowledge.

The Phase-9 exit criterion from the accepted master plan remains:

**The owner can acquire one real new capability without manually researching, coding, managing Git, or debugging the candidate.**

This document records technology research and dispositions only. It does not authorize implementation.

---

## 1. Repository boundary

Phase 9 must be thin. Phases 3–8 already provide most of the hard machinery:

- Phase 3: durable EngineeringChange / WorkItem lifecycle, research, architecture gate, isolated DEVELOPMENT work, owner input and restart recovery;
- Phase 4: governed research/diagnostic model routing;
- Phase 5: dependency acquisition, ArtifactStore, provenance, SecretBroker, SandboxProfile, bounded discovery and CapabilityManifest;
- Phase 6: exact-revision code inspection, isolated development, candidate verification and protected-surface enforcement;
- Phase 7: exact PR/CI/release promotion, immutable release identity, production observation and rollback;
- Phase 8: immutable capability package contracts, package registry, compatibility, health, lifecycle reconciliation, Authority-bound enable/disable/version switching and rollback.

Therefore Phase 9 must **not** create another task engine, agent control plane, approval system, package registry, secret store, sandbox, Git promotion path, health system or durable work database.

The missing layer is acquisition intelligence:

1. interpret the owner-requested capability;
2. decide whether it already exists;
3. resolve the best reusable source/integration;
4. normalize evidence and risk;
5. choose adapt/wrap/generate/build;
6. hand the approved plan into the existing engineering lifecycle;
7. produce a Phase-8 PACKAGE_MANAGED capability.

---

## 2. Core research conclusion

The correct Phase-9 strategy is:

**wrap existing integration -> generate from a machine-readable contract -> adapt an SDK/library -> write custom code only as the last resort.**

JARVIS should not treat "generate source code" as the default way to gain a capability.

The largest efficiency gain comes from standardized integration ecosystems and protocols, not from making a larger autonomous coding agent.

Recommended resolution order:

1. existing JARVIS capability/package;
2. existing trusted local integration/broker;
3. MCP server/tool surface;
4. machine-readable API contract such as OpenAPI or AsyncAPI;
5. mature official/vendor SDK or protocol library;
6. isolated generated adapter;
7. bespoke implementation only when no reusable route exists.

---

## 3. Technology dispositions

| Technology | Phase-9 disposition | Why |
| --- | --- | --- |
| Model Context Protocol (MCP) 2026-07-28 + official Python SDK v2 | **ADOPT** | Standard discovery/invocation boundary for existing tools and services; Python SDK supports clients/servers, stdio and Streamable HTTP. |
| Official MCP Registry | **ADAPT AS DISCOVERY SOURCE** | Useful searchable ecosystem, but registry metadata/discovery is not trust or execution Authority. |
| Agent Client Protocol (ACP) + official Python SDK | **ADOPT AS OPTIONAL DEVELOPMENT-WORKER PROTOCOL** | Lets JARVIS drive replaceable coding agents over a standard JSON-RPC/stdio contract instead of hard-wiring one coding framework. |
| OpenHands Software Agent SDK / Agent Server | **BENCHMARK / OPTIONAL BACKEND** | Mature MIT-licensed coding-agent runtime and ACP bridge; must remain a replaceable worker behind JARVIS orchestration. |
| mini-SWE-agent | **BENCHMARK AS LIGHTWEIGHT ALTERNATIVE** | Very small coding loop and model flexibility; useful comparison before accepting a heavier development runtime. |
| A2A / Agent2Agent | **DEFER** | Useful for peer autonomous agents, but Phase 9 already has DBOS/WorkItem/EngineeringChange orchestration; adopting A2A as the control plane would duplicate accepted truth. |
| Home Assistant integration ecosystem + WebSocket API | **ADAPT FOR SMART-HOME / DEVICE ACQUISITION** | Converts many vendor-specific devices/services into stable entity/action semantics; especially valuable for the TV/device reference scenario. |
| OpenAPI | **ADOPT AS PREFERRED REST CONTRACT SOURCE** | Machine-readable API semantics enable client generation, test generation and bounded adapter construction. |
| OpenAPI Generator | **ADAPT FOR CLIENT/STUB GENERATION** | Avoids manually writing repetitive REST clients when a good contract exists. Generated code still requires sandboxed verification. |
| AsyncAPI | **ADOPT WHEN EVENT CONTRACT EXISTS** | Equivalent contract-first path for event/message-driven integrations; do not make it a hard dependency before a real use case. |
| FastMCP/OpenAPI-to-MCP frameworks | **OPTIONAL BOOTSTRAP ONLY** | Useful for rapidly exposing an OpenAPI surface as MCP, but full automatic mirroring creates noisy/oversized tool surfaces. JARVIS should curate the final operations. |
| Extism / WebAssembly | **DEFER AS FUTURE UNTRUSTED PLUGIN BACKEND** | Strong capability-style isolation and Python host SDK; useful later for third-party pure logic. Existing Phase-5 isolation is better aligned with Phase-9 v1, and Extism plugin PDKs do not directly cover Python. |
| SWE-ReX / another standalone execution sandbox | **DO NOT ADOPT NOW** | Phase 5 already owns JARVIS sandbox, dependency and provenance semantics. A second sandbox truth would add complexity. |
| OCI/ORAS | **CONDITIONAL** | Good transport/content-addressing if Phase 9 begins distributing external capability artifacts. Do not run new registry infrastructure merely for local source-built packages. |
| Sigstore/Cosign | **CONDITIONAL, STRONGLY PREFERRED FOR EXTERNAL SIGNED ARTIFACTS** | Provides identity-bound signature, timestamp and transparency-log evidence. |
| TUF | **DEFER UNTIL A LONG-LIVED REMOTE CAPABILITY REPOSITORY EXISTS** | Solves rollback/freeze/mix-and-match/update attacks; excessive for the first source-built/local Phase-9 flow. |
| LangGraph / CrewAI / AutoGen-style orchestration replacement | **REJECT FOR PHASE 9 CONTROL PLANE** | JARVIS already owns durable work, Authority, memory, package truth and promotion. Replacing them would regress accepted architecture. |

---

## 4. MCP: primary reusable integration fabric

The current MCP line is materially more suitable than early MCP versions.

The 2026-07-28 specification makes the modern HTTP path stateless, carries protocol/client metadata per request, makes tool/resource/prompt listing cacheable, and standardizes deterministic tool discovery. Official Python SDK v2 supports current and older MCP revisions and provides a first-class client for Streamable HTTP, stdio and in-memory testing.

Phase-9 recommendation:

- create a JARVIS-owned MCP client/broker boundary;
- treat discovered MCP servers/tools as **candidate capabilities**, not automatically trusted capabilities;
- normalize selected tools into JARVIS capability operations;
- allow only approved tool subsets;
- bind remote credentials through SecretBroker;
- bind network destinations through Sandbox/Authority policy;
- keep tool annotations untrusted unless the server/source is trusted;
- never allow registry metadata to become shell execution instructions;
- persist source/version/digest/provenance evidence before package admission.

The Official MCP Registry is useful for discovery, but registry presence is not sufficient evidence for installation or execution.

For local MCP servers, JARVIS should prefer exact pinned dependencies/artifacts through Phase 5 and launch them under an accepted sandbox/process boundary. For remote Streamable HTTP MCP servers, no third-party code runs in the JARVIS process, but credentials, network scope and state-changing tools still require the normal Authority model.

---

## 5. ACP: replaceable coding worker, not a new control plane

ACP is now a practical interoperability layer for coding agents.

The official Python SDK can programmatically spawn ACP agents and provides typed schemas, stdio JSON-RPC plumbing, session updates and permission callbacks. ACP-compatible ecosystems already include Codex-class, Gemini CLI, Claude-class and other coding agents. OpenHands can itself delegate to ACP agents.

This is valuable because Phase 9 should not permanently encode "the coding worker is OpenHands" or "the coding worker is vendor X".

Recommended design:

```text
JARVIS EngineeringChange / DEVELOPMENT
        |
        v
JARVIS DevelopmentWorkerBackend
        |
        +---- existing native worker
        |
        +---- ACP backend
                 |
                 +---- Codex-compatible agent
                 +---- Gemini CLI
                 +---- OpenHands / other ACP agent
```

However ACP **does not replace Phase-5 containment**.

ACP exposes permission and client capability mechanisms, but its protocol does not guarantee that every agent will request permission before sensitive writes/terminal work. External coding agents may manage their own tools. Therefore any ACP worker used by JARVIS must be started inside the exact approved worktree/sandbox boundary with only the filesystem, network, credentials and commands JARVIS intentionally grants.

ACP is an interoperability protocol, not Authority.

Before selecting a default backend, Phase 9 should run a small JARVIS-specific benchmark comparing the current DEVELOPMENT worker, an ACP backend and at least one mature coding-agent backend on identical bounded adapter tasks. Measure verified completion, regressions, owner interventions, tokens/cost, elapsed time and policy violations.

---

## 6. Home Assistant: high-leverage device adapter ecosystem

For device/smart-home requests, building a vendor adapter from scratch should be the last option.

Home Assistant already normalizes many external devices/services into domain entities, states, events and actions. Its WebSocket API provides authenticated state/event streaming and command exchange.

Phase-9 recommendation:

- add Home Assistant as an optional `CapabilitySourceAdapter`, not as a mandatory JARVIS dependency;
- if the requested physical capability already exists as a suitable Home Assistant integration, JARVIS should wrap that normalized surface;
- expose only owner-approved entities/actions as JARVIS capability operations;
- keep Home Assistant credentials in SecretBroker;
- preserve JARVIS Authority even if Home Assistant itself would permit the action.

For the documented TV example this can eliminate brand-specific API engineering when the TV is already supported by Home Assistant.

---

## 7. Contract-first API acquisition

When a service publishes a machine-readable contract, JARVIS should use it before asking a model to invent an API client.

### OpenAPI

Use the OpenAPI document as evidence for:

- operation discovery;
- request/response schemas;
- authentication requirements;
- deterministic client generation;
- contract tests;
- bounded operation selection.

OpenAPI Generator or another mature generator may produce the low-level client. The generated output remains untrusted candidate source and must be built/tested through Phase 5/6.

Do **not** blindly expose every OpenAPI endpoint as an LLM tool. A capability package should contain a small semantic operation set matching the owner goal.

### AsyncAPI

Use the same policy for event-driven/message APIs when an AsyncAPI contract exists. It is a source for schemas, channels and generated plumbing, not execution Authority.

---

## 8. Generated/custom code fallback

Only after reusable routes fail should JARVIS generate a custom adapter.

The accepted Phase-6 DEVELOPMENT substrate already supplies most of this path:

- isolated worktree;
- exact source revision;
- typed actions;
- tests;
- sandboxed execution;
- protected-surface policy;
- clean commit/candidate evidence.

Phase 9 should add capability-specific acceptance requirements rather than replace the development substrate.

Examples:

- operation-semantic tests;
- unavailable dependency/device behavior;
- credential redaction;
- disconnect/reconnect;
- idempotency where relevant;
- state-changing negative controls;
- owner-assisted physical verification when software cannot independently observe the real result.

---

## 9. Supply-chain decision

Phase 9 must separate **discovery** from **trust**.

A registry entry, GitHub repository, npm/PyPI package, MCP server card or model recommendation is evidence that something exists. It is not permission to install or run it.

Initial Phase-9 preference:

1. reuse code already in the accepted JARVIS release;
2. prefer remote standardized APIs/MCP where local code installation is unnecessary;
3. when local dependencies are needed, use Phase-5 exact dependency resolution, hashes, ArtifactStore and offline recreation;
4. when external prebuilt capability artifacts become a real requirement, use OCI/ORAS-style immutable transport plus Sigstore/Cosign verification/provenance;
5. add TUF only when JARVIS actually depends on a persistent remote repository/update channel.

Do not invent a JARVIS-specific signing ecosystem.

---

## 10. Proposed Phase-9 acquisition-source interface

Architecture should formalize a replaceable source boundary roughly equivalent to:

```text
CapabilitySourceAdapter
    discover(owner_goal, environment_snapshot)
        -> AcquisitionCandidate[]

AcquisitionCandidate
    source_kind
    stable_source_identity
    candidate_version
    immutable_digest/evidence
    supported_operations
    required_dependencies
    required_secrets/scopes
    network/device requirements
    license/provenance
    trust class
    expected adaptation path
    verification requirements
```

Expected source adapters:

- ExistingCapabilitySource
- HomeAssistantCapabilitySource
- McpRegistryCapabilitySource
- OpenApiCapabilitySource
- AsyncApiCapabilitySource
- LibrarySdkCapabilitySource
- CustomBuildCapabilitySource

These are acquisition sources only. They must not become independent package registries.

---

## 11. Proposed orchestration shape

The Phase-9 control path should remain:

```text
owner capability goal
        |
        v
capability check / duplicate detection
        |
        v
source resolver
        |
        v
normalized AcquisitionCandidate set
        |
        v
evidence/risk/fit comparison
        |
        v
architecture proposal
        |
        v
existing owner architecture gate
        |
        v
adapt / generate / build through existing DEVELOPMENT substrate
        |
        v
Phase-5 dependency / secret / sandbox / provenance verification
        |
        v
capability-specific automated verification
        |
        v
owner-assisted acceptance only where real-world evidence is required
        |
        v
Phase-8 CapabilityPackageV1 admission
        |
        v
Phase-7 promotion / release observation / rollback
        |
        v
EngineeringKnowledge
```

DBOS/WorkItem and EngineeringChange remain the durable orchestration truth.

---

## 12. Efficiency rules

Phase 9 should optimize for runtime simplicity, not maximum agent activity.

1. Use model reasoning during acquisition/research/design, not for every normal invocation.
2. Once a capability is installed, routine execution should use deterministic typed routing where possible.
3. Cache source metadata and machine-readable schemas with explicit freshness.
4. Prefer one normalized adapter over many vendor-specific prompt recipes.
5. Avoid copying a large external API into the model context; expose the minimal semantic operation set.
6. Prefer remote protocol calls when they safely avoid local package installation.
7. Do not run coding agents when a verified existing integration already satisfies the owner goal.
8. Keep all frameworks replaceable behind JARVIS-owned interfaces.

---

## 13. Security invariants for architecture

The architecture proposal must preserve these rules:

1. owner request is intent, not unrestricted execution Authority;
2. discovery metadata is never trust;
3. external server/tool descriptions are untrusted input;
4. no model-generated shell command becomes automatically authorized;
5. no unpinned `pip install`, `npm install`, `npx -y` or equivalent production acquisition path;
6. local MCP/ACP/generated code runs only inside an accepted execution boundary;
7. credentials are requested/scoped through SecretBroker and never embedded in package metadata;
8. source adapters cannot broaden network/device/filesystem scope;
9. package admission cannot weaken Phase-5 manifest constraints;
10. every Phase-9-created capability is PACKAGE_MANAGED;
11. package registration alone does not enable execution;
12. Phase 7 remains the only source-code production promotion path;
13. Phase 8 remains canonical capability lifecycle truth;
14. JARVIS does not use an external agent framework as canonical work, Authority, memory, package or promotion truth.

---

## 14. Architecture questions remaining

Research is sufficient to proceed to Phase-9 architecture, but the architecture proposal must make four explicit choices:

### A. Runtime external-tool model

Define whether selected MCP/remote integrations are represented as trusted JARVIS providers that proxy to the external system, and exactly how their identity/version/health maps into CapabilityPackageV1.

### B. Acquisition trust classes

Define deterministic trust/evidence tiers such as accepted-release, owner-configured local system, verified official remote API, signed external artifact, and unverified candidate. The model must not assign these classes by confidence alone.

### C. Development-worker backend

Keep the current worker as baseline and define a narrow backend interface. Pilot ACP as a replaceable backend and benchmark it before choosing a default.

### D. Real-world acceptance target

Use one genuine owner-requested capability with external state, preferably the documented device/TV pattern if suitable hardware/integration is available. Acceptance must prove the complete lifecycle rather than a synthetic code-only demo.

---

## 15. Research disposition

**Proceed to Phase-9 architecture. Do not start implementation yet.**

The proposed architecture should introduce only the acquisition-specific contracts/coordinator/source adapters/brokers required to connect the owner goal to the already accepted EngineeringChange -> DEVELOPMENT -> verification -> Phase 8 package -> Phase 7 promotion path.

No external framework should replace the JARVIS control plane.

---

## References

Primary current sources reviewed for this research:

- MCP specification / tools / transports: https://modelcontextprotocol.io/
- Official MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Official MCP Registry: https://registry.modelcontextprotocol.io/
- Agent Client Protocol: https://agentclientprotocol.com/
- ACP Python SDK: https://github.com/agentclientprotocol/python-sdk
- OpenHands Software Agent SDK: https://github.com/OpenHands/software-agent-sdk
- A2A Protocol: https://a2a-protocol.org/
- Home Assistant integration architecture: https://developers.home-assistant.io/docs/architecture_components/
- Home Assistant WebSocket API: https://developers.home-assistant.io/docs/api/websocket/
- OpenAPI Initiative: https://www.openapis.org/
- OpenAPI Generator: https://openapi-generator.tech/
- AsyncAPI: https://www.asyncapi.com/
- Extism: https://extism.org/
- Sigstore/Cosign: https://docs.sigstore.dev/
- The Update Framework: https://theupdateframework.io/
