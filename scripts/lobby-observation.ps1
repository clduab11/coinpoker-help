#Requires -Version 7.0
# Bounded lobby-only live check. Requires an observed executable name and lobby
# title. Does not pin a PID or HWND, does not save pixels, and does not close
# physical gate 8: one passing run is a single lobby view, not every lobby view
# or table preview.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ExeName,
    [Parameter(Mandatory)][string]$LobbyTitle,
    [int]$Seconds = 90,
    [string]$VlmEndpoint,
    [string]$VlmModel = 'coinpoker-gemma-4-e2b',
    [string]$Binary
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ExeName = $ExeName.Trim()
$LobbyTitle = $LobbyTitle.Trim()
if ([string]::IsNullOrWhiteSpace($ExeName) -or [string]::IsNullOrWhiteSpace($LobbyTitle)) {
    throw 'ExeName and LobbyTitle must be nonempty observed calibration.'
}
if ($Seconds -lt 5 -or $Seconds -gt 180) {
    throw 'Seconds must be from 5 through 180.'
}
if ([string]::IsNullOrWhiteSpace($VlmEndpoint)) {
    $VlmEndpoint = [Environment]::GetEnvironmentVariable('COINPOKER_VLM_ENDPOINT')
}
if (-not [string]::IsNullOrWhiteSpace($VlmEndpoint)) {
    $endpointUri = [Uri]$VlmEndpoint
    if ($endpointUri.Host -notin @('127.0.0.1', 'localhost', '::1')) {
        throw 'Refusing a non-loopback VLM endpoint for lobby observation.'
    }
}

$root = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Binary)) {
    $Binary = Join-Path $root 'target\release\coinpoker.exe'
    if (-not (Test-Path -LiteralPath $Binary -PathType Leaf)) {
        $Binary = Join-Path $root 'coinpoker.exe'
    }
}
if (-not (Test-Path -LiteralPath $Binary -PathType Leaf)) {
    throw "Windows coinpoker binary not found: $Binary"
}
$Binary = (Resolve-Path -LiteralPath $Binary).Path

$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$out = Join-Path $root ".local\acceptance\$stamp"
New-Item -ItemType Directory -Force -Path $out | Out-Null

function Start-Helper([string[]]$arguments) {
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $Binary
    $info.WorkingDirectory = $root
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $arguments) {
        [void]$info.ArgumentList.Add($argument)
    }
    foreach ($name in @('COINPOKER_PID', 'COINPOKER_WINDOW_HWND', 'COINPOKER_WINDOW_TITLE')) {
        if ($info.Environment.ContainsKey($name)) {
            [void]$info.Environment.Remove($name)
        }
    }
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $info
    return $process
}

function Stop-Helper($process) {
    if ($null -eq $process) { return }
    try {
        if (-not $process.HasExited) { $process.Kill($true) }
    } catch {
        try { if (-not $process.HasExited) { $process.Kill() } } catch { }
    }
    try { [void]$process.WaitForExit(5000) } catch { }
}

function Read-HelperOutput($process, [int]$timeoutMs) {
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $exited = $process.WaitForExit($timeoutMs)
    if (-not $exited) { Stop-Helper $process }
    return [pscustomobject]@{
        stdout = $stdoutTask.GetAwaiter().GetResult()
        stderr = $stderrTask.GetAwaiter().GetResult()
        exit_code = if ($process.HasExited) { $process.ExitCode } else { $null }
        timed_out = -not $exited
    }
}

function Convert-JsonLines([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return }
    foreach ($line in [regex]::Split($text, "\r?\n")) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        Write-Output ($line | ConvertFrom-Json)
    }
}

