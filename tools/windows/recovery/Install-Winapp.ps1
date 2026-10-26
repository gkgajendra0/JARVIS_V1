[CmdletBinding()]
param([string]$JarvisRoot='E:\Jarvis')
$ErrorActionPreference='Stop'
$version='0.7.1'
$uri='https://github.com/microsoft/winappCli/releases/download/v0.7.1/winappcli-x64.zip'
$expected='d925d1e32cdc320b6d271f653fd2cd3c05b5d7558deb20d1b548bead77900fcf'
$cache=Join-Path $JarvisRoot 'Cache\downloads'
$target=Join-Path $JarvisRoot 'Data\LocalState\tools\winapp'
$archive=Join-Path $cache 'winappcli-v0.7.1-x64.zip'
New-Item -ItemType Directory -Force -Path $cache | Out-Null
if(-not(Test-Path -LiteralPath $archive)) { Invoke-WebRequest -Uri $uri -OutFile $archive }
if((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Official Microsoft archive hash mismatch; no executable installed.' }
$targetFull=[IO.Path]::GetFullPath($target).TrimEnd('\')
$rootFull=[IO.Path]::GetFullPath($JarvisRoot).TrimEnd('\')
if(-not $targetFull.StartsWith($rootFull+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Install destination escaped Jarvis root.'}
New-Item -ItemType Directory -Force -Path $targetFull | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::OpenRead($archive)
try {
    foreach($entry in $zip.Entries) {
        if($entry.FullName.EndsWith('/') -or $entry.FullName.EndsWith('.pdb',[StringComparison]::OrdinalIgnoreCase)){continue}
        $destination=[IO.Path]::GetFullPath((Join-Path $targetFull $entry.FullName))
        if(-not $destination.StartsWith($targetFull+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe archive path.'}
        if(Test-Path -LiteralPath $destination){throw "Refusing to overwrite an existing tool file: $destination"}
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        [IO.Compression.ZipFileExtensions]::ExtractToFile($entry,$destination,$false)
    }
} finally {$zip.Dispose()}
$exe=Join-Path $targetFull 'winapp.exe'
if(-not(Test-Path -LiteralPath $exe -PathType Leaf)){throw 'Standalone archive did not contain winapp.exe.'}
$manifest=@{
    version=$version;source=$uri;archive_sha256=$expected
    executable=$exe;executable_sha256=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash
    debugging_symbols_installed=$false
    installed_utc=[DateTime]::UtcNow.ToString('o')
}
$manifest|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $targetFull 'installation.json') -Encoding UTF8
Write-Output "Installed verified Microsoft winapp v$version at $exe"
