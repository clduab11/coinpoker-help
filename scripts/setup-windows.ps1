param([switch]$DownloadModel, [switch]$SkipBuild, [string]$CondaPython = '')

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
    throw 'The pinned CUDA PyTorch wheels require Windows x64.'
}

$root = Split-Path -Parent $PSScriptRoot
$pins = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'laya-pins.json') -Raw | ConvertFrom-Json
if ($pins.format -ne 1) { throw 'Unsupported Laya pin format.' }
$envPrefix = Join-Path $root $pins.runtime.env_prefix
$python = Join-Path $envPrefix 'python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    # conda creates the interpreter only; every Python package is pip-installed at an exact pin below.
    $conda = @()
    if ($CondaPython) { $conda = @($CondaPython, '-m', 'conda') }
    elseif (Get-Command conda -ErrorAction SilentlyContinue) { $conda = @('conda') }
    else { throw 'conda not found. Pass -CondaPython <python.exe that has the conda package>.' }
    Write-Output "Creating the Laya environment at $envPrefix (python $($pins.runtime.python))"
    $exe = $conda[0]
    $rest = @($conda | Select-Object -Skip 1)
    & $exe @rest create --yes --prefix $envPrefix -c conda-forge --override-channels "python=$($pins.runtime.python)" pip
    if ($LASTEXITCODE -ne 0) { throw 'conda environment creation failed.' }
}

$packages = $pins.runtime.packages
& $python -m pip install --disable-pip-version-check --no-input `
    "torch==$($packages.torch)" "torchvision==$($packages.torchvision)" --index-url $pins.runtime.torch_index_url
if ($LASTEXITCODE -ne 0) { throw 'Pinned torch install failed.' }
& $python -m pip install --disable-pip-version-check --no-input `
    "transformers==$($packages.transformers)" "safetensors==$($packages.safetensors)" `
    "huggingface_hub==$($packages.huggingface_hub)" "numpy==$($packages.numpy)" "pillow==$($packages.pillow)" `
    "laya @ git+$($pins.runtime.laya.repository)@$($pins.runtime.laya.commit)"
if ($LASTEXITCODE -ne 0) { throw 'Pinned Laya package install failed.' }

$cuda = (& $python -c "import torch; print(torch.cuda.is_available())" 2>$null | Out-String).Trim()
if ($cuda -ne 'True') { throw 'The pinned CUDA torch build found no CUDA GPU. Check the NVIDIA driver.' }

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
Write-Output 'Windows setup complete. Start the foreground Laya server with scripts/start-vlm.ps1, then run doctor.'
