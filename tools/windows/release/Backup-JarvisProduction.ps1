<#
.SYNOPSIS
Read-only, verified backup of the installed Jarvis before the project-memory
merge (#303-#308). It never modifies the data folder.

Copies memory.db (+ -wal, -shm), memory.key.dpapi, machine.json and the
authority folder into a new dated folder under E:\Jarvis\Backups, records the
installed App commit, and writes a SHA-256 manifest that is re-verified against
the copies. Refuses to run while Jarvis is running (a live WAL is not a
consistent backup).

The memory key is DPAPI-sealed to this Windows user: the backup can be
restored only by the same user on this machine.
#>
param(
    [string]$DataPath = 'E:\Jarvis\Data\LocalState',
    [string]$AppPath = 'E:\Jarvis\App',
    [string]$BackupRoot = 'E:\Jarvis\Backups'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$running = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like 'jarvis*' -or ($_.CommandLine -and $_.CommandLine -match '\bjarvis\.(voice|runtime_supervisor|app)\b|jarvis-voice') }
if ($running) {
    throw ("Jarvis is running (PIDs: {0}). Stop it first; nothing was copied." -f (($running | ForEach-Object ProcessId) -join ', '))
}
$data = (Resolve-Path -LiteralPath $DataPath).Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$target = Join-Path $BackupRoot "project-memory-pre-merge-$stamp"
if (Test-Path -LiteralPath $target) { throw "Backup folder already exists: $target" }
New-Item -ItemType Directory -Path $target | Out-Null

$items = @('memory.db', 'memory.db-wal', 'memory.db-shm', 'memory.key.dpapi', 'machine.json', 'authority')
$copied = @()
foreach ($name in $items) {
    $source = Join-Path $data $name
    if (-not (Test-Path -LiteralPath $source)) { continue }
    Copy-Item -LiteralPath $source -Destination (Join-Path $target $name) -Recurse
    $copied += $name
}
if ($copied -notcontains 'memory.db' -or $copied -notcontains 'memory.key.dpapi') {
    throw "memory.db or memory.key.dpapi missing in $data; backup is incomplete."
}

function Get-Manifest([string]$Root) {
    Get-ChildItem -LiteralPath $Root -Recurse -File |
        Where-Object { $_.Name -ne 'manifest.json' } |
        Sort-Object FullName |
        ForEach-Object {
            [pscustomobject]@{
                path   = $_.FullName.Substring($Root.Length + 1)
                bytes  = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            }
        }
}
$sourceManifest = foreach ($name in $copied) {
    $p = Join-Path $data $name
    if (Test-Path -LiteralPath $p -PathType Leaf) {
        [pscustomobject]@{ path = $name; sha256 = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash }
    }
}
$backupManifest = Get-Manifest $target
foreach ($s in $sourceManifest) {
    $b = $backupManifest | Where-Object path -eq $s.path
    if (-not $b -or $b.sha256 -ne $s.sha256) { throw "Verification failed for $($s.path)." }
}
$commit = (& git -C $AppPath rev-parse HEAD).Trim()
[pscustomobject]@{
    created     = (Get-Date).ToString('o')
    data_path   = $data
    app_path    = $AppPath
    app_commit  = $commit
    windows_user = "$env:USERDOMAIN\$env:USERNAME"
    files       = $backupManifest
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $target 'manifest.json') -Encoding UTF8
Write-Host "Backup verified: $target"
Write-Host "Installed App commit: $commit"
