# Detached, exact-commit lab. Does not install packages or change the active checkout.
[CmdletBinding()]
param(
    [string]$RepoRoot = "E:\Jarvis\App",
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$Commit,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Model,
    [string]$MachineProfile = ""
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$git = (Get-Command git -ErrorAction Stop).Source
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python -PathType Leaf)) {
    throw "Installed Jarvis Python not found; no packages were installed."
}
& $git -C $RepoRoot fetch origin feat/semantic-context-reducer-20261029
if ($LASTEXITCODE -ne 0) { throw "Feature fetch failed." }
& $git -C $RepoRoot cat-file -e ($Commit + '^{commit}')
if ($LASTEXITCODE -ne 0) { throw "Exact commit unavailable." }
$lab = Join-Path $env:TEMP ("jarvis-semantic-live-" + [guid]::NewGuid().ToString("N"))
$source = Join-Path $lab "source"
$profile = Join-Path $lab "profile"
New-Item -ItemType Directory -Path $lab | Out-Null
& $git -C $RepoRoot worktree add --detach $source $Commit
if ($LASTEXITCODE -ne 0) { throw "Isolated checkout creation failed." }
$oldPath = $env:PYTHONPATH
$oldSite = $env:PYTHONNOUSERSITE
try {
    $env:PYTHONPATH = Join-Path $source "src"
    $env:PYTHONNOUSERSITE = "1"
    Write-Host "Exact source: $Commit"
    Write-Host "Lab: $lab"
    Write-Host "Close the normal Jarvis voice process before using the microphone."
    $arguments = @("-m", "jarvis.voice.semantic_smoke_lab", "--lab-root", $profile, "--model", $Model)
    if ($MachineProfile) { $arguments += @("--profile", $MachineProfile) }
    Push-Location $source
    try {
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw "Voice smoke exited with an error; retain lab logs." }
    }
    finally { Pop-Location }
}
finally {
    $env:PYTHONPATH = $oldPath
    $env:PYTHONNOUSERSITE = $oldSite
    Write-Host "Lab retained: $lab"
}
