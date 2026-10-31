# Exact local commit only; no fetch, install, checkout reset or activation.
[CmdletBinding()]
param(
    [string]$RepoRoot = "E:\Jarvis\App",
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$Commit,
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Model,
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$LabRoot,
    [string]$MachineProfile = "",
    [switch]$ResumeLab
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
    $arguments = @("-X", "utf8", "-m", "jarvis.voice.project_memory_lab", "--lab-root", $profile, "--model", $Model, "--source-commit", $Commit)
    if ($MachineProfile) { $arguments += @("--profile", $MachineProfile) }
    if ($ResumeLab) { $arguments += "--resume-lab" }
    Push-Location $source
    try { & $python @arguments; if ($LASTEXITCODE -ne 0) { throw "Lab failed; retain its files." } }
    finally { Pop-Location }
} finally {
    $env:PYTHONPATH = $oldPath
    $env:PYTHONNOUSERSITE = $oldSite
    Write-Host "Isolated text lab retained: $resolvedLab"
}
