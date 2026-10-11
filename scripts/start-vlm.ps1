<#
.SYNOPSIS
Starts the read-only Laya dashboard without capture or model loading by default.
.DESCRIPTION
Normal launch and -DashboardOnly load no model and never attach or record.
-EnableInference requires separate operator approval and only loads the pinned
model. It does not start capture. Manual capture-only sessions use the separate
scripts/laya_capture.py CLI with exact source confirmation and seated assertion.
Suggestions remain OFF; model loading is not quality or advice approval.
.PARAMETER PracticeConfig
Legacy selector parameter. Supplying it is refused, never automatically followed.
.PARAMETER LiveConfig
Legacy automatic attachment parameter; refused.
#>
param(
    [string]$AnswersLog = '',
    [switch]$DashboardOnly,
    [switch]$EnableInference,
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
if ($LiveConfig -or $PSBoundParameters.ContainsKey('PracticeConfig')) {
    throw 'Automatic attachment is disabled. Use scripts/laya_capture.py for a confirmed capture-only session.'
}
if ($DashboardOnly -and $EnableInference) {
    throw 'Choose -DashboardOnly or separately approved -EnableInference, not both.'
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
Write-Output "Starting the read-only dashboard at http://127.0.0.1:$($pins.server.port)/. Inference opt-in: $EnableInference. No automatic capture or recording."
# Keep diagnostics locally; the server never logs requests or images.
$errorDir = Join-Path $root '.local/laya/train'
[void](New-Item -ItemType Directory -Force -Path $errorDir)
$errorFile = Join-Path $errorDir ("server-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')).stderr.txt")
Write-Output "Private diagnostics: $errorFile"
& $python @serverArgs 2>$errorFile
if ($LASTEXITCODE -ne 0) { throw "Laya server exited with code $LASTEXITCODE" }
