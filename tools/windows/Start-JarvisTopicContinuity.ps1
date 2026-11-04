param(
    [string]$RepoRoot = "E:\Jarvis\App",
    [Parameter(Mandatory = $true)][string]$Commit,
    [string]$LabRoot = "",
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "The installed Jarvis Python environment was not found." }
if ($Commit -notmatch '^[0-9a-f]{40}$') { throw "An exact 40-character commit SHA is required." }
git -C $RepoRoot cat-file -e "${Commit}^{commit}"
if ($LASTEXITCODE -ne 0) { throw "Commit unavailable locally. Fetch the feature branch first." }

if (-not $LabRoot) {
    if ($Resume) { throw "Resume requires the previous LabRoot." }
    $LabRoot = Join-Path $env:TEMP ("jarvis-topic-" + [guid]::NewGuid().ToString("N"))
}
$source = Join-Path $LabRoot "source"
$testProfile = Join-Path $LabRoot "profile"
if ($Resume) {
    $actual = git -C $source rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $actual -ne $Commit) { throw "Resume source does not match the requested commit." }
    $dirty = git -C $source status --porcelain
    if ($LASTEXITCODE -ne 0 -or $dirty) { throw "The isolated source has local changes." }
} else {
    if (Test-Path $LabRoot) { throw "LabRoot exists. Use a new directory, or Resume for an existing continuity lab." }
    git -C $RepoRoot worktree add --detach $source $Commit
    if ($LASTEXITCODE -ne 0) { throw "Isolated checkout creation failed." }
}

$previousPath = $env:PYTHONPATH
$previousSite = $env:PYTHONNOUSERSITE
try {
    $env:PYTHONPATH = Join-Path $source "src"
    $env:PYTHONNOUSERSITE = "1"
    $arguments = @("-m", "jarvis.voice.semantic_continuity_lab", "--lab-root", $testProfile)
    if ($Resume) { $arguments += "--resume-lab" }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Continuity runtime exited with an error. Check the preceding output." }
} finally {
    $env:PYTHONPATH = $previousPath
    $env:PYTHONNOUSERSITE = $previousSite
    Write-Host "Continuity lab: $LabRoot"
    Write-Host "To restart this profile, run this launcher with -Resume -LabRoot '$LabRoot' and the same -Commit."
}
