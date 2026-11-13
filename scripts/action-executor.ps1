# action-executor.ps1 -- fail-closed clicker for the game's action bar.
#
# Tails the run's stdout JSONL. For every fresh "decision" record it validates
# identity, lease and geometry, clicks the action (activating + uncloaking the
# table first), then requires read-back evidence from the stream before the
# next click. Anything uncertain aborts clicking instead of clicking again.
#
# Hardening contract (handoff Phase 4):
#  1. Identity comes from the decision stream (observation.identity), never a
#     constant. -Hwnd/-ProcessId are optional pins and must match the stream.
#  2. Every click activates the window first (clickrel uncloaks + activates;
#     click twice: first click activates, second acts).
#  3. Coordinates scale from the 800x613 reference to the actual window rect.
#     A non-proportional rect is refused (geometry-mismatch), not guessed.
#  4. Raise honours `amount`: raise button, then typed amount, then Enter
#     (RaiseMode type-enter). RaiseMode click restores single-click behaviour.
#  5. Read-back: after a click, a bounded window must show changed stream
#     content (new decision / changed partial / changed observation / clear),
#     otherwise `action-unverified` aborts (exit 2) unless -ContinueOnUnverified.
#  6. Turn guard: never click a decision whose lease is already dead or shorter
#     than -MinLeaseMs, and never fire a second click while one is unverified.
#  7. Abort switch: a stop file (default `<jsonl>.stop`) stops clicking and
#     exits; the executor also exits when the stream stalls (-EofGraceMs).
#
# -DryRun plans everything and logs `dry-click` lines without touching input.
param(
  [Parameter(Mandatory)][string]$Jsonl,
  [string]$Hwnd = '',
  [int]$ProcessId = 0,
  [string]$StopFile = '',
  [int]$PollMs = 120,
  [int]$BudgetMs = 7500,    # jittered decision cap: capture -> click (10 s hard total)
  [int]$MinDelayMs = 250,
  [int]$MaxDelayMs = 1600,
  [int]$MinLeaseMs = 1500,  # safety floor: skip clicks with less lease remaining
  [int]$VerifyMs = 6000,    # read-back window after a click
  [int]$EofGraceMs = 20000, # stream stalled this long -> exit
  [ValidateSet('clickrel', 'clicktop')][string]$ClickMode = 'clickrel',
  [ValidateSet('click', 'type', 'type-enter')][string]$RaiseMode = 'type-enter',
  [switch]$SkipGeometry,    # offline/inspection use when no window exists
  [switch]$ContinueOnUnverified,
  [switch]$DryRun
)
$ErrorActionPreference = 'Continue'
if (-not $StopFile) { $StopFile = "$Jsonl.stop" }
# Window-relative button centers for the 800x613 practice table layout (reference).
$REF_WIDTH = 800
$REF_HEIGHT = 613
$FOLD = @(525, 581)
$MID = @(635, 581)   # Check and Call share the middle button
$RAISE = @(746, 581)
$log = "$Jsonl.executor.log"
$logDir = Split-Path -Parent $Jsonl
if ($logDir -and -not (Test-Path $logDir)) { New-Item -ItemType Directory -Force $logDir | Out-Null }
$EXECUTOR_VERSION = 'hardened-1'

# Envelope keys from leased_record()/event_record(): volatile, excluded from
# content comparison used for read-back verification.
$ENVELOPE_KEYS = @('schema_version', 'event', 'observation', 'captured_at_unix_ms',
  'valid_for_ms', 'emitted_at_unix_ms', 'expires_at_unix_ms', 'finished_in_ms',
  'source_age_ms', 'source_current')
$EVIDENCE_EVENTS = @('partial_observation', 'observation', 'decision', 'clear')
$VERIFY_CLEARS = @('action-not-required', 'frame-changed', 'decision-suppressed', 'screen-not-accepted')

function Write-Log([string]$message) {
  $stamp = Get-Date -Format 'HH:mm:ss.fff'
  "$stamp pid=$PID $message" | Out-File -Append -Encoding utf8 $log
}

function ConvertTo-HexValue([string]$value) {
  if (-not $value) { return $null }
  if ($value -match '^0x') { return [int64]("0x" + $value.Substring(2)) }
  return [int64]$value
}

