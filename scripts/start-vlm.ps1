Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows)) {
    throw 'Windows is required.'
}
$root = Split-Path -Parent $PSScriptRoot
$pins = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'vlm-pins.json') -Raw | ConvertFrom-Json
if ($pins.format -ne 1) { throw 'Unsupported VLM pin format.' }
$runtime = Join-Path $root ".local/vlm-runtime/$($pins.runtime.tag)"
$archive = Join-Path $runtime $pins.runtime.asset
$server = Join-Path $runtime 'bin/llama-server.exe'
if (-not (Test-Path -LiteralPath $archive -PathType Leaf) -or
    (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ine $pins.runtime.sha256) {
    throw 'Pinned llama.cpp server archive is missing or has a wrong hash. Run scripts/setup-windows.ps1.'
}
if (-not (Test-Path -LiteralPath $server -PathType Leaf)) {
    throw 'Pinned llama.cpp server executable is missing. Run scripts/setup-windows.ps1.'
}
$version = (& $server --version 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or
    $version -notmatch "build $($pins.runtime.tag.Substring(1))" -or
    $version -notmatch [regex]::Escape($pins.runtime.commit.Substring(0, 9))) {
    throw 'Installed llama.cpp server does not match the pinned build.'
}

& (Join-Path $root 'download-model.ps1') -Verify
$modelDirectory = Join-Path (Join-Path $root 'models') $pins.model.directory
$modelFile = Join-Path $modelDirectory $pins.model.files[0].name
$projectorFile = Join-Path $modelDirectory $pins.model.files[1].name

$env:HF_HUB_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
Write-Output "Starting pinned GGUF server on 127.0.0.1:18080 as $($pins.model.alias)."
& $server --model $modelFile --mmproj $projectorFile --alias $pins.model.alias `
    --host 127.0.0.1 --port 18080 --offline --gpu-layers auto `
    --ctx-size 8192 --parallel 1 --no-webui --cors-origins localhost `
    --no-cors-credentials --log-disable
if ($LASTEXITCODE -ne 0) { throw "llama.cpp server exited with code $LASTEXITCODE" }
