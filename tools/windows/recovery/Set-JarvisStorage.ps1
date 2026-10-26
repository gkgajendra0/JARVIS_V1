# Reapply Jarvis-owned storage locations after Windows setup/reinstallation.
[CmdletBinding()]
param(
    [string]$JarvisRoot = 'E:\Jarvis',
    [string]$StatePath = '',
    [string]$ModelsPath = '',
    [string]$LegacyHomePath = (Join-Path $env:USERPROFILE '.jarvis'),
    [switch]$PersistUser
)
$ErrorActionPreference = 'Stop'
if (-not $StatePath) { $StatePath = Join-Path $JarvisRoot 'Data\LocalState' }
if (-not $ModelsPath) { $ModelsPath = Join-Path $JarvisRoot 'Models' }
$cacheRoot = Join-Path $JarvisRoot 'Cache'
$cachePaths = [ordered]@{
    RF_HOME = (Join-Path $ModelsPath 'rfdetr')
    HF_HOME = (Join-Path $cacheRoot 'huggingface')
    TORCH_HOME = (Join-Path $cacheRoot 'torch')
    PLAYWRIGHT_BROWSERS_PATH = (Join-Path $cacheRoot 'ms-playwright')
    PIP_CACHE_DIR = (Join-Path $cacheRoot 'pip')
}
foreach ($entry in $cachePaths.GetEnumerator()) {
    New-Item -ItemType Directory -Force -Path $entry.Value | Out-Null
    [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
    if ($PersistUser) {
        [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'User')
    }
}
$stateModels = Join-Path $StatePath 'models'
New-Item -ItemType Directory -Force -Path $stateModels,(Join-Path $StatePath 'identity') | Out-Null
[Environment]::SetEnvironmentVariable('JARVIS_MODEL_CACHE',$stateModels,'Process')
[Environment]::SetEnvironmentVariable('JARVIS_BLAZEFACE_MODEL_PATH',(Join-Path $stateModels 'blaze_face_full_range.tflite'),'Process')
[Environment]::SetEnvironmentVariable('JARVIS_IDENTITY_DATA_DIR',(Join-Path $StatePath 'identity'),'Process')
$authorityPath = Join-Path $StatePath 'authority'
New-Item -ItemType Directory -Force -Path $authorityPath | Out-Null
[Environment]::SetEnvironmentVariable('JARVIS_AUTHORITY_AUDIT_DB',(Join-Path $authorityPath 'step7_audit.sqlite3'),'Process')
# Some optional modules still use ~/.jarvis without a configurable root.
# Redirect this Jarvis-only compatibility path; never replace an existing directory.
$legacyTarget = Join-Path $StatePath 'legacy-home'
New-Item -ItemType Directory -Force -Path $legacyTarget | Out-Null
if (-not (Test-Path -LiteralPath $LegacyHomePath)) {
    New-Item -ItemType Junction -Path $LegacyHomePath -Target $legacyTarget | Out-Null
} else {
    $legacyItem = Get-Item -LiteralPath $LegacyHomePath -Force
    if ($legacyItem.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath([string]$legacyItem.Target) -ne [IO.Path]::GetFullPath($legacyTarget)) {
        throw "Existing Jarvis home is not the expected E-drive junction: $LegacyHomePath. Preserve and migrate it before continuing."
    }
}
[Environment]::SetEnvironmentVariable('JARVIS_WINDOWS_HELLO_HELPER',(Join-Path $StatePath 'tools\windows-hello\Jarvis.WindowsHelloVerifier.exe'),'Process')
$winappRoot = Join-Path $StatePath 'tools\winapp'
if (Test-Path -LiteralPath (Join-Path $winappRoot 'winapp.exe') -PathType Leaf) {
    # Reapply the portable Hands dependency after reinstall; preserve the user's PATH.
    $pathEntries = @($env:PATH -split ';' | Where-Object {
        $_ -and -not [string]::Equals($_.TrimEnd('\'),$winappRoot.TrimEnd('\'),[StringComparison]::OrdinalIgnoreCase)
    })
    $env:PATH = (@($winappRoot) + $pathEntries) -join ';'
}
$tempRoot = Join-Path $JarvisRoot 'Temp'
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
[Environment]::SetEnvironmentVariable('TEMP',$tempRoot,'Process')
[Environment]::SetEnvironmentVariable('TMP',$tempRoot,'Process')
[Environment]::SetEnvironmentVariable('XDG_CACHE_HOME',$cacheRoot,'Process')
