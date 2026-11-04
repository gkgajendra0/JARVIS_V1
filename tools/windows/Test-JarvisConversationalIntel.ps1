# Tests the feature branch in a detached worktree; does not modify running Jarvis.
[CmdletBinding()]
param(
    [string]$RepoRoot = "E:\Jarvis\App",
    [string]$FeatureBranch = "feat/semantic-context-reducer-20261029",
    [ValidateSet("all", "voice-close")]
    [string]$Suite = "all"
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not (Test-Path $RepoRoot -PathType Container)) {
    throw "Jarvis repo not found."
}
$git = (Get-Command git -ErrorAction Stop).Source
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python -PathType Leaf)) {
    throw "Jarvis virtual environment not found. No dependencies installed."
}
if ($FeatureBranch -notmatch '^[a-zA-Z0-9._/-]+$') {
    throw "Invalid branch name."
}
& $git -C $RepoRoot rev-parse --is-inside-work-tree | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Not a Git working tree."
}
$remoteRef = "refs/remotes/origin/" + $FeatureBranch
$fetchRef = "+refs/heads/" + $FeatureBranch + ":" + $remoteRef
& $git -C $RepoRoot fetch origin $fetchRef
if ($LASTEXITCODE -ne 0) {
    throw "Feature fetch failed."
}
$sha = (& $git -C $RepoRoot rev-parse $remoteRef).Trim()
if ($LASTEXITCODE -ne 0 -or $sha -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve feature commit."
}
$worktree = Join-Path $env:TEMP ("jarvis-semantic-verify-" + $sha.Substring(0, 12))
if (Test-Path $worktree) {
    throw "Isolated directory exists; refusing overwrite: $worktree"
}
& $git -C $RepoRoot worktree add --detach $worktree $sha
if ($LASTEXITCODE -ne 0) {
    throw "Could not create isolated worktree."
}
Write-Host "Production checkout unchanged: $RepoRoot"
Write-Host "Verification source: $worktree"
Write-Host "Exact commit: $sha"
$oldPath = $env:PYTHONPATH
$oldConfig = $env:JARVIS_MACHINE_CONFIG
$oldSite = $env:PYTHONNOUSERSITE
try {
    $env:PYTHONPATH = Join-Path $worktree "src"
    $env:PYTHONNOUSERSITE = "1"
    $env:JARVIS_MACHINE_CONFIG = Join-Path $worktree ".semantic_test_machine.json"
    Push-Location $worktree
    try {
        $checks = @(
            "tests/test_conversation_semantics.py",
            "tests/test_semantic_action_evidence.py",
            "tests/test_semantic_pipeline.py",
            "tests/test_semantic_model_producer.py",
            "tests/test_semantic_session_producer.py",
            "tests/test_semantic_session_components.py",
            "tests/test_semantic_session_controller.py",
            "tests/test_semantic_script_smoke.py",
            "tests/test_semantic_smoke_lab.py",
            "tests/test_semantic_voice_attachment.py",
            "tests/test_conversation_checkpoint.py",
            "tests/test_semantic_checkpoint_flow.py",
            "tests/test_semantic_checkpoint_writer.py",
            "tests/test_semantic_projection.py",
            "tests/test_semantic_personal_voice_resume.py",
            "tests/learning/test_conversation_checkpoint_suppression.py",
            "tests/test_memory_migrations.py",
            "tests/test_memory_database.py",
            "tests/test_memory_runtime.py"
        )
        # Stop at the first failure and emit useful stack traces if a test hangs.
        if ($Suite -eq "voice-close") {
            $checks = @("tests/test_semantic_voice_attachment.py")
        }
        & $python -m pytest -x -vv --tb=short -o faulthandler_timeout=20 @checks
        if ($LASTEXITCODE -ne 0) {
            throw "Focused semantic/memory tests failed."
        }
        $ruff = Join-Path $RepoRoot ".venv\Scripts\ruff.exe"
        if (-not (Test-Path $ruff -PathType Leaf)) {
            Write-Warning "Ruff unavailable; hosted CI formatting check is still required."
        }
        else {
            $files = @(
                "src/jarvis/memory/conversation_semantics.py",
                "src/jarvis/memory/conversation_checkpoint.py",
                "src/jarvis/memory/semantic_pipeline.py",
                "src/jarvis/memory/semantic_model_producer.py",
                "src/jarvis/memory/semantic_projection.py",
                "src/jarvis/memory/semantic_checkpoint_writer.py",
                "src/jarvis/memory/runtime.py",
                "src/jarvis/memory/service.py",
                "src/jarvis/memory/lifecycle.py",
                "src/jarvis/voice/semantic_context_bridge.py",
                "src/jarvis/voice/semantic_script_smoke.py",
                "src/jarvis/voice/semantic_smoke_lab.py",
                "tests/test_conversation_checkpoint.py"
            )
            & $ruff format --check @files
            if ($LASTEXITCODE -ne 0) {
                throw "Ruff format check failed on isolated worktree."
            }
        }
        Write-Host "Focused checks PASSED at commit $sha"
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:PYTHONPATH = $oldPath
    $env:JARVIS_MACHINE_CONFIG = $oldConfig
    $env:PYTHONNOUSERSITE = $oldSite
    Write-Host "Isolated worktree retained for inspection: $worktree"
    Write-Host "No active Jarvis checkout files or installed packages were altered."
}
