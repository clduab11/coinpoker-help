<#
.SYNOPSIS
Starts the pinned, offline Laya dashboard with user-declared NLH attachment.
.DESCRIPTION
Normal launch automatically selects one visible CoinPoker.exe game window whose
title matches ^NLH\s*[0-9]+ and whose current bounds are positive. Missing or
ambiguous matching windows block capture; a missing private profile does not.
Practice-six-max is user-declared scope, not title proof or perception calibration.
Capture supplies the current resolution; no lobby image or fixed size is used.
-DashboardOnly loads no model and disables automatic attachment by default,
making it suitable for safe UI inspection and tests. -NoAutoAttach is an
explicit internal/diagnostic opt-out, not a browser connection workflow.
.PARAMETER PracticeConfig
Optional private rule under .local; defaults to .local/practice-table.json.
If absent, the built-in user-provided CoinPoker.exe / NLH rule is used.
.PARAMETER LiveConfig
Internal compatibility mode: requires -NoAutoAttach and the same strict selector
rule contract, not legacy arbitrary capture arguments.
#>
param(
    [string]$AnswersLog = '',
    [switch]$DashboardOnly,
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
if ($LiveConfig -and -not $NoAutoAttach) {
    throw '-LiveConfig is internal compatibility mode and requires explicit -NoAutoAttach.'
}
if ($LiveConfig -and $PSBoundParameters.ContainsKey('PracticeConfig')) {
    throw 'Choose only one selector rule: -LiveConfig or -PracticeConfig.'
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
    if ($DashboardOnly) {
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
if ($DashboardOnly) { $serverArgs += '--dashboard-only' }
if (-not $DashboardOnly -and -not $NoAutoAttach) {
    $serverArgs += @('--auto-attach', '--practice-config', $PracticeConfig)
}
if ($LiveConfig) { $serverArgs += @('--live-config', $LiveConfig) }
Write-Output "Starting the read-only dashboard at http://127.0.0.1:$($pins.server.port)/ as $($pins.server.alias). Model loading is separate from quality/advice approval."
# Keep diagnostics locally; the server never logs requests or images.
$errorDir = Join-Path $root '.local/laya/train'
[void](New-Item -ItemType Directory -Force -Path $errorDir)
$errorFile = Join-Path $errorDir ("server-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')).stderr.txt")
Write-Output "Private diagnostics: $errorFile"
& $python @serverArgs 2>$errorFile
if ($LASTEXITCODE -ne 0) { throw "Laya server exited with code $LASTEXITCODE" }
