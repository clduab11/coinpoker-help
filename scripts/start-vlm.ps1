<#
.SYNOPSIS
Starts the Laya Monitor with configurable model loading and capture.
.DESCRIPTION
Normal launch and -DashboardOnly load no model and never attach or record.
-EnableInference loads the pinned model. Alone it does not start capture. -AutomaticInference
arms one bounded source-profile discovery and independently admitted readout session,
whether observing or seated. Activity qualifies history, not Pot/stack/card readout.
All frames/time count against 600s/1200 frames unless -ContinuousObservation is
selected. That mode observes the same source until stop/loss; its
evidence recording still ends at 600s/1200 frames/1 GiB.
Manual sessions use scripts/laya_capture.py
with exact source confirmation. Its --mode inference-enabled
also requires separate session inference consent; default mode is capture-only.
Analysis requires valid current inputs; model loading does not establish accuracy.
.PARAMETER PracticeConfig
Private source selector for -AutomaticInference; it does not start capture by itself.
.PARAMETER ExperimentalBetAction
Explicit unvalidated p6/p7 diagnostics only, bound to the approved automatic source.
No wager/scene accuracy approval, action history or recommendations are enabled.
.PARAMETER LiveConfig
Legacy automatic attachment parameter; refused.
#>
param(
    [string]$AnswersLog = '',
    [switch]$DashboardOnly,
    [switch]$EnableInference,
    [switch]$AutomaticInference,
    [switch]$ContinuousObservation,
    [switch]$ManualStart,
    [switch]$ExperimentalBetAction,
    [string]$LiveConfig = '',
    [switch]$NoAutoAttach,
    [string]$PracticeConfig = '.local/practice-table.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows)) {
    throw 'Windows is required.'
}
$root = Split-Path -Parent $PSScriptRoot
$pins = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'laya-pins.json') -Raw | ConvertFrom-Json
if ($pins.format -ne 1) { throw 'Unsupported Laya pin format.' }
if ($pins.server.port -ne 18090) { throw 'Laya requires port 18090; no alternate-port fallback.' }
if ($LiveConfig -or ($PSBoundParameters.ContainsKey('PracticeConfig') -and -not $AutomaticInference)) {
    throw 'Use -PracticeConfig with -AutomaticInference; -LiveConfig is unsupported.'
}
if ($AutomaticInference -and (-not $EnableInference -or $NoAutoAttach -or $DashboardOnly)) {
    throw 'Automatic observation needs both -EnableInference and -AutomaticInference, without -NoAutoAttach/-DashboardOnly.'
}
if ($DashboardOnly -and $EnableInference) {
    throw 'Choose -DashboardOnly or -EnableInference, not both.'
}
if ($ExperimentalBetAction -and -not $AutomaticInference) {
    throw 'Experimental bet/action diagnostics require separately approved -EnableInference and -AutomaticInference.'
}
if ($ContinuousObservation -and (-not $EnableInference -or -not $AutomaticInference -or $ExperimentalBetAction)) {
    throw 'Continuous observation requires -EnableInference and -AutomaticInference, without -ExperimentalBetAction.'
}
if ($ManualStart -and -not $AutomaticInference) {
    throw 'Manual start requires -EnableInference and -AutomaticInference to configure the source selector.'
}
# Check before any Python/model start. Do not kill an unowned listener or restart it.
try {
    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
} catch {
    throw 'Cannot verify port 18090 availability; refusing to start another Laya instance.'
}
if (@($listeners | Where-Object { $_.Port -eq 18090 }).Count -gt 0) {
    throw 'Port 18090 is already occupied. No listener was stopped. Use the coordinator-controlled one-instance refresh.'
}
$python = Join-Path (Join-Path $root $pins.runtime.env_prefix) 'python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    if (-not $EnableInference) {
        $python = (Get-Command python.exe -CommandType Application -ErrorAction Stop).Source
    } else {
        throw 'The Laya environment is missing. Run scripts/setup-windows.ps1, or use -DashboardOnly with Python.'
    }
}

$env:HF_HOME = Join-Path $root $pins.model.hf_home
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$env:TRANSFORMERS_VERBOSITY = 'error'
$serverArgs = @((Join-Path $PSScriptRoot 'laya-server.py'), 'serve')
if ($AnswersLog) { $serverArgs += @('--answers-log', $AnswersLog) }
if ($EnableInference) {
    $serverArgs += '--enable-inference'
} else {
    $serverArgs += '--dashboard-only'
}
if ($AutomaticInference) { $serverArgs += @('--automatic-inference', '--practice-config', $PracticeConfig) }
if ($ContinuousObservation) { $serverArgs += '--continuous-observation' }
if ($ManualStart) { $serverArgs += '--manual-start' }
if ($ExperimentalBetAction) { $serverArgs += '--experimental-bet-action' }
Write-Output "Starting the Monitor at http://127.0.0.1:$($pins.server.port)/. Inference: $EnableInference. Automatic observation: $AutomaticInference. Sustained same-source observation: $ContinuousObservation."
# Keep diagnostics locally; the server never logs requests or images.
$errorDir = Join-Path $root '.local/laya/train'
[void](New-Item -ItemType Directory -Force -Path $errorDir)
$errorFile = Join-Path $errorDir ("server-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')).stderr.txt")
Write-Output "Private diagnostics: $errorFile"
if ($ContinuousObservation) {
    $serverArgs += @('--stderr-log', $errorFile)
    & $python @serverArgs
} else {
    & $python @serverArgs 2>$errorFile
}
if ($LASTEXITCODE -ne 0) { throw "Laya server exited with code $LASTEXITCODE" }