function Get-ContentHash($evt) {
  $copy = [ordered]@{}
  foreach ($property in $evt.PSObject.Properties) {
    if ($ENVELOPE_KEYS -notcontains $property.Name) { $copy[$property.Name] = $property.Value }
  }
  return ($copy | ConvertTo-Json -Compress -Depth 12)
}

function Get-DecisionKey($evt) {
  if ($evt.observation) { return ($evt.observation | ConvertTo-Json -Compress) }
  return "$($evt.emitted_at_unix_ms)"
}

# Cached per-hwnd scale from the actual window rect; refuses non-proportional sizes.
$geometry = @{}
function Get-Geometry([int64]$hwndValue, [string]$hwndHex) {
  if ($geometry.ContainsKey($hwndValue)) { return $geometry[$hwndValue] }
  $result = @{ scale = 1.0; width = $REF_WIDTH; height = $REF_HEIGHT; source = 'reference' }
  if (-not $SkipGeometry) {
    try {
      $rows = & (Join-Path $PSScriptRoot 'table-input.ps1') -Action list 2>$null
      $pattern = 'hwnd=0x' + ('{0:x}' -f $hwndValue) + ' '
      $row = $rows | Where-Object { $_ -like "*$pattern*" } | Select-Object -First 1
      if ($row -and $row -match 'rect=(-?\d+),(-?\d+),(-?\d+),(-?\d+)') {
        $width = [int]$Matches[3] - [int]$Matches[1]
        $height = [int]$Matches[4] - [int]$Matches[2]
        if ($width -gt 0 -and $height -gt 0) {
          $sx = $width / $REF_WIDTH
          $sy = $height / $REF_HEIGHT
          if ([math]::Abs($sx - $sy) -le 0.02) {
            $result = @{ scale = $sx; width = $width; height = $height; source = 'scaled' }
          } else {
            $result = @{ scale = -1.0; width = $width; height = $height; source = 'geometry-mismatch' }
          }
        }
      }
    } catch {
      Write-Log "geometry probe failed: $($_.Exception.Message)"
    }
  }
  $geometry[$hwndValue] = $result
  return $result
}

function Get-Point($point, [double]$scale) {
  return @([int][math]::Round($point[0] * $scale), [int][math]::Round($point[1] * $scale))
}

# One decision -> planned steps (used identically by dry and real paths).
function Get-Plan($action, [long]$amount, [double]$scale) {
  $steps = @()
  switch ($action) {
    'fold' { $steps += @{ kind = 'click'; point = (Get-Point $FOLD $scale) } }
    'check' { $steps += @{ kind = 'click'; point = (Get-Point $MID $scale) } }
    'call' { $steps += @{ kind = 'click'; point = (Get-Point $MID $scale) } }
    'raise' {
      $steps += @{ kind = 'click'; point = (Get-Point $RAISE $scale) }
      if ($RaiseMode -ne 'click' -and $amount -gt 0) {
        $steps += @{ kind = 'type'; text = "$amount" }
        if ($RaiseMode -eq 'type-enter') { $steps += @{ kind = 'type'; text = '{ENTER}' } }
      }
    }
    'allin' { $steps += @{ kind = 'click'; point = (Get-Point $RAISE $scale) } }
    default { return $null }
  }
  return $steps
}

Write-Log "executor $EXECUTOR_VERSION start jsonl=$Jsonl dry=$DryRun click=$ClickMode raise=$RaiseMode pin_hwnd=$Hwnd pin_process=$ProcessId"
if (Test-Path $StopFile) { Write-Log "stop-file-present $StopFile"; exit 0 }

$seen = @{}
$pos = 0
$lastGrowth = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$fileExisted = $false
$queue = $null          # newest unclicked decision
$queueKey = ''
$pending = $null        # clicked, awaiting read-back
$pendingBaseline = $null
$lastContentHash = $null

