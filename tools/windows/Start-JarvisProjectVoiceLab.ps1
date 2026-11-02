# Isolated project-memory VOICE lab. Exact local commit only; no fetch, install,
# checkout reset or activation. Shares its lab root with
# Start-JarvisProjectMemoryLab.ps1 at the same commit (use -ResumeLab there).
[CmdletBinding()]
param(
    [string]$RepoRoot = "E:\Jarvis\App",
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$Commit,
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$LabRoot,
    [string]$MachineProfile = "",
    [switch]$ResumeLab,
    [switch]$Baseline,
    # Lab only: keep DPAPI-sealed post-wake audio + per-turn records in this lab.
    [switch]$RecordDiagnostics,
    # A/B only: no session preload; every request calls prepare_project_turn.
    [switch]$ToolOnlyMemory,
    # Decrypt the latest diagnostics run into a local HTML report (no voice run).
    [switch]$DiagnosticsReport,
    # Delete all diagnostics recordings, records and reports of this lab.
    [switch]$CleanupDiagnostics
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$git = (Get-Command git -ErrorAction Stop).Source
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python -PathType Leaf)) { throw "Existing Python unavailable; nothing installed." }
& $git -C $RepoRoot cat-file -e ($Commit + '^{commit}')
if ($LASTEXITCODE -ne 0) { throw "Exact commit is not local. Fetch it explicitly before this launcher; no implicit network retry." }
$resolvedLab = [IO.Path]::GetFullPath($LabRoot)
$source = Join-Path $resolvedLab "source"
$profile = Join-Path $resolvedLab "profile"
if ($DiagnosticsReport -or $CleanupDiagnostics) {
    if ($DiagnosticsReport -and $CleanupDiagnostics) { throw "Choose one diagnostics action." }
    if (-not (Test-Path (Join-Path $profile "project-memory.marker") -PathType Leaf)) { throw "Marked profile unavailable." }
    $action = if ($DiagnosticsReport) { "report" } else { "cleanup" }
    $oldPath = $env:PYTHONPATH
    try {
        $env:PYTHONPATH = Join-Path $source "src"
        $out = & $python -X utf8 -m jarvis.voice.voice_diagnostics $action --lab-root $profile
        if ($LASTEXITCODE -ne 0) { throw "Diagnostics $action failed." }
        Write-Host $out
        if ($DiagnosticsReport) {
            $acceptance = Get-Content (Join-Path (Split-Path $out) "acceptance.json") -Raw | ConvertFrom-Json
            Write-Host ("Acceptance: {0}  (PASS {1} / REVIEW {2} / FAIL {3}; run checks: {4})" -f $acceptance.verdict, $acceptance.counts.PASS, $acceptance.counts.REVIEW, $acceptance.counts.FAIL, ($acceptance.run_review -join ", "))
            foreach ($r in $acceptance.results) { if ($r.verdict -eq "FAIL") { Write-Host ("  FAIL {0}: {1}" -f $r.id, ($r.fail -join ", ")) } }
            Start-Process $out
        }
    } finally { $env:PYTHONPATH = $oldPath }
    return
}
if ($ResumeLab) {
    if (-not (Test-Path (Join-Path $profile "project-memory.marker") -PathType Leaf)) { throw "Marked profile unavailable." }
} else {
    if (Test-Path $resolvedLab) { throw "New lab root must not exist." }
    New-Item -ItemType Directory -Path $resolvedLab | Out-Null
    & $git -C $RepoRoot worktree add --detach $source $Commit
    if ($LASTEXITCODE -ne 0) { throw "Isolated worktree creation failed." }
}
$oldPath = $env:PYTHONPATH
$oldSite = $env:PYTHONNOUSERSITE
try {
    $env:PYTHONPATH = Join-Path $source "src"
    $env:PYTHONNOUSERSITE = "1"
    $arguments = @("-X", "utf8", "-m", "jarvis.voice.project_voice_lab", "--lab-root", $profile, "--source-commit", $Commit)
    if ($MachineProfile) { $arguments += @("--profile", $MachineProfile) }
    if ($ResumeLab) { $arguments += "--resume-lab" }
    if ($Baseline) { $arguments += "--baseline" }
    if ($RecordDiagnostics) { $arguments += "--record-diagnostics" }
    if ($ToolOnlyMemory) { $arguments += "--tool-only-memory" }
    Push-Location $source
    try { & $python @arguments; if ($LASTEXITCODE -ne 0) { throw "Voice lab failed; retain its files." } }
    finally { Pop-Location }
} finally {
    $env:PYTHONPATH = $oldPath
    $env:PYTHONNOUSERSITE = $oldSite
    Write-Host "Isolated voice lab retained: $resolvedLab"
}
