Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [System.Runtime.InteropServices.OSPlatform]::Windows)) {
    throw 'Windows acceptance requires a Windows host.'
}
if ([Environment]::OSVersion.Version.Build -lt 18362) {
    throw 'Windows 10 version 1903 (build 18362) or newer is required.'
}

$root = Split-Path -Parent $PSScriptRoot
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$out = Join-Path $root ".local/acceptance/$stamp"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$results = [System.Collections.Generic.List[object]]::new()

function Run-NativeCheck([string]$name, [string]$program, [string[]]$arguments) {
    $log = Join-Path $out "$name.log"
    try {
        & $program @arguments *> $log
        $code = $LASTEXITCODE
        $status = if ($code -eq 0) { 'PASS' } else { 'FAIL' }
    } catch {
        $status = 'FAIL'
        $code = 1
        $_.Exception.Message | Set-Content -LiteralPath $log -Encoding utf8
    }
    $results.Add([pscustomobject]@{ check = $name; status = $status; exit_code = $code; log = $log })
    Write-Output "$name`: $status"
}

Push-Location $root
try {
    $sourceCheckout = (Test-Path -LiteralPath 'Cargo.toml' -PathType Leaf) -and
        (Test-Path -LiteralPath 'scripts/validate.py' -PathType Leaf)
    if ($sourceCheckout) {
        Run-NativeCheck 'source-validation' 'python' @('scripts/validate.py')
        Run-NativeCheck 'release-build' 'cargo' @('+1.95.0', 'build', '--release', '--locked', '--bin', 'coinpoker')
    } else {
        $results.Add([pscustomobject]@{ check = 'source-validation'; status = 'BLOCKED'; exit_code = $null;
            log = ''; reason = 'Candidate bundle has no Rust source or validation suite.' })
        Write-Output 'source-validation: BLOCKED (source checkout required)'
    }

    $binary = Join-Path $root 'target/release/coinpoker.exe'
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
        $binary = Join-Path $root 'coinpoker.exe'
    }
    if (Test-Path -LiteralPath $binary -PathType Leaf) {
        Run-NativeCheck 'synthetic-evaluation' $binary @('--evaluate', 'fixtures/synthetic/manifest.json')
        $doctorLog = Join-Path $out 'doctor-offline.json'
        $doctorCode = 127
        try {
            & python 'scripts/doctor.py' --offline --binary $binary *> $doctorLog
            $doctorCode = $LASTEXITCODE
        } catch {
            $_.Exception.Message | Set-Content -LiteralPath $doctorLog -Encoding utf8
        }
        $doctorStatus = if ($doctorCode -eq 0) { 'PASS' } else { 'FAIL' }
        $results.Add([pscustomobject]@{ check = 'doctor-offline'; status = $doctorStatus; exit_code = $doctorCode;
            log = $doctorLog; reason = 'Local hashes, runtime, OS, and metadata diagnostics; inspect report for details.' })
        $results.Add([pscustomobject]@{ check = 'live-api-probes'; status = 'BLOCKED'; exit_code = $null;
            log = $doctorLog; reason = 'Offline mode intentionally skips generated-image HTTP probes.' })
        Write-Output "doctor-offline: $doctorStatus (inspect local report)"
        Write-Output 'live-api-probes: BLOCKED (offline mode)'
    } else {
        $results.Add([pscustomobject]@{ check = 'synthetic-evaluation'; status = 'FAIL'; exit_code = 1;
            log = ''; reason = 'Windows coinpoker.exe not found.' })
        Write-Output 'synthetic-evaluation: FAIL (binary missing)'
    }
} finally {
    Pop-Location
}

$gates = @{}
1..20 | ForEach-Object { $gates[[string]$_] = @{ status = 'UNRUN'; evidence = '' } }
$report = [ordered]@{
    format = 1
    event = 'windows_acceptance'
    utc = [DateTime]::UtcNow.ToString('o')
    windows_build = [Environment]::OSVersion.Version.Build
    architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    automated_checks = $results
    gates = $gates
    release_decision = 'NO-GO until applicable physical gates and exact-revision CI evidence are recorded'
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $out 'acceptance-v1.json') -Encoding utf8
Write-Output "Local report: $out"
Write-Output 'All 20 physical gates remain UNRUN. Complete docs/WINDOWS_ACCEPTANCE_V1.md with evidence.'
if (@($results | Where-Object { $_.status -eq 'FAIL' }).Count -gt 0) { exit 1 }
