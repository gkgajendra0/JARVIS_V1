<#
.SYNOPSIS
Roll the data folder back to a verified backup made by Backup-JarvisProduction.ps1.

Owner-run only, with Jarvis stopped. Verifies every file in the backup against
its manifest first. The current files are MOVED aside (never deleted) into
<DataPath>\pre-restore-<timestamp>, then the backup is copied in. The App code
rollback (git checkout of manifest.app_commit) is a separate, printed step.
#>
param(
    [Parameter(Mandatory = $true)][string]$Backup,
    [string]$DataPath = 'E:\Jarvis\Data\LocalState'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$running = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like 'jarvis*' -or ($_.CommandLine -and $_.CommandLine -match '\bjarvis\.(voice|runtime_supervisor|app)\b|jarvis-voice') }
if ($running) { throw "Jarvis is running; stop it first. Nothing was changed." }
$backupPath = (Resolve-Path -LiteralPath $Backup).Path
$manifest = Get-Content -LiteralPath (Join-Path $backupPath 'manifest.json') -Raw | ConvertFrom-Json
foreach ($f in $manifest.files) {
    $p = Join-Path $backupPath $f.path
    if ((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash -ne $f.sha256) {
        throw "Backup file $($f.path) does not match its manifest. Nothing was changed."
    }
}
$data = (Resolve-Path -LiteralPath $DataPath).Path
$aside = Join-Path $data ("pre-restore-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $aside | Out-Null
foreach ($name in @('memory.db', 'memory.db-wal', 'memory.db-shm', 'memory.key.dpapi', 'machine.json', 'authority')) {
    $current = Join-Path $data $name
    if (Test-Path -LiteralPath $current) { Move-Item -LiteralPath $current -Destination (Join-Path $aside $name) }
    $saved = Join-Path $backupPath $name
    if (Test-Path -LiteralPath $saved) { Copy-Item -LiteralPath $saved -Destination $current -Recurse }
}
Write-Host "Data restored from $backupPath. Previous files kept in $aside."
Write-Host "Now restore the code: git -C E:\Jarvis\App checkout $($manifest.app_commit)"
