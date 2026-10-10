param([switch]$Verify)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Laya Vision: downloads the pinned base checkpoint (thaitea/laya-vision at the pinned revision) into
# models/laya-vision/hf and verifies it plus the locally fine-tuned checkpoint pinned in
# scripts/laya-pins.json (model.finetuned). The fine-tuned weights are produced locally and are never
# downloaded or redistributed (CC-BY-NC-SA-4.0, personal local use).
$root = $PSScriptRoot
$pins = Get-Content -LiteralPath (Join-Path $root 'scripts/laya-pins.json') -Raw | ConvertFrom-Json
if ($pins.format -ne 1) { throw 'Unsupported Laya pin format.' }
$python = Join-Path (Join-Path $root $pins.runtime.env_prefix) 'python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The Laya environment is missing. Run scripts/setup-windows.ps1 first.'
}
$env:HF_HOME = Join-Path $root $pins.model.hf_home
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$server = Join-Path $root 'scripts/laya-server.py'
if ($Verify) {
    $env:HF_HUB_OFFLINE = '1'
    & $python $server verify
} else {
    Write-Output "Downloading $($pins.model.repository)@$($pins.model.revision) into $($env:HF_HOME)"
    Write-Output 'Review MODEL_LICENSES.md (CC-BY-NC-SA-4.0 weights) before downloading.'
    & $python $server fetch
}
if ($LASTEXITCODE -ne 0) { throw 'Pinned Laya checkpoint verification failed (see the problems listed above).' }
Write-Output 'Verified pinned Laya base and fine-tuned checkpoints.'
