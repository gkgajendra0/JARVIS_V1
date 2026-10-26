param([string]$Model = 'E:\Jarvis\WakeTraining\2026-10-24\results\jarvis\jarvis.onnx')
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Model)) { throw "Trained model not present: $Model" }
& 'E:\Jarvis\App\.venv\Scripts\python.exe' (Join-Path $PSScriptRoot 'validate_runtime.py') $Model
if ($LASTEXITCODE -ne 0) { throw 'Runtime compatibility verification failed.' }