$listingProcess = $null
$liveProcess = $null
try {
    $listingProcess = Start-Helper @('--list-windows')
    $listing = Read-HelperOutput $listingProcess 30000
    [System.IO.File]::WriteAllText((Join-Path $out 'window-list.jsonl'), $listing.stdout)
    [System.IO.File]::WriteAllText((Join-Path $out 'window-list.stderr.txt'), $listing.stderr)
    if ($listing.timed_out -or $listing.exit_code -ne 0) {
        throw 'window listing failed; see window-list.stderr.txt'
    }
    $listed = Convert-JsonLines $listing.stdout
    $eligible = @($listed | Where-Object {
            $_.event -eq 'window' -and
            $null -ne $_.window -and
            [string]::Equals($_.window.exe_name, $ExeName, [StringComparison]::OrdinalIgnoreCase) -and
            $_.window.on_screen -eq $true -and
            $_.window.width -gt 0 -and
            $_.window.height -gt 0
        } | ForEach-Object { $_.window })
    if ($eligible.Count -eq 0) {
        throw "no on-screen window for $ExeName"
    }
    $nonLobby = @($eligible | Where-Object {
            -not ($_.title -is [string] -and $_.title.Contains($LobbyTitle))
        })
    if ($nonLobby.Count -gt 0) {
        $titles = ($nonLobby | ForEach-Object { $_.title }) -join ', '
        throw "refusing to observe: on-screen $ExeName window is not the lobby ($titles)"
    }

    $liveArgs = @('--exe-name', $ExeName, '--lobby-title', $LobbyTitle, '--vlm-model', $VlmModel)
    if (-not [string]::IsNullOrWhiteSpace($VlmEndpoint)) {
        $liveArgs += @('--vlm-endpoint', $VlmEndpoint)
    }
    $liveProcess = Start-Helper $liveArgs
    $live = Read-HelperOutput $liveProcess ($Seconds * 1000)
    [System.IO.File]::WriteAllText((Join-Path $out 'live.jsonl'), $live.stdout)
    [System.IO.File]::WriteAllText((Join-Path $out 'live.stderr.txt'), $live.stderr)
    $events = @(Convert-JsonLines $live.stdout)
    $statuses = @($events | Where-Object { $_.event -eq 'status' })
    $decisions = @($events | Where-Object { $_.event -eq 'decision' })
    $clears = @($events | Where-Object { $_.event -eq 'clear' })
    $lobbyHits = @($statuses | Where-Object { $_.state -eq 'lobby_detected' })
    $vetoes = @($statuses | Where-Object { $_.reason -eq 'lobby title; no table recommendations' })
    $discarded = @($events | Where-Object { $_.event -eq 'discarded' })
    $reasons = @($statuses | ForEach-Object { '{0} | {1}' -f $_.state, $_.reason })
    $settled = ($vetoes.Count -ge 1 -or $discarded.Count -ge 1)
    $earlyExit = (-not $live.timed_out) -and ($null -ne $live.exit_code) -and ($live.exit_code -ne 0)
    if ($decisions.Count -gt 0 -or $clears.Count -gt 0 -or $lobbyHits.Count -lt 1 -or $earlyExit) {
        $contract = 'FAIL'
    } elseif ($settled) {
        $contract = 'PASS'
    } else {
        $contract = 'INCOMPLETE'
    }
    $summary = [ordered]@{
        format = 1
        event = 'lobby_observation'
        utc = [DateTime]::UtcNow.ToString('o')
        seconds = $Seconds
        binary = $Binary
        binary_utc = (Get-Item -LiteralPath $Binary).LastWriteTimeUtc.ToString('o')
        exe_name = $ExeName
        lobby_title = $LobbyTitle
        table_title = $null
        pins = 'PID, HWND, and table title were removed from the child environment and were not passed as arguments.'
        vlm_endpoint = $VlmEndpoint
        vlm_model = $VlmModel
        pixels_saved = $false
        eligible_windows = @($eligible | ForEach-Object {
                [ordered]@{
                    title = $_.title
                    width = $_.width
                    height = $_.height
                    process_id = $_.process_id
                    hwnd = $_.hwnd
                }
            })
        status_reasons = $reasons
        decision_count = $decisions.Count
        clear_count = $clears.Count
        lobby_detected_count = $lobbyHits.Count
        lobby_veto_count = $vetoes.Count
        discarded_count = $discarded.Count
        helper_timed_out = [bool]$live.timed_out
        helper_exit_code = $live.exit_code
        contract = $contract
        gate_8 = 'UNRUN'
        limitation = 'One visible lobby view only. Other lobby views, table previews, and pixel-boundary checks remain untested.'
    }
    $reportPath = Join-Path $out 'lobby-observation.json'
    $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Output ("lobby-observation: " + $summary.contract)
    Write-Output ("eligible_windows: " + $eligible.Count)
    Write-Output ("lobby_detected: " + $lobbyHits.Count)
    Write-Output ("lobby_vetoes: " + $vetoes.Count)
    Write-Output ("discarded: " + $discarded.Count)
    Write-Output ("decisions: " + $decisions.Count)
    Write-Output ("clears: " + $clears.Count)
    foreach ($reason in $reasons) { Write-Output ("status: " + $reason) }
    Write-Output 'gate_8: UNRUN'
    Write-Output ("report: " + $reportPath)
    if ($contract -eq 'FAIL') { exit 1 }
    if ($contract -eq 'INCOMPLETE') { exit 2 }
} finally {
    Stop-Helper $liveProcess
    Stop-Helper $listingProcess
}
