[CmdletBinding()]
param(
    [string]$TrainingRoot = 'E:\Jarvis\WakeTraining\2026-10-24',
    [string]$BackupRoot = 'D:\JarvisWakeBackup\2026-10-24',
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$env:PATH = 'C:\Program Files\Docker\Docker\resources\bin;' + $env:PATH
$docker = (Get-Command docker.exe -ErrorAction Stop).Source
$recipe = $PSScriptRoot
$image = 'jarvis-wake-training:livekit-0.2.1-cu128'
New-Item -ItemType Directory -Force -Path $TrainingRoot,$BackupRoot,(Join-Path $TrainingRoot 'logs') | Out-Null
$lockPath = Join-Path $TrainingRoot 'overnight.lock'
try { $lock = [IO.File]::Open($lockPath,'OpenOrCreate','ReadWrite','None') }
catch { throw 'An overnight supervisor already holds the training lock.' }
$transcript = Join-Path $TrainingRoot ('logs\supervisor-' + (Get-Date -Format yyyyMMdd-HHmmss) + '.log')
Start-Transcript -Path $transcript | Out-Null
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class JarvisTrainingPower {
  [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);
}
'@
$container = $null
$follow = $null
try {
    if ((Get-PSDrive E).Free -lt 60GB) { throw 'Need at least 60 GiB free on E:.' }
    if ((Get-PSDrive D).Free -lt 30GB) { throw 'Need at least 30 GiB free on D:.' }
    & $docker info --format 'Docker: {{.ServerVersion}} / {{.OSType}}'
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop first.' }
    & nvidia-smi
    if ($LASTEXITCODE -ne 0) { throw 'NVIDIA GPU preflight failed.' }
    $running = & $docker ps --filter 'label=jarvis.wake-training=true' --format '{{.Names}}'
    if ($running) { throw "A training container is already running: $running" }
    [void][JarvisTrainingPower]::SetThreadExecutionState([uint32]2147483649)
    if (-not $SkipBuild) {
        Write-Host 'Building isolated trainer; progress: logs\build.stderr.log'
        $build = Start-Process -FilePath $docker -ArgumentList @('build','--progress','plain','-t',$image,$recipe) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $TrainingRoot 'logs\build.stdout.log') -RedirectStandardError (Join-Path $TrainingRoot 'logs\build.stderr.log')
        while (-not $build.WaitForExit(30000)) {
            [void][JarvisTrainingPower]::SetThreadExecutionState([uint32]2147483649)
        }
        if ($build.ExitCode -ne 0) { throw 'Training image build failed; see build.stderr.log.' }
    }
    & $docker image inspect $image --format '{{.Id}}' | Set-Content (Join-Path $TrainingRoot 'logs\image-id.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Training image is unavailable.' }
    # Archive source and recipe on both drives before launching any long stage.
    $archive = Join-Path $TrainingRoot 'recipe'
    if (-not (Test-Path -LiteralPath $archive)) { Copy-Item -LiteralPath $recipe -Destination $archive -Recurse }
    $backupRecipe = Join-Path $BackupRoot 'recipe'
    if (-not (Test-Path -LiteralPath $backupRecipe)) { Copy-Item -LiteralPath $recipe -Destination $backupRecipe -Recurse }
    $container = 'jarvis-wake-' + (Get-Date -Format yyyyMMdd-HHmmss)
    $containerId = & $docker run -d --name $container --label jarvis.wake-training=true --gpus all --shm-size 2g --cpus 8 --memory 7g --restart no --mount "type=bind,source=$TrainingRoot,target=/training" --mount "type=bind,source=$BackupRoot,target=/backup" --mount "type=bind,source=$recipe,target=/workflow,readonly" $image bash -lc 'python -u /workflow/run_training.py --smoke && python -u /workflow/run_training.py'
    if ($LASTEXITCODE -ne 0) { throw 'Container launch failed.' }
    $container | Set-Content (Join-Path $TrainingRoot 'container-name.txt')
    $containerId | Set-Content (Join-Path $TrainingRoot 'container-id.txt')
    Copy-Item -LiteralPath (Join-Path $TrainingRoot 'container-name.txt') -Destination $BackupRoot -Force
    Write-Host "Running: $container"
    Write-Host "Logs: $TrainingRoot\logs"
    $follow = Start-Process -FilePath $docker -ArgumentList @('logs','--follow',$container) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $TrainingRoot 'logs\container.stdout.log') -RedirectStandardError (Join-Path $TrainingRoot 'logs\container.stderr.log')
    do {
        [void][JarvisTrainingPower]::SetThreadExecutionState([uint32]2147483649)
        $stateText = & $docker inspect $container --format '{{json .State}}'
        if ($LASTEXITCODE -ne 0) { throw 'Docker became unavailable; inspect the retained container after recovery.' }
        $stateText | Set-Content (Join-Path $TrainingRoot 'container-state.json')
        Copy-Item -LiteralPath (Join-Path $TrainingRoot 'container-state.json') -Destination $BackupRoot -Force
        $state = $stateText | ConvertFrom-Json
        Get-ChildItem -LiteralPath (Join-Path $TrainingRoot 'logs') -File | ForEach-Object {
            $target = Join-Path $BackupRoot 'logs'
            New-Item -ItemType Directory -Force -Path $target | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force -ErrorAction Continue
        }
        if ($state.Running) { Start-Sleep -Seconds 30 }
    } while ($state.Running)
    if ($follow) { $follow.WaitForExit(10000) | Out-Null }
    if ($state.ExitCode -ne 0) { throw "Training stopped with exit $($state.ExitCode). Logs and completed stages are retained." }
    Write-Host "Training complete. Model: $TrainingRoot\results\jarvis\jarvis.onnx"
    Write-Host 'Run Validate-Runtime.ps1 before deploying to the app.'
} finally {
    [void][JarvisTrainingPower]::SetThreadExecutionState([uint32]2147483648)
    Stop-Transcript | Out-Null
    $lock.Dispose()
}
