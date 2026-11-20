# Rehearse a memory migration on isolated copies of the installed database.
# Numbers only; the live database is only read and hashed. Nothing is installed,
# fetched, reset or activated. Run from an elevated or normal PowerShell with
# Jarvis stopped.
#
#   1. Refuses unless -IConfirmJarvisStopped is given AND no Jarvis process is
#      found AND the live database has no -wal/-shm side files.
#   2. Copies memory.db + memory.key.dpapi into <Root>\pristine (kept untouched,
#      marked read-only) and records live hashes before and after.
#   3. Inspects the pristine copy's schema version READ-ONLY with the installed
#      code (no migration runs), then re-hashes it.
#   4. Migrates a separate copy with the commit under test (isolated worktree).
#   5. Opens a copy of the migrated database with the installed code: it must
#      refuse (a code-only rollback does not reverse the migration).
#   6. Restore drill: a fresh copy of the pristine database opens with the
#      installed code at the old version with unchanged content.
[CmdletBinding()]
param(
    [string]$RepoRoot = "E:\Jarvis\App",
    [string]$LiveDatabase = "E:\Jarvis\Data\LocalState\memory.db",
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$Commit,
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Root,
    [switch]$IConfirmJarvisStopped
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $IConfirmJarvisStopped) { throw "Stop Jarvis first, then pass -IConfirmJarvisStopped." }
$running = @(Get-CimInstance Win32_Process | Where-Object {
    ($_.ExecutablePath -and $_.ExecutablePath -like "E:\Jarvis\*") -or
    ($_.CommandLine -and $_.CommandLine -match '(?i)jarvis[-_]voice|jarvis\.voice|jarvis\.runtime|jarvis-supervisor')
} | Where-Object { $_.ProcessId -ne $PID })
if ($running.Count -gt 0) {
    $running | ForEach-Object { Write-Host ("Running: {0} (PID {1})" -f $_.Name, $_.ProcessId) }
    throw "Jarvis processes are running; stop them first. Nothing was copied."
}
$live = [IO.Path]::GetFullPath($LiveDatabase)
$liveKey = Join-Path (Split-Path $live) ("{0}.key.dpapi" -f [IO.Path]::GetFileNameWithoutExtension($live))
foreach ($side in @("$live-wal", "$live-shm")) {
    if (Test-Path $side) { throw "Live database side file exists ($side): Jarvis may be running or stopped uncleanly. Nothing was copied." }
}
$git = (Get-Command git -ErrorAction Stop).Source
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
& $git -C $RepoRoot cat-file -e ($Commit + '^{commit}')
if ($LASTEXITCODE -ne 0) { throw "Commit is not local; fetch it explicitly first." }
$resolved = [IO.Path]::GetFullPath($Root)
if (Test-Path $resolved) { throw "Rehearsal root must not exist." }
New-Item -ItemType Directory -Path $resolved | Out-Null
$source = Join-Path $resolved "source"
& $git -C $RepoRoot worktree add --detach $source $Commit
if ($LASTEXITCODE -ne 0) { throw "Isolated worktree creation failed." }
$tool = Join-Path $source "tools\memory_migration_rehearsal.py"

function Hash($path) { (Get-FileHash -Algorithm SHA256 $path).Hash.ToLower() }
function CopyPair($from, $dir) {
    New-Item -ItemType Directory -Path $dir | Out-Null
    Copy-Item $from (Join-Path $dir "memory.db")
    Copy-Item (Join-Path (Split-Path $from) "memory.key.dpapi") (Join-Path $dir "memory.key.dpapi")
    return (Join-Path $dir "memory.db")
}
function Run($code, $command, $db) {
    $old = $env:PYTHONPATH; $oldSite = $env:PYTHONNOUSERSITE
    try {
        $env:PYTHONPATH = Join-Path $code "src"; $env:PYTHONNOUSERSITE = "1"
        $out = & $python -X utf8 $tool $command $db
        if ($LASTEXITCODE -ne 0) { throw "Rehearsal step '$command' failed." }
        return ($out | Select-Object -Last 1 | ConvertFrom-Json)
    } finally { $env:PYTHONPATH = $old; $env:PYTHONNOUSERSITE = $oldSite }
}

$liveBefore = @{ db = Hash $live; key = Hash $liveKey }
New-Item -ItemType Directory -Path (Join-Path $resolved "pristine") | Out-Null
$pristine = Join-Path $resolved "pristine\memory.db"
Copy-Item $live $pristine
Copy-Item $liveKey (Join-Path $resolved "pristine\memory.key.dpapi")
if ((Hash $pristine) -ne $liveBefore.db) { throw "Pristine copy differs from live." }
Set-ItemProperty $pristine -Name IsReadOnly -Value $true

# Read-only version inspection with the installed code: no migration can run.
$inspected = Run $RepoRoot "inspect" $pristine
$pristineAfterInspect = Hash $pristine
if ($pristineAfterInspect -ne $liveBefore.db) { throw "Read-only inspection changed the pristine copy." }
Write-Host ("Pristine copy schema version: {0} (ledger {1} entries)" -f $inspected.user_version, $inspected.ledger.Count)

$migrateDb = CopyPair $pristine (Join-Path $resolved "migrate")
Set-ItemProperty $migrateDb -Name IsReadOnly -Value $false
$migrated = Run $source "migrate" $migrateDb

$oldDb = CopyPair $migrateDb (Join-Path $resolved "older-code")
$beforeOld = Hash $oldDb
$olderCode = Run $RepoRoot "open" $oldDb
$afterOld = Hash $oldDb

$restoreDb = CopyPair $pristine (Join-Path $resolved "restore")
Set-ItemProperty $restoreDb -Name IsReadOnly -Value $false
$restored = Run $RepoRoot "open" $restoreDb

$liveAfter = @{ db = Hash $live; key = Hash $liveKey }
$differing = @()
foreach ($p in $inspected.tables.PSObject.Properties) {
    if ($p.Name -eq "jarvis_schema_migration") { continue }  # gains the new ledger row
    $after = $migrated.tables.PSObject.Properties[$p.Name]
    if (-not $after -or $after.Value.rows -ne $p.Value.rows -or $after.Value.digest -ne $p.Value.digest) { $differing += $p.Name }
}
$restoreDiffering = @()
foreach ($p in $inspected.tables.PSObject.Properties) {
    $after = $restored.tables.PSObject.Properties[$p.Name]
    if (-not $after -or $after.Value.digest -ne $p.Value.digest) { $restoreDiffering += $p.Name }
}
$report = [ordered]@{
    commit = $Commit
    live_unchanged = ($liveBefore.db -eq $liveAfter.db -and $liveBefore.key -eq $liveAfter.key)
    pristine_version = $inspected.user_version
    pristine_unchanged_after_inspection = ($pristineAfterInspect -eq $liveBefore.db)
    migrated_version = $migrated.user_version
    migrated_integrity = $migrated.integrity_check
    migrated_foreign_key_violations = $migrated.foreign_key_violations
    tables_with_changed_rows = $differing
    tables_added = @($migrated.tables.PSObject.Properties.Name | Where-Object { -not $inspected.tables.PSObject.Properties[$_] })
    older_code_opened_migrated = $olderCode.opened
    older_code_error = $olderCode.error
    older_code_left_copy_unchanged = ($beforeOld -eq $afterOld)
    restore_opened = $restored.opened
    restore_version = $restored.user_version
    restore_tables_changed = $restoreDiffering
}
$report | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $resolved "rehearsal-report.json") -Encoding utf8
$report | ConvertTo-Json -Depth 4
Write-Host "Rehearsal copies retained under $resolved (delete only with approval)."
