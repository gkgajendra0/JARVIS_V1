param(
    [string]$WorkDir = ".step4-sqlcipher417-build",
    [string]$WheelDir = ".step4-sqlcipher417-wheelhouse"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SqlcipherCommit = "810db22f575ee7cf94ea96a3e91622b5fcece3dc"
$WrapperCommit = "14fc263"
$CustomVersion = "0.6.2+jarvis.sqlcipher4170"
$ConanVersion = "2.31.1"
$SetuptoolsVersion = "80.9.0"
$WheelVersion = "0.47.0"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

$Root = (Get-Location).Path
$BuildRoot = Join-Path $Root $WorkDir
$OutputRoot = Join-Path $Root $WheelDir
$SqlcipherDir = Join-Path $BuildRoot "sqlcipher"
$WrapperDir = Join-Path $BuildRoot "sqlcipher3"

Remove-Item -Recurse -Force $BuildRoot -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $OutputRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $BuildRoot | Out-Null
New-Item -ItemType Directory -Force $OutputRoot | Out-Null

Write-Host "STEP4_SQLCIPHER417_STAGE=clone_sources"
Invoke-Checked "git" @("clone", "--filter=blob:none", "https://github.com/sqlcipher/sqlcipher.git", $SqlcipherDir) $Root
Invoke-Checked "git" @("checkout", "--detach", $SqlcipherCommit) $SqlcipherDir
Invoke-Checked "git" @("clone", "--filter=blob:none", "https://github.com/coleifer/sqlcipher3.git", $WrapperDir) $Root
Invoke-Checked "git" @("checkout", "--detach", $WrapperCommit) $WrapperDir

$ActualSqlcipherCommit = (& git -C $SqlcipherDir rev-parse HEAD).Trim()
$ActualWrapperCommit = (& git -C $WrapperDir rev-parse HEAD).Trim()
if ($ActualSqlcipherCommit -ne $SqlcipherCommit) {
    throw "SQLCipher commit mismatch: $ActualSqlcipherCommit"
}
if (-not $ActualWrapperCommit.StartsWith($WrapperCommit)) {
    throw "sqlcipher3 wrapper commit mismatch: $ActualWrapperCommit"
}

Write-Host "STEP4_SQLCIPHER417_STAGE=generate_amalgamation"
Invoke-Checked "nmake" @("/f", "Makefile.msc", "sqlite3.c") $SqlcipherDir

$GeneratedC = Join-Path $SqlcipherDir "sqlite3.c"
$GeneratedH = Join-Path $SqlcipherDir "sqlite3.h"
if (-not (Test-Path $GeneratedC) -or -not (Test-Path $GeneratedH)) {
    throw "SQLCipher amalgamation was not generated"
}

Copy-Item -Force $GeneratedC (Join-Path $WrapperDir "vendor\sqlite3.c")
Copy-Item -Force $GeneratedH (Join-Path $WrapperDir "vendor\sqlite3.h")

Write-Host "STEP4_SQLCIPHER417_STAGE=mark_integrator_version"
$PyprojectPath = Join-Path $WrapperDir "pyproject.toml"
$Pyproject = Get-Content $PyprojectPath -Raw
$Pyproject = $Pyproject -replace 'version = "0\.6\.2"', ('version = "' + $CustomVersion + '"')
Set-Content -Path $PyprojectPath -Value $Pyproject -Encoding UTF8

$SetupPath = Join-Path $WrapperDir "setup.py"
$Setup = Get-Content $SetupPath -Raw
$Setup = $Setup -replace "VERSION = '0\.6\.2'", ("VERSION = '" + $CustomVersion + "'")
Set-Content -Path $SetupPath -Value $Setup -Encoding UTF8

Write-Host "STEP4_SQLCIPHER417_STAGE=install_build_tools"
Invoke-Checked "python" @("-m", "pip", "install", "--disable-pip-version-check", "setuptools==$SetuptoolsVersion", "wheel==$WheelVersion", "conan==$ConanVersion") $Root

Write-Host "STEP4_SQLCIPHER417_STAGE=build_wheel"
$PreviousCompileTarget = $env:SQLCIPHER3_COMPILE_TARGET
$env:SQLCIPHER3_COMPILE_TARGET = "x86_64"
try {
    Invoke-Checked "python" @("-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "--wheel-dir", $OutputRoot) $WrapperDir
}
finally {
    $env:SQLCIPHER3_COMPILE_TARGET = $PreviousCompileTarget
}

$Wheels = @(Get-ChildItem -Path $OutputRoot -Filter "sqlcipher3-*.whl")
if ($Wheels.Count -ne 1) {
    throw "Expected exactly one sqlcipher3 wheel, found $($Wheels.Count)"
}
$Wheel = $Wheels[0]
if ($Wheel.Name -notmatch '0\.6\.2\+jarvis\.sqlcipher4170') {
    throw "Custom integrator version missing from wheel name: $($Wheel.Name)"
}

$Manifest = [ordered]@{
    purpose = "research-only pinned SQLCipher 4.17.0 Windows wheel"
    sqlcipher_commit = $ActualSqlcipherCommit
    sqlcipher_expected_version = "4.17.0 community"
    sqlcipher_expected_sqlite = "3.53.3"
    sqlcipher3_wrapper_commit = $ActualWrapperCommit
    sqlcipher3_integrator_version = $CustomVersion
    openssl_recipe = "openssl/3.6.0"
    conan_version = $ConanVersion
    wheel_file = $Wheel.Name
    wheel_sha256 = (Get-FileHash $Wheel.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    amalgamation_sqlite3_c_sha256 = (Get-FileHash $GeneratedC -Algorithm SHA256).Hash.ToLowerInvariant()
    amalgamation_sqlite3_h_sha256 = (Get-FileHash $GeneratedH -Algorithm SHA256).Hash.ToLowerInvariant()
}

$ManifestPath = Join-Path $OutputRoot "build-manifest.json"
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $ManifestPath -Encoding UTF8

Write-Host "STEP4_SQLCIPHER417_STAGE=build_complete"
Write-Host "WHEEL=$($Wheel.Name)"
Write-Host "SHA256=$($Manifest.wheel_sha256)"
