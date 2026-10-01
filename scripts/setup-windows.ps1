param([switch]$DownloadModel, [switch]$SkipBuild)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows)) {
    throw 'Windows is required.'
}
if ([Environment]::OSVersion.Version.Build -lt 18362) {
    throw 'Windows 10 version 1903 (build 18362) or newer is required for window capture.'
}
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne
    [System.Runtime.InteropServices.Architecture]::X64) {
    throw 'The pinned llama.cpp server asset requires Windows x64.'
}

$root = Split-Path -Parent $PSScriptRoot
$pins = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'vlm-pins.json') -Raw | ConvertFrom-Json
if ($pins.format -ne 1) { throw 'Unsupported VLM pin format.' }
$runtime = Join-Path $root ".local/vlm-runtime/$($pins.runtime.tag)"
$archive = Join-Path $runtime $pins.runtime.asset
$bin = Join-Path $runtime 'bin'
$server = Join-Path $bin 'llama-server.exe'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
    $partial = Join-Path $runtime ($pins.runtime.asset + '.partial-' + [guid]::NewGuid().ToString('N'))
    $url = "https://github.com/$($pins.runtime.repository)/releases/download/$($pins.runtime.tag)/$($pins.runtime.asset)"
    Write-Output "Downloading pinned llama.cpp server asset from $url"
    Invoke-WebRequest -Uri $url -OutFile $partial -MaximumRedirection 5
    if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ine $pins.runtime.sha256) {
        throw "Server archive failed the pinned SHA256 check; partial file retained at $partial"
    }
    if (Test-Path -LiteralPath $archive) { throw "Server archive destination appeared during download: $archive" }
    Move-Item -LiteralPath $partial -Destination $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ine $pins.runtime.sha256) {
    throw "Pinned llama.cpp server archive hash mismatch: $archive"
}

if (-not (Test-Path -LiteralPath $bin)) {
    $staging = Join-Path $runtime ('bin.partial-' + [guid]::NewGuid().ToString('N'))
    Expand-Archive -LiteralPath $archive -DestinationPath $staging
    if (-not (Test-Path -LiteralPath (Join-Path $staging 'llama-server.exe') -PathType Leaf)) {
        throw "Server executable missing from pinned archive; staging retained at $staging"
    }
    if (Test-Path -LiteralPath $bin) { throw "Server destination appeared during extraction: $bin" }
    Move-Item -LiteralPath $staging -Destination $bin
}
if (-not (Test-Path -LiteralPath $server -PathType Leaf)) {
    throw "Pinned server executable missing: $server"
}
$version = (& $server --version 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or
    $version -notmatch "build $($pins.runtime.tag.Substring(1))" -or
    $version -notmatch [regex]::Escape($pins.runtime.commit.Substring(0, 9))) {
    throw "Installed server does not match pinned $($pins.runtime.tag) build and commit."
}
$devices = (& $server --list-devices 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $devices -notmatch 'Vulkan\d+:') {
    throw 'The pinned Vulkan server found no Vulkan GPU. Check the graphics driver.'
}

if ($DownloadModel) {
    & (Join-Path $root 'download-model.ps1')
}

if (-not $SkipBuild) {
    $rust = (& rustc +1.95.0 --version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or $rust -notmatch '^rustc 1\.95\.0 ') {
        throw 'Install the pinned Rust 1.95.0 toolchain with rustup, then rerun setup.'
    }
    Push-Location $root
    try {
        & cargo +1.95.0 build --locked --release --bin coinpoker
        if ($LASTEXITCODE -ne 0) { throw 'Locked Windows release build failed.' }
    } finally {
        Pop-Location
    }
}
Write-Output 'Windows setup complete. Start the foreground server with scripts/start-vlm.ps1, then run doctor.'
