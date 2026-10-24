# JARVIS V1 Windows E-drive restore and launcher.
# Safe defaults: no git checkout/reset/pull, no database initialization, no secret logging.
[CmdletBinding()]
param(
    [string]$AppPath = 'E:\Jarvis\App',
    [string]$DataPath = 'E:\Jarvis\Data\LocalState',
    [string]$ModelsPath = 'E:\Jarvis\Models',
    [string]$WakeModelPath = '',
    [switch]$DeepScan,
    [switch]$Launch,
    [switch]$PersonalContextApply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Require-File([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description not found: $Path"
    }
}

function Find-WakeModel {
    if ($WakeModelPath) {
        Require-File $WakeModelPath 'Specified wake model'
        return (Get-Item -LiteralPath $WakeModelPath).FullName
    }

    $candidates = @(
        (Join-Path $ModelsPath 'jarvis.onnx'),
        'G:\jarvis_wake_output\jarvis\jarvis.onnx',
        'D:\jarvis_wake_output\jarvis\jarvis.onnx',
        (Join-Path $AppPath 'jarvis.onnx')
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            return (Get-Item -LiteralPath $path).FullName
        }
    }

    $roots = @($ModelsPath, (Join-Path $AppPath 'models'), 'D:\Jarvis', 'D:\Models')
    if ($DeepScan) { $roots += @('D:\', 'E:\', 'G:\') }
    foreach ($root in ($roots | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        Write-Host "Searching for jarvis.onnx under $root"
        $found = Get-ChildItem -LiteralPath $root -Recurse -File -Filter 'jarvis.onnx' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $found) { return $found.FullName }
    }
    return $null
}

Write-Host '=== JARVIS restore: source and Python ===' -ForegroundColor Cyan
Require-File (Join-Path $AppPath 'src\jarvis\config.py') 'Jarvis source'
$python = Join-Path $AppPath '.venv\Scripts\python.exe'
$setup = Join-Path $AppPath '.venv\Scripts\jarvis-setup.exe'
$voice = Join-Path $AppPath '.venv\Scripts\jarvis-voice.exe'
Require-File $python 'Python virtual environment'
Require-File $setup 'Jarvis setup'
Require-File $voice 'Jarvis voice'
& $python -c 'import jarvis; print("Jarvis code:", jarvis.__file__)'
if ($LASTEXITCODE -ne 0) { throw 'Jarvis import failed; the virtual environment needs repair.' }

Write-Host '=== JARVIS restore: persistent storage ===' -ForegroundColor Cyan
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is unavailable.' }
if ($env:JARVIS_MACHINE_CONFIG) {
    throw 'Custom JARVIS_MACHINE_CONFIG is configured. Do not replace its existing layout.'
}
New-Item -ItemType Directory -Force -Path $DataPath | Out-Null
New-Item -ItemType Directory -Force -Path $ModelsPath | Out-Null
$source = Join-Path $env:LOCALAPPDATA 'JARVIS'
$item = Get-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue
if ($null -eq $item) {
    New-Item -ItemType Junction -Path $source -Target $DataPath | Out-Null
    Write-Host "Created junction: $source => $DataPath"
} else {
    if (-not (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        throw "The current $source is a real directory. No data will be moved or overwritten automatically."
    }
    $destination = @($item.Target) | Select-Object -First 1
    if (-not $destination) { throw "Could not determine junction target for $source" }
    $actual = [IO.Path]::GetFullPath($destination).TrimEnd('\')
    $expected = [IO.Path]::GetFullPath($DataPath).TrimEnd('\')
    if (-not [string]::Equals($actual, $expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Storage junction points to $actual instead of $expected. No change made."
    }
    Write-Host "Junction already correct: $source => $actual"
}
& $python -c 'from jarvis.machine_config import default_machine_config_path; from jarvis.memory.runtime import default_memory_database_path; from jarvis.work.store import default_work_state_dir; print("Config:", default_machine_config_path().resolve()); print("Memory:", default_memory_database_path().resolve()); print("Work:", default_work_state_dir().resolve())'
if ($LASTEXITCODE -ne 0) { throw 'Unable to verify Jarvis data paths.' }

Write-Host '=== JARVIS restore: wake-word model ===' -ForegroundColor Cyan
$model = Find-WakeModel
if (-not $model) {
    Write-Warning 'BLOCKED: A compatible jarvis.onnx wake-word model was not found.'
    Write-Host 'Recover the original trained ONNX model or retrain it; an arbitrary ONNX file will not work.'
    Write-Host 'To scan all drives, rerun with -DeepScan. To use a file, rerun with -WakeModelPath "FULL_PATH" -Launch.'
    Write-Host 'No Jarvis machine settings were changed.'
    return
}
$stagedModel = Join-Path $ModelsPath 'jarvis.onnx'
if (-not [string]::Equals([IO.Path]::GetFullPath($model), [IO.Path]::GetFullPath($stagedModel), [StringComparison]::OrdinalIgnoreCase)) {
    if (Test-Path -LiteralPath $stagedModel) { throw "Model destination exists; refusing to overwrite: $stagedModel" }
    Copy-Item -LiteralPath $model -Destination $stagedModel
    Write-Host "Copied wake model to $stagedModel"
}
if ((Get-Item -LiteralPath $stagedModel).Length -eq 0) { throw 'Wake model file is empty.' }

Write-Host '=== JARVIS restore: official machine setup ===' -ForegroundColor Cyan
$config = Join-Path $DataPath 'machine.json'
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
    Write-Host 'Running official setup to select real microphone, speakers, vision, and authority tools.'
    $env:JARVIS_WAKE_MODEL_PATH = $stagedModel
    & $setup
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
        throw "Machine profile was not created (setup exit code $LASTEXITCODE)."
    }
} else {
    Write-Host 'Existing machine profile preserved. Re-run jarvis-setup manually to update any old device selectors.'
}

Write-Host '=== JARVIS restore: production startup checks ===' -ForegroundColor Cyan
& $python -c 'from jarvis.config import JarvisConfig; from jarvis.preflight import run_startup_preflight, print_preflight; checks=run_startup_preflight(JarvisConfig.from_environment()); print_preflight(checks); raise SystemExit(0 if all(check.ok for check in checks) else 2)'
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Jarvis is not yet ready. Fix the printed startup checks, then rerun this script.'
    Write-Host 'Provider API credentials must remain local; never paste them in chat.'
    return
}

if ($Launch) {
    Write-Host '=== Starting JARVIS ===' -ForegroundColor Cyan
    Push-Location -LiteralPath $AppPath
    try {
        if ($PersonalContextApply) {
            & $voice --personal-context apply
        } else {
            & $voice
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host 'Ready. Run this script with -Launch to start Jarvis.'
    Write-Host 'Add -PersonalContextApply to opt into owner-consented personal context.'
}

Write-Warning 'Important: Windows DPAPI-protected personal-memory encryption keys are not portable across a fresh Windows user installation merely by storing the DB on E:. A tested, separate encrypted recovery solution is still needed.'
