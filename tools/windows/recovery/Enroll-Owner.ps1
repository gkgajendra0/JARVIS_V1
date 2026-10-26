[CmdletBinding()]
param([string]$JarvisRoot = 'E:\Jarvis')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Set-JarvisStorage.ps1') -JarvisRoot $JarvisRoot
Push-Location -LiteralPath (Join-Path $JarvisRoot 'App')
try {
    & (Join-Path $JarvisRoot 'App\.venv\Scripts\python.exe') -m jarvis.identity.owner_enrollment
    $enrollmentExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $enrollmentExit
