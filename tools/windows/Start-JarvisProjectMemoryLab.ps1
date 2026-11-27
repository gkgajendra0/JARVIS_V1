# Exact local commit only; no fetch, install, checkout reset or activation.
[CmdletBinding()]
param(
    [string]$RepoRoot = "E:\Jarvis\App",
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$Commit,
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$Model,
    [Parameter(Mandatory=$true)][ValidateNotNullOrEmpty()][string]$LabRoot,
    [string]$MachineProfile = "",
    [switch]$ResumeLab,
    [switch]$SeedAcceptance,
    [switch]$DevelopmentBatch,
    [switch]$PersonalAcceptance,
    [switch]$ContextEval,
    [switch]$SeedVoiceEval,
    [switch]$Slice1Acceptance,
    [switch]$RetryInterrupted,
    [ValidateRange(0.5, 120)][double]$CallSpacingSeconds = 0,
    [ValidateSet('story','explicit-list','ambiguous-bike','idiom','scale-11','scale-90','bytes','ambiguous-plan','d1-regression','alternatives','pages')][string[]]$Slice1Group,
    [switch]$PaidLane,
    [switch]$PaidCheckpoint,
    [switch]$RecoverD17Consent,
    [string]$PaidBudgetLedger = "",
    [string]$HeldoutScript = "",
    [ValidateSet('any','invariant')][string]$StopOn = "any",
    [ValidateSet('without','with')][string]$ContextEvalArm,
    [ValidateSet('travel','diet','device')][string]$ContextEvalCase,
    [ValidateSet('p0-q0','p1-q1','p2-q2','p3-q3','p4-q4','p5-q5')][string]$DevelopmentCase
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ($PersonalAcceptance -and ($ResumeLab -or $SeedAcceptance -or $DevelopmentBatch -or $DevelopmentCase)) { throw "Personal acceptance requires a fresh standalone lab." }
if ($ContextEval -and ($ResumeLab -or $SeedAcceptance -or $DevelopmentBatch -or $DevelopmentCase -or $PersonalAcceptance)) { throw "Context evaluation requires a fresh standalone lab." }
if (($ContextEvalArm -or $ContextEvalCase) -and -not $ContextEval) { throw "ContextEvalArm/ContextEvalCase require ContextEval." }
if ($SeedVoiceEval -and ($ResumeLab -or $SeedAcceptance -or $DevelopmentBatch -or $DevelopmentCase -or $PersonalAcceptance -or $ContextEval)) { throw "Voice evaluation seeding requires a fresh standalone lab." }
if ($DevelopmentCase -and -not $DevelopmentBatch) { throw "DevelopmentCase requires DevelopmentBatch." }
if ($Slice1Acceptance -and ($SeedAcceptance -or $DevelopmentBatch -or $DevelopmentCase -or $PersonalAcceptance -or $ContextEval -or $SeedVoiceEval)) { throw "Slice-1 acceptance runs alone in its own lab." }
if (($Slice1Group -or $RetryInterrupted) -and -not $Slice1Acceptance) { throw "Slice1Group/RetryInterrupted require Slice1Acceptance." }
if ($PaidLane -and -not $Slice1Acceptance) { throw "PaidLane is only for Slice1Acceptance (owner-approved USD 1 development acceptance)." }
if ($PaidCheckpoint -and -not $PaidLane) { throw "PaidCheckpoint requires PaidLane." }
if ($RecoverD17Consent -and -not ($Slice1Acceptance -and $ResumeLab)) { throw "RecoverD17Consent continues an existing acceptance lab (ResumeLab)." }
if ([bool]$PaidLane -ne [bool]$PaidBudgetLedger) { throw "PaidLane and PaidBudgetLedger go together." }
if ($RetryInterrupted -and -not $ResumeLab) { throw "RetryInterrupted only continues an existing lab (ResumeLab)." }
if ($HeldoutScript -and (-not $Slice1Acceptance -or $Slice1Group -or $PaidLane -or $PaidCheckpoint -or $RecoverD17Consent -or $ResumeLab)) { throw "HeldoutScript runs once in a fresh lab with Slice1Acceptance, Free lane only (the approved Paid budget excludes held-out)." }
if ($StopOn -ne "any" -and -not $PaidLane) { throw "StopOn applies to the Paid lane." }
if ($CallSpacingSeconds -and -not $Slice1Acceptance) { throw "CallSpacingSeconds requires Slice1Acceptance." }
if ($DevelopmentBatch -and ($SeedAcceptance -or $ResumeLab)) { throw "Development batch requires a new isolated lab, without acceptance seeding or resume." }
if ($SeedAcceptance -and $ResumeLab) { throw "Acceptance seeding requires a new isolated lab." }
$git = (Get-Command git -ErrorAction Stop).Source
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python -PathType Leaf)) { throw "Existing Python unavailable; nothing installed." }
& $git -C $RepoRoot cat-file -e ($Commit + '^{commit}')
if ($LASTEXITCODE -ne 0) { throw "Exact commit is not local. Fetch it explicitly before this launcher; no implicit network retry." }
$resolvedLab = [IO.Path]::GetFullPath($LabRoot)
if ($PaidLane) {
    $resolvedLedger = [IO.Path]::GetFullPath($PaidBudgetLedger)
    if ($resolvedLedger.StartsWith($resolvedLab.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "The shared Paid ledger must live outside any lab root." }
}
$source = Join-Path $resolvedLab "source"
$profile = Join-Path $resolvedLab "profile"
if ($ResumeLab) {
    if (-not (Test-Path (Join-Path $profile "project-memory.marker") -PathType Leaf)) { throw "Marked profile unavailable." }
    # The lab's original source checkout is never changed. A resume on a
    # different commit is allowed only for the D17 consent recovery (and its
    # continuation), from a separate checkout named after that commit.
    $labHead = (& $git -C $source rev-parse HEAD).Trim()
    if ($labHead -ne $Commit) {
        $source = Join-Path $resolvedLab ("source-" + $Commit.Substring(0, 8))
        if (-not (Test-Path $source)) {
            if (-not $RecoverD17Consent) { throw "This lab ran on commit $labHead; a different commit is only for -RecoverD17Consent." }
            & $git -C $RepoRoot worktree add --detach $source $Commit
            if ($LASTEXITCODE -ne 0) { throw "Recovery worktree creation failed." }
        }
        if ((& $git -C $source rev-parse HEAD).Trim() -ne $Commit) { throw "Checkout $source is not at $Commit." }
        Write-Host "Resuming lab (original source $labHead) from $source at $Commit"
    }
} else {
    if (Test-Path $resolvedLab) { throw "New lab root must not exist." }
    New-Item -ItemType Directory -Path $resolvedLab | Out-Null
    & $git -C $RepoRoot worktree add --detach $source $Commit
    if ($LASTEXITCODE -ne 0) { throw "Isolated worktree creation failed." }
}
$oldPath = $env:PYTHONPATH
$oldSite = $env:PYTHONNOUSERSITE
try {
    $env:PYTHONPATH = Join-Path $source "src"
    $env:PYTHONNOUSERSITE = "1"
    $arguments = @("-X", "utf8", "-m", "jarvis.voice.project_memory_lab", "--lab-root", $profile, "--model", $Model, "--source-commit", $Commit)
    if ($MachineProfile) { $arguments += @("--profile", $MachineProfile) }
    if ($ResumeLab) { $arguments += "--resume-lab" }
    if ($SeedAcceptance) { $arguments += "--seed-acceptance" }
    if ($DevelopmentBatch) { $arguments += "--development-batch" }
    if ($PersonalAcceptance) { $arguments += "--personal-acceptance" }
    if ($ContextEval) { $arguments += "--context-eval" }
    if ($SeedVoiceEval) { $arguments += "--seed-voice-eval" }
    if ($ContextEvalArm) { $arguments += @("--context-eval-arm", $ContextEvalArm) }
    if ($ContextEvalCase) { $arguments += @("--context-eval-case", $ContextEvalCase) }
    if ($DevelopmentCase) { $arguments += @("--development-case", $DevelopmentCase) }
    if ($Slice1Acceptance) { $arguments += "--slice1-acceptance" }
    if ($RetryInterrupted) { $arguments += "--retry-interrupted" }
    if ($CallSpacingSeconds) { $arguments += @("--call-spacing-seconds", $CallSpacingSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)) }
    foreach ($group in @($Slice1Group | Where-Object { $_ })) { $arguments += @("--slice1-group", $group) }
    if ($PaidLane) { $arguments += @("--paid-lane", "--paid-budget-ledger", $resolvedLedger) }
    if ($PaidCheckpoint) { $arguments += "--paid-checkpoint" }
    if ($RecoverD17Consent) { $arguments += "--recover-d17-consent" }
    if ($HeldoutScript) { $arguments += @("--slice1-heldout-script", [IO.Path]::GetFullPath($HeldoutScript)) }
    if ($StopOn -ne "any") { $arguments += @("--slice1-stop-on", $StopOn) }
    Push-Location $source
    try { & $python @arguments; if ($LASTEXITCODE -ne 0) { throw "Lab failed; retain its files." } }
    finally { Pop-Location }
} finally {
    $env:PYTHONPATH = $oldPath
    $env:PYTHONNOUSERSITE = $oldSite
    Write-Host "Isolated text lab retained: $resolvedLab"
}
