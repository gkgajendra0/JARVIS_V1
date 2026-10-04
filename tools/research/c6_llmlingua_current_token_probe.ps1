param(
    [string]$Model = "gpt-6-astra",
    [string]$EvidenceReport = ""
)

$ErrorActionPreference = "Stop"

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
$probe = Join-Path $repo "tools\research\c6_llmlingua_current_token_probe.py"

Set-Location $repo

if (-not (Test-Path $python)) {
    throw "JARVIS virtual environment Python not found at $python"
}

if (git status --porcelain) {
    throw "Working tree is not clean. Preserve local work before acceptance."
}

if (-not $EvidenceReport) {
    $EvidenceReport = Join-Path $env:TEMP "jarvis_c6_llmlingua_live_3749bcea.json"
}

if (-not (Test-Path $EvidenceReport)) {
    throw ("Accepted LLMLingua PASS report not found at $EvidenceReport. " + "Supply -EvidenceReport with the saved 3749bcea PASS JSON.")
}

$head = (git rev-parse HEAD).Trim()
$short = $head.Substring(0, [Math]::Min(8, $head.Length))
$outputReport = Join-Path $env:TEMP ("jarvis_c6_llmlingua_current_tokens_" + $short + ".json")

Write-Host "================================================="
Write-Host "C6 CURRENT-PAYLOAD TOKEN PROBE"
Write-Host "================================================="
Write-Host "HEAD            : $head"
Write-Host "Evidence report : $EvidenceReport"
Write-Host "Model           : $Model"
Write-Host ""
Write-Host "This reuses the accepted 3-call PASS evidence."
Write-Host "Maximum new ChatGPT-plan calls: ONE."
Write-Host "No Work action is executed and production settings remain unchanged."
Write-Host ""

$lines = & $python $probe --evidence-report $EvidenceReport --model $Model

$exitCode = $LASTEXITCODE
$text = $lines -join [Environment]::NewLine
$text | Set-Content $outputReport -Encoding UTF8

if ($exitCode -eq 1) {
    throw "Current-payload token probe failed to execute. See $outputReport"
}

$result = $text | ConvertFrom-Json

if ($result.model_calls -ne 1) { throw "Current-payload probe did not use exactly one model call." }
if ($result.actions_executed -ne $false) { throw "Probe unexpectedly executed a Work action." }
if ($result.production_routing_mutated -ne $false) { throw "Probe unexpectedly changed production routing." }
if ($result.paid_fallback_enabled -ne $false) { throw "Probe unexpectedly enabled paid fallback." }
if ($result.provider_circuit_updated -ne $false) { throw "Probe unexpectedly changed provider circuit state." }
if ($result.c6_apply_decision_equivalence_proven -ne $false) { throw "Token probe must never automatically promote C6 APPLY." }

Write-Host "================================================="
Write-Host "C6 CURRENT TOKEN RESULT"
Write-Host "================================================="
Write-Host "case                               : $($result.case_id)"
Write-Host "current_provider_input_tokens      : $($result.current_provider_input_tokens)"
Write-Host "compressed_provider_input_tokens   : $($result.accepted_compressed_provider_input_tokens)"
Write-Host "compressed_beats_current_tokens    : $($result.compressed_beats_current_provider_tokens)"
Write-Host "provider_token_reduction_percent   : $($result.compressed_vs_current_provider_token_reduction_percent)"
Write-Host "current_action_matches_full        : $($result.current_action_matches_prior_full_history)"
Write-Host "current_parameters_match_full      : $($result.current_parameters_match_prior_full_history)"
Write-Host "report                             : $outputReport"
Write-Host ""

if ($result.status -ne "PASS") {
    Write-Host "RESULT: INCOMPLETE - compressed full history did not beat current provider tokens."
    exit 2
}

Write-Host ("RESULT: PASS - accepted compressed full history uses fewer real provider input " + "tokens than today's current payload.")
Write-Host "Production remains unchanged; this result is evidence only."
exit 0
