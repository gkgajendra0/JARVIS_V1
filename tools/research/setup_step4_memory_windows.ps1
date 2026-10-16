#Requires -Version 5.1
<#
Research-only setup: isolated venv plus local contract tests, no inference.
Windows PowerShell 5.1 / Python 3.11. No owner memory is read.
Package installation uses PyPI; it does not call Google/OpenAI models.
#>
[CmdletBinding()]
param([switch] $SkipInstall)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$venvDir = Join-Path $root ".venv-memory-research"
$python = Join-Path $venvDir "Scripts\python.exe"
$originalLocation = Get-Location
$secretEnvNames = @("GOOGLE_API_KEY", "OPENAI_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")
$originalSecrets = @{}

try {
    Set-Location $root
    foreach ($name in $secretEnvNames) {
        $originalSecrets[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    if (-not $SkipInstall) {
        Write-Host "Creating isolated memory research environment (Python 3.11)."
        & py -3.11 -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "Python 3.11 virtual environment creation failed." }
        $deps = @("langmem==0.0.30", "hindsight-client==0.10.3", "pytest>=8,<10", "ruff==0.16.5", "psutil>=6,<8")
        & $python -m pip install --disable-pip-version-check @deps
        if ($LASTEXITCODE -ne 0) { throw "Isolated dependency installation failed." }
    }
    if (-not (Test-Path $python)) {
        throw "Research virtual environment not installed. Run without -SkipInstall."
    }
    Write-Host "Running isolated tests with cloud keys unavailable to test processes."
    $tests = @(
        "tests/test_task_context_shadow.py",
        "tests/test_step4_memory_comparator_adapters.py",
        "tests/test_step4_memory_blind_scorer.py",
        "tests/test_step4_memory_owner_preflight.py"
    )
    & $python -m pytest -q @tests
    if ($LASTEXITCODE -ne 0) { throw "Research tests did not pass." }
    $lintFiles = @(
        "src/jarvis/memory/task_context_shadow.py",
        "tools/research/step4_memory_model_comparators.py",
        "tools/research/step4_hindsight_isolated_probe.py",
        "tools/research/step4_memory_blind_scorer.py",
        "tools/research/step4_memory_owner_preflight.py"
    ) + $tests
    & $python -m ruff check @lintFiles
    if ($LASTEXITCODE -ne 0) { throw "Research lint did not pass." }
    Write-Host "PASS: local tests and lint. 0 memory writes, 0 provider model calls."
    Write-Host ("Research Python: " + $python)
}
finally {
    foreach ($name in $secretEnvNames) {
        [Environment]::SetEnvironmentVariable($name, $originalSecrets[$name], "Process")
    }
    Set-Location $originalLocation
}
