param(
    [string]$Model = "gpt-6-astra",
    [double]$CompressionRate = 0.5,
    [ValidateSet("cpu", "cuda")]
    [string]$Device = "cpu",
    [switch]$SkipDependencyInstall,
    [switch]$SkipLiveBenchmark
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
$benchmark = Join-Path $repo "tools\research\c6_context_owner_acceptance.py"
$caseId = "research_requires_reresolution_after_new_evidence"

Set-Location $repo

Write-Host "================================================="
Write-Host "C6 LLMLINGUA-2 OWNER ACCEPTANCE"
Write-Host "================================================="

if (-not (Test-Path $python)) {
    throw "JARVIS virtual environment Python not found at $python"
}

if (git status --porcelain) {
    throw "Working tree is not clean. Preserve local work before acceptance."
}

$branch = (git branch --show-current).Trim()
if ($branch -ne "feat/development-engine-control-plane") {
    throw "Run this acceptance only from feat/development-engine-control-plane."
}

$head = (git rev-parse HEAD).Trim()
Write-Host "Branch : $branch"
Write-Host "HEAD   : $head"
Write-Host "Device : $Device"
Write-Host "Rate   : $CompressionRate"
Write-Host ""

if (-not $SkipDependencyInstall) {
    Write-Host "=== INSTALL REVIEWED OPTIONAL COMPRESSOR ==="
    & $python -m pip install -e ".[context-compression]"
    if ($LASTEXITCODE -ne 0) {
        throw "Optional context-compression dependency installation failed."
    }
    Write-Host ""
}

$short = $head.Substring(0, [Math]::Min(8, $head.Length))
$preflightReport = Join-Path $env:TEMP "jarvis_c6_llmlingua_preflight_$short.json"
$liveReport = Join-Path $env:TEMP "jarvis_c6_llmlingua_live_$short.json"

Write-Host "=== LOCAL ZERO-CHATGPT PREFLIGHT ==="
Write-Host "The first run may download the pinned LLMLingua-2 model."
Write-Host ""

$preflightArgs = @(
    "--llmlingua-fixture-preflight",
    "--llmlingua-rate", [string]$CompressionRate,
    "--llmlingua-device", $Device,
    "--llmlingua-case-id", $caseId
)
$preflightLines = & $python $benchmark @preflightArgs

$preflightExit = $LASTEXITCODE
$preflightText = $preflightLines -join [Environment]::NewLine
$preflightText | Set-Content $preflightReport -Encoding UTF8

if ($preflightExit -eq 1) {
    throw "LLMLingua preflight failed to execute. See $preflightReport"
}

$preflight = $preflightText | ConvertFrom-Json
$pre = $preflight.llmlingua_fixture_preflight

if ($preflight.model_api_called -ne $false) {
    throw "Preflight unexpectedly called ChatGPT."
}
if ($preflight.production_routing_mutated -ne $false) {
    throw "Preflight unexpectedly changed production routing."
}
if ($pre.preflight_ready -ne $true) {
    throw "LLMLingua preflight is not ready. See $preflightReport"
}
if ($pre.all_fixture_cases_reduced -ne $true) {
    throw "LLMLingua did not reduce the selected full-history fixture."
}
if ($pre.all_full_history_payloads_beat_current -ne $true) {
    throw "Compressed full history is not smaller than the current model payload."
}
if ($pre.actions_executed -ne $false) {
    throw "Preflight unexpectedly executed a Work action."
}
if ($pre.paid_fallback_enabled -ne $false) {
    throw "Preflight unexpectedly enabled paid fallback."
}
if ($pre.provider_circuit_updated -ne $false) {
    throw "Preflight unexpectedly changed the provider circuit."
}
if ($pre.c6_apply_decision_equivalence_proven -ne $false) {
    throw "Preflight must never promote C6 APPLY."
}

Write-Host "PREFLIGHT PASS - zero ChatGPT-plan calls."
Write-Host "Library revision : $($pre.compressor_library_revision)"
Write-Host "Model revision   : $($pre.compressor_model_revision)"
Write-Host "Torch             : $($pre.runtime_dependency_versions.torch)"
Write-Host "Transformers      : $($pre.runtime_dependency_versions.transformers)"

if ($pre.runtime_dependency_versions.torch -ne "2.13.0") {
    throw "Owner acceptance requires the approved torch==2.13.0 runtime."
}
if ($pre.runtime_dependency_versions.transformers -ne "5.16.1") {
    throw "Owner acceptance requires the approved transformers==5.16.1 runtime."
}
foreach ($item in $pre.planned_cases) {
    Write-Host ("Case             : {0}" -f $item.case_id)
    Write-Host ("History steps     : {0}" -f $item.full_history_steps)
    Write-Host ("Current steps     : {0}" -f $item.current_recent_steps)
    Write-Host ("Current chars     : {0}" -f $item.current_chars)
    Write-Host ("Full-history chars: {0}" -f $item.full_history_chars)
    Write-Host ("Compressed chars  : {0}" -f $item.compressed_chars)
    Write-Host ("Full reduction    : {0}%" -f $item.reduction_percent)
    Write-Host (
        "Vs current         : {0}%" -f $item.compressed_vs_current_reduction_percent
    )
    Write-Host ("Candidate strings : {0}" -f $item.candidate_strings)
    Write-Host ("Compressed strings: {0}" -f $item.compressed_strings)
    Write-Host ("Compressor latency: {0} ms" -f $item.compression_latency_ms)
}
Write-Host "Preflight report : $preflightReport"
Write-Host ""

if ($SkipLiveBenchmark) {
    Write-Host "LIVE BENCHMARK SKIPPED BY REQUEST."
    exit 0
}

Write-Host "=== LIVE LEGACY VS COMPRESSED PAIR ==="
Write-Host "Maximum ChatGPT-plan calls: TWO."
Write-Host "No Work action is executed and production settings remain unchanged."
Write-Host ""

$liveArgs = @(
    "--llmlingua-fixture-benchmark",
    "--model", $Model,
    "--llmlingua-rate", [string]$CompressionRate,
    "--llmlingua-device", $Device,
    "--llmlingua-case-id", $caseId
)
$liveLines = & $python $benchmark @liveArgs

$liveExit = $LASTEXITCODE
$liveText = $liveLines -join [Environment]::NewLine
$liveText | Set-Content $liveReport -Encoding UTF8

if ($liveExit -eq 1) {
    throw "LLMLingua live benchmark failed to execute. See $liveReport"
}

$live = $liveText | ConvertFrom-Json
$bench = $live.llmlingua_fixture_benchmark

if ($bench.model_calls -gt 2) {
    throw "Benchmark unexpectedly used more than two model calls."
}
if ($bench.fixture_cases -ne 1) {
    throw "Expected exactly one research fixture pair."
}
if ($bench.actions_executed -ne $false) {
    throw "Benchmark unexpectedly executed a Work action."
}
if ($bench.production_routing_mutated -ne $false) {
    throw "Benchmark unexpectedly changed production routing."
}
if ($bench.paid_fallback_enabled -ne $false) {
    throw "Benchmark unexpectedly enabled paid fallback."
}
if ($bench.provider_circuit_updated -ne $false) {
    throw "Benchmark unexpectedly changed provider circuit state."
}
if ($live.c6_apply_decision_equivalence_proven -ne $false) {
    throw "LLMLingua benchmark must not automatically promote C6 APPLY."
}

$case = $bench.cases[0]

Write-Host "================================================="
Write-Host "C6 LLMLINGUA RESULT"
Write-Host "================================================="
Write-Host "case                       : $($case.case_id)"
Write-Host "equivalent                 : $($case.equivalent)"
Write-Host "action_equal               : $($case.action_equal)"
Write-Host "parameters_equal           : $($case.parameters_equal)"
Write-Host "goal_complete_equal        : $($case.goal_complete_equal)"
Write-Host "needs_owner_equal          : $($case.needs_owner_equal)"
Write-Host "owner_question_equal       : $($case.owner_question_equal)"
Write-Host "baseline_scope             : $($case.baseline_scope)"
Write-Host "full_history_steps         : $($case.full_history_steps)"
Write-Host "current_recent_steps       : $($case.current_recent_steps)"
Write-Host "full_context_reduction %   : $($case.reduction_percent)"
Write-Host "compressed_vs_current %    : $($case.compressed_vs_current_reduction_percent)"
Write-Host "beats_current_payload      : $($case.beats_current_payload)"
Write-Host "provider_tokens_reduced    : $($case.provider_input_tokens_reduced)"
Write-Host "provider_token_reduction % : $($case.provider_input_token_reduction_percent)"
Write-Host "compression_latency_ms     : $($case.compression_latency_ms)"
Write-Host ""
Write-Host "Full-context parameters:"
$case.full_context_parameters | ConvertTo-Json -Depth 20
Write-Host "Compressed parameters:"
$case.compressed_parameters | ConvertTo-Json -Depth 20
Write-Host ""
Write-Host "Live report: $liveReport"
Write-Host ""

if (
    $bench.all_fixture_cases_equivalent -ne $true -or
    $bench.all_full_history_payloads_beat_current -ne $true -or
    $bench.all_provider_input_tokens_reduced -ne $true -or
    $case.parameters_equal -ne $true -or
    $case.beats_current_payload -ne $true
) {
    Write-Host "RESULT: INCOMPLETE - compressor is not eligible for promotion."
    exit 2
}

Write-Host "RESULT: PASS - compressed full history preserved strict semantics, beat the current payload size, and reduced real provider input tokens versus full history."
Write-Host "Production remains unchanged; this result is evidence only."
exit 0
