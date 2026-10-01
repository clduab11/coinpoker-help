param([switch]$Verify)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$root = $PSScriptRoot
$pins = Get-Content -LiteralPath (Join-Path $root 'scripts/vlm-pins.json') -Raw | ConvertFrom-Json
if ($pins.format -ne 1) { throw 'Unsupported VLM pin format.' }
$models = Join-Path $root 'models'
$target = Join-Path $models $pins.model.directory
$sourceRevision = @(
    'format=2'
    "repository=$($pins.model.repository)"
    "revision=$($pins.model.revision)"
    "model=$($pins.model.files[0].name)"
    "projector=$($pins.model.files[1].name)"
)

function Assert-ModelFiles([string]$directory) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        throw "Pinned model directory is missing: $directory"
    }
    foreach ($artifact in $pins.model.files) {
        $path = Join-Path $directory $artifact.name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Missing model artifact: $($artifact.name)"
        }
        if ((Get-Item -LiteralPath $path).Length -ne $artifact.size) {
            throw "Wrong size for model artifact: $($artifact.name)"
        }
        if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $artifact.sha256) {
            throw "SHA256 mismatch for model artifact: $($artifact.name)"
        }
    }
    $source = Join-Path $directory 'SOURCE_REVISION'
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw 'Model provenance file is missing.'
    }
    $actual = @(Get-Content -LiteralPath $source)
    if (($actual -join "`n") -cne ($sourceRevision -join "`n")) {
        throw 'Model provenance does not match the pinned GGUF and projector.'
    }
}

if (Test-Path -LiteralPath $target) {
    Assert-ModelFiles $target
    Write-Output "Verified pinned model and projector: $target"
    return
}
if ($Verify) { throw "Pinned model is missing: $target" }

New-Item -ItemType Directory -Force -Path $models | Out-Null
$staging = Join-Path $models ('.' + $pins.model.directory + '.partial-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging | Out-Null
Write-Output "Downloading $($pins.model.repository)@$($pins.model.revision) into $staging"
Write-Output 'Review MODEL_LICENSES.md and the upstream model license before downloading.'
foreach ($artifact in $pins.model.files) {
    $url = "https://huggingface.co/$($pins.model.repository)/resolve/$($pins.model.revision)/$($artifact.name)?download=true"
    $path = Join-Path $staging $artifact.name
    Invoke-WebRequest -Uri $url -OutFile $path -MaximumRedirection 5
    if ((Get-Item -LiteralPath $path).Length -ne $artifact.size -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ine $artifact.sha256) {
        throw "Downloaded artifact failed the pinned size/SHA256 check: $($artifact.name); staging was retained at $staging"
    }
}
Set-Content -LiteralPath (Join-Path $staging 'SOURCE_REVISION') -Value $sourceRevision -Encoding utf8
Assert-ModelFiles $staging
if (Test-Path -LiteralPath $target) { throw "Model destination appeared during download: $target" }
Move-Item -LiteralPath $staging -Destination $target
Write-Output "Verified pinned model and projector installed: $target"
