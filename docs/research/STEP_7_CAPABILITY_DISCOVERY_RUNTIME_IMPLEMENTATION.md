# Step 7 Capability Discovery Runtime — Research-Backed Implementation

## Status

Implementation slice authorized by owner on 2026-09-09 after a fresh technology review.

This document records the bounded architecture implemented in the first Step-7 capability-runtime slice. It does **not** authorize browser control, file writes, external communication, arbitrary shell execution, device control, or voice action wiring.

## Technology decision

JARVIS must not hardcode one Python function for every sentence or workflow the owner may request. The durable architecture is a provider-neutral capability resolver that prefers mature semantic/native tools, then structured specialist automation, and only later visual Computer Use when no better substrate exists.

Target preference order:

1. semantic/native capability: Windows ODR/MCP, Windows App Actions, app/native APIs;
2. structured specialist automation: Playwright for web, Microsoft `winapp`/UIA for interactive Windows apps;
3. visual Computer Use fallback: Gemini/OpenAI/future provider;
4. human when safe automation cannot proceed.

Research basis:

- Microsoft documents MCP on Windows and the Windows On-Device Agent Registry (ODR) as the standard discovery surface for registered MCP servers, with user/admin control and auditability. The official MCP host quickstart uses `odr.exe list`, which returns JSON for discovery.
  - https://learn.microsoft.com/windows/ai/mcp/overview
  - https://learn.microsoft.com/windows/ai/mcp/quickstart-mcp-host
- Windows App Actions expose app-defined atomic operations through the Windows action catalog and can be discovered with `ActionCatalog.GetAllActions` / `GetActionsForInputs`. They are a future semantic capability source for JARVIS rather than something JARVIS should recreate per app.
  - https://learn.microsoft.com/windows/ai/app-actions/
  - https://learn.microsoft.com/windows/ai/app-actions/actions-consume
- Microsoft `winapp` exposes `--cli-schema` specifically as machine-readable JSON for tooling, scripting and LLM integration. JARVIS can therefore discover the installed UI automation surface rather than hardcoding every `winapp ui` verb.
  - https://github.com/microsoft/winappCli/blob/main/docs/cli-schema.json
- Microsoft Playwright MCP provides structured browser automation through accessibility snapshots and MCP tools rather than screenshots/coordinate guessing. Browser execution remains a later roadmap step, but the capability resolver must be able to host it when that step becomes active.
  - https://github.com/microsoft/playwright-mcp
- Microsoft UFO²/UFO³ validates the hybrid native-API + GUI pattern, but adopting its full HostAgent/AppAgent reasoning loop would duplicate JARVIS's conversational brain, authority, memory and provider architecture.

## Bounded implementation in this slice

This slice implements a provider-neutral **capability discovery and resolution catalog** only.

Initial discovery sources:

- `WinAppCliSchemaSource`: shell-free `winapp --cli-schema` discovery. It imports only the `ui` command family metadata and does not execute discovered UI actions.
- `WindowsOdrSource`: shell-free `odr.exe list` discovery when the OS exposes ODR. It imports registered MCP server metadata only; it does not launch, connect to, or call server tools in this slice.

The resolver:

- preserves source identity and provenance;
- normalizes capability identities without assigning authority from descriptions;
- deduplicates deterministic source/capability identities;
- remains useful when one source is unavailable or fails;
- exposes a catalog suitable for future capability selection without granting execution permission;
- does not invent a second permission system;
- treats discovered descriptions/manifests as untrusted metadata.

## Security invariants

- Discovery subprocesses use argument arrays with `shell=False`.
- Discovery is read-only.
- No discovered command line is executed merely because it appears in metadata.
- No MCP server is launched or connected to in this slice.
- No discovered metadata can alter identity, authority, memory, policy, provider selection, or execution scope.
- All discovered descriptors have `execution_enabled = false` in this slice.
- Any future execution must create an existing `ActionProposal`, pass canonical `AuthorityService`, receive/revalidate a one-time execution permit, and execute through a bounded provider adapter.
- No `run_any_command`, arbitrary PowerShell, arbitrary shell, self-modification, security change, deletion, purchase, communication, install, or account-change capability is exposed.

## Roadmap boundary

Step 7 establishes the common discovery/resolution contract and safe-read expansion. Later roadmap steps may plug additional execution providers into the same contract:

- Step 9: Windows application/device control using native APIs + `winapp` and visual CU fallback;
- Step 10: browser execution using Playwright MCP;
- Step 11+: external app/service connectors;
- Step 16: broader plugin/skill lifecycle.

The discovery contract is intentionally future-facing, but this slice does not pull those later execution powers into Step 7.

## Owner-machine probe

After CI, the bounded owner smoke is:

```powershell
python -m jarvis.capabilities.smoke
```

It only prints discovered source/capability metadata and explicitly reports `execution_attempted: false`.