function Read-NewText {
  $text = ''
  if (Test-Path $Jsonl) {
    if (-not $script:fileExisted) { $script:fileExisted = $true }
    $fs = [IO.File]::Open($Jsonl, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    if ($fs.Length -gt $script:pos) {
      [void]$fs.Seek($script:pos, [IO.SeekOrigin]::Begin)
      $buf = New-Object byte[] ($fs.Length - $script:pos)
      [void]$fs.Read($buf, 0, $buf.Length)
      $text = [Text.Encoding]::UTF8.GetString($buf)
      $script:pos = $fs.Length
    }
    $fs.Close()
  }
  return $text
}

function Test-Verified($evt) {
  if (-not $script:pending) { return $null }
  if ($evt.event -eq 'decision') {
    if ((Get-DecisionKey $evt) -ne $script:pending.key) { return 'new-decision' }
    return $null
  }
  if ($evt.event -eq 'clear' -and $VERIFY_CLEARS -contains "$($evt.reason)") {
    return "clear:$($evt.reason)"
  }
  if ($EVIDENCE_EVENTS -contains $evt.event) {
    $hash = Get-ContentHash $evt
    if ($hash -ne $script:pendingBaseline) { return "content-changed:$($evt.event)" }
  }
  return $null
}

# Exit helper: a pending click at an exit boundary is unverified -> abort(2)
# unless -ContinueOnUnverified. Operator stop and stream EOF both fail closed.
function Exit-FailClosed([string]$reason) {
  if ($script:pending) {
    Write-Log "action-unverified action=$($script:pending.action) hwnd=$($script:pending.identity) reason=$reason"
    if (-not $ContinueOnUnverified) {
      Write-Log 'abort-on-unverified -> exiting(2)'
      exit 2
    }
  }
  exit 0
}

# Validate + fire the queued decision (no-op when a click is pending).
function Invoke-QueueDecision([int64]$nowMs) {
  if ($script:pending -or -not $script:queue) { return }
  $evt = $script:queue
  $action = "$($evt.action)"
  $identity = $evt.observation.identity
  if (-not $identity -or -not $identity.hwnd) {
    Write-Log "identity-missing action=$action; skipping"
    $script:queue = $null; $script:queueKey = ''
    return
  }
  $streamHwndHex = "$($identity.hwnd)"
  $streamHwnd = ConvertTo-HexValue $streamHwndHex
  $streamPid = [int64]"$($identity.process_id)"
  $mismatch = $null
  if ($Hwnd -and (ConvertTo-HexValue $Hwnd) -ne $streamHwnd) { $mismatch = "hwnd pin=$Hwnd stream=$streamHwndHex" }
  if ($ProcessId -and $ProcessId -ne $streamPid) { $mismatch = "pid pin=$ProcessId stream=$streamPid" }
  if ($mismatch) {
    Write-Log "identity-mismatch $mismatch; refusing click for action=$action"
    $script:queue = $null; $script:queueKey = ''
    return
  }
  if ($evt.expires_at_unix_ms -and ([int64]$evt.expires_at_unix_ms - $nowMs) -lt $MinLeaseMs) {
    Write-Log "lease-expired action=$action remaining_ms=$([int64]$evt.expires_at_unix_ms - $nowMs)"
    $script:queue = $null; $script:queueKey = ''
    return
  }
  $geo = Get-Geometry $streamHwnd $streamHwndHex
  if ($geo.scale -lt 0) {
    Write-Log "geometry-mismatch hwnd=$streamHwndHex rect=$($geo.width)x$($geo.height); refusing click"
    $script:queue = $null; $script:queueKey = ''
    return
  }
  $plan = Get-Plan $action ([long]$evt.amount) $geo.scale
  if (-not $plan) {
    Write-Log "unknown-action $action; skipping"
    $script:queue = $null; $script:queueKey = ''
    return
  }
  # Jittered pace inside budget and lease. Tiers are clamped so overridden
  # small MinDelay/MaxDelay bounds stay valid (Get-Random needs min < max).
  $loDelay = [math]::Max(1, $MinDelayMs)
  if ($MaxDelayMs -le $loDelay) { $MaxDelayMs = $loDelay + 1 }
  $hiDelay = $MaxDelayMs
  $tier1 = [math]::Min(650, $hiDelay); if ($tier1 -le $loDelay) { $tier1 = $loDelay + 1 }
  $tier2 = [math]::Min(1150, $hiDelay); if ($tier2 -le $tier1) { $tier2 = $tier1 + 1 }
  $hiDelay = [math]::Max($hiDelay, $tier2 + 1)
  $roll = Get-Random -Minimum 0 -Maximum 100
  if ($roll -lt 55) { $delay = Get-Random -Minimum $loDelay -Maximum $tier1 }
  elseif ($roll -lt 85) { $delay = Get-Random -Minimum $tier1 -Maximum $tier2 }
  else { $delay = Get-Random -Minimum $tier2 -Maximum $hiDelay }
  $finished = 0
  if ($evt.finished_in_ms) { $finished = [int]$evt.finished_in_ms }
  $budgetLeft = $BudgetMs - $finished - 300
  if ($budgetLeft -lt 120) { $budgetLeft = 120 }
  if ($delay -gt $budgetLeft) { $delay = $budgetLeft }
  if ($evt.expires_at_unix_ms) {
    $leaseLeft = [int]([int64]$evt.expires_at_unix_ms - ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())) - 120
    if ($leaseLeft -lt 120) { $leaseLeft = 120 }
    if ($delay -gt $leaseLeft) { $delay = $leaseLeft }
  }
  Start-Sleep -Milliseconds $delay
  $clickedAt = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  $points = ($plan | Where-Object { $_.kind -eq 'click' } | ForEach-Object { $_.point -join ',' }) -join '|'
  Write-Log ("{0} action=$action amount=$($evt.amount) hwnd=$streamHwndHex pid=$streamPid scale={1:N3} mode=$ClickMode point=$points delay_ms=$delay total_ms=$($finished + $delay)" -f $(if ($DryRun) { 'dry-click' } else { 'click' }), $geo.scale)
  if (-not $DryRun) {
    foreach ($step in $plan) {
      if ($step.kind -eq 'click') {
        & (Join-Path $PSScriptRoot 'table-input.ps1') -Action $ClickMode -Hwnd $streamHwndHex `
          -X $step.point[0] -Y $step.point[1] -Repeat 2 | Out-Null
      } else {
        & (Join-Path $PSScriptRoot 'table-input.ps1') -Action type -Text $step.text | Out-Null
      }
      Start-Sleep -Milliseconds 220
    }
  }
  if ($action -eq 'allin') { Write-Log 'allin-uses-raise-button (amount not typed)' }
  $script:pending = @{
    key       = $script:queueKey
    action    = $action
    identity  = $streamHwndHex
    clickedAt = $clickedAt
    deadline  = $clickedAt + $VerifyMs
  }
  $script:pendingBaseline = $script:lastContentHash
  $script:queue = $null; $script:queueKey = ''
}

while ($true) {
  try {
    if (Test-Path $StopFile) { Write-Log "stop-file $StopFile -> exiting"; Exit-FailClosed 'stop-file' }
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $text = Read-NewText
    if ($text.Length -gt 0) { $lastGrowth = $now }
    elseif ($fileExisted -and ($now - $lastGrowth) -ge $EofGraceMs) {
      Write-Log "stream-eof no growth for ${EofGraceMs}ms -> exiting"
      Exit-FailClosed 'stream-eof'
    }

    foreach ($line in ($text -split "`n")) {
      if (-not $line.Trim() -or $line -notmatch '"event"') { continue }
      $evt = $null
      try { $evt = $line | ConvertFrom-Json } catch { continue }

      # Read-back first: any new evidence line can verify the pending click.
      $verified = Test-Verified $evt
      if ($verified) {
        $elapsed = [math]::Max(0, [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $pending.clickedAt)
        Write-Log "action-verified action=$($pending.action) hwnd=$($pending.identity) evidence=$verified after_ms=$elapsed"
        $pending = $null
      }

      if ($EVIDENCE_EVENTS -contains $evt.event) { $lastContentHash = Get-ContentHash $evt }

      if ($evt.event -ne 'decision') { continue }
      $key = Get-DecisionKey $evt
      if ($seen.ContainsKey($key)) { continue }
      $seen[$key] = $true
      if ($queue) { Write-Log "decision-dropped stale_queued=$queueKey" }
      $queue = $evt
      $queueKey = $key
      Invoke-QueueDecision $now
    }

    if ($pending) {
      $mow = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
      if ($mow -ge $pending.deadline) {
        Write-Log "action-unverified action=$($pending.action) hwnd=$($pending.identity) within_ms=$VerifyMs"
        if (-not $ContinueOnUnverified) {
          Write-Log 'abort-on-unverified -> exiting(2)'
          exit 2
        }
        $pending = $null
      }
    }
  } catch {
    Write-Log ("exec error: " + $_.Exception.Message)
  }
  Start-Sleep -Milliseconds $PollMs
}
