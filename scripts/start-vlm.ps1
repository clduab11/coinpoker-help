param([string]$AnswersLog = '', [switch]$DashboardOnly, [string]$LiveConfig = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows)) {
    throw 'Windows is required.'
}
$root = Split-Path -Parent $PSScriptRoot
$pins = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'laya-pins.json') -Raw | ConvertFrom-Json
if ($pins.format -ne 1) { throw 'Unsupported Laya pin format.' }
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
if ($LiveConfig) { $serverArgs += @('--live-config', $LiveConfig) }
Write-Output "Starting the read-only dashboard at http://127.0.0.1:$($pins.server.port)/ as $($pins.server.alias). Model loading is separate from quality/advice approval."
# Keep diagnostics locally; the server never logs requests or images.
$errorDir = Join-Path $root '.local/laya/train'
[void](New-Item -ItemType Directory -Force -Path $errorDir)
$errorFile = Join-Path $errorDir ("server-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')).stderr.txt")
Write-Output "Private diagnostics: $errorFile"
& $python @serverArgs 2>$errorFile
if ($LASTEXITCODE -ne 0) { throw "Laya server exited with code $LASTEXITCODE" }
