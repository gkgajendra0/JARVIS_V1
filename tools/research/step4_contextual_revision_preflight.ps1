#Requires -Version 5.1
<#
Owner-machine offline preflight for Step-4 context-grounded research only.
Runs disposable synthetic SQLite tests. Never starts JARVIS, invokes Gemini,
Qwen, JEV, Hindsight, accesses canonical owner DB, or writes memory.
No dependency installation or repo mutation is performed by this script.

Invoke from any working directory AFTER selecting the research branch:
  powershell -NoProfile -File tools/research/step4_contextual_revision_preflight.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$cwd = Get-Location
$keyNames = @("GOOGLE_API_KEY", "OPENAI_API_KEY", "JEV_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")
$previous = @{}

try {
    if (-not (Test-Path $python)) {
        throw "JARVIS project .venv Python not found; install existing project dependencies first."
    }
    Set-Location $root
    foreach ($name in $keyNames) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }

    $tests = @(
        "tests/test_memory_revision_shadow.py",
        "tests/test_memory_revision_snapshot_shadow.py",
        "tests/test_memory_contextual_revision_shadow.py"
    )
    Write-Host "Running offline synthetic Step-4 contextual memory checks."
    & $python -m pytest -q @tests
    if ($LASTEXITCODE -ne 0) { throw "Offline synthetic contextual tests failed." }

    $files = @(
        "src/jarvis/memory/revision_shadow.py",
        "src/jarvis/memory/revision_snapshot_shadow.py",
        "src/jarvis/memory/revision_proposal_shadow.py",
        "src/jarvis/memory/contextual_extractors.py",
        "src/jarvis/memory/contextual_revision_shadow.py",
        "src/jarvis/memory/contextual_retrieval_shadow.py",
        "src/jarvis/memory/contextual_control_shadow.py"
    ) + $tests
    & $python -m ruff check @files
    if ($LASTEXITCODE -ne 0) { throw "Offline synthetic contextual lint failed." }
    & $python -m ruff format --check @files
    if ($LASTEXITCODE -ne 0) { throw "Offline synthetic contextual formatting failed." }

    Write-Host "PASS: Step-4 synthetic memory integration. Zero provider calls and zero production memory writes."
}
finally {
    foreach ($name in $keyNames) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
    }
    Set-Location $cwd
}
