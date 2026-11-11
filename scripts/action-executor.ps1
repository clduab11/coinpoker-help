# action-executor.ps1 -- click the game's action bar when the run publishes a
# decision. Tails the run's stdout jsonl (event "decision"), translates the
# recommended action to the vendored button geometry, waits a short RANDOM
# delay (varied human pace; total capture->click bounded by -BudgetMs), then
# clicks via clicktop (raise + click; survives a live WGC capture). One click
# per decision line; the click spot is inert felt once the bar closes.
param(
  [Parameter(Mandatory)][string]$Jsonl,
  [string]$Hwnd = '0xd11f36',
  [int]$PollMs = 120,
  [int]$BudgetMs = 7500,   # jittered decision cap: capture -> click (10 s hard total)
  [int]$MinDelayMs = 250,
  [int]$MaxDelayMs = 1600,
  [switch]$DryRun
)
$ErrorActionPreference = 'Continue'
# Window-relative button centers for the 800x613 practice table layout.
$FOLD  = @(525, 581)
$MID   = @(635, 581)   # Check and Call share the middle button
$RAISE = @(746, 581)
$log = "$Jsonl.executor.log"
$seen = @{}
$pos = 0
while ($true) {
  try {
    $text = ''
    if (Test-Path $Jsonl) {
      $fs = [IO.File]::Open($Jsonl, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
      if ($fs.Length -gt $pos) {
        [void]$fs.Seek($pos, [IO.SeekOrigin]::Begin)
        $buf = New-Object byte[] ($fs.Length - $pos)
        [void]$fs.Read($buf, 0, $buf.Length)
        $text = [Text.Encoding]::UTF8.GetString($buf)
        $pos = $fs.Length
      }
      $fs.Close()
    }
    foreach ($line in ($text -split "`n")) {
      if ($line -notmatch '"event":"decision"') { continue }
      $evt = $null
      try { $evt = $line | ConvertFrom-Json } catch { continue }
      $key = if ($evt.observation) { $evt.observation | ConvertTo-Json -Compress } else { "$($evt.emitted_at_unix_ms)" }
      if ($seen.ContainsKey($key)) { continue }
      $seen[$key] = $true
      $action = "$($evt.action)"
      $pt = switch ($action) {
        'fold' { $FOLD }
        'check' { $MID }
        'call' { $MID }
        'raise' { $RAISE }
        'allin' { $RAISE }
        default { $null }
      }
      if (-not $pt) { continue }
      # Varied pace: mostly quick, sometimes thoughtful; never past the budget.
      $roll = Get-Random -Minimum 0 -Maximum 100
      if ($roll -lt 55) {
        $delay = Get-Random -Minimum $MinDelayMs -Maximum 650
      } elseif ($roll -lt 85) {
        $delay = Get-Random -Minimum 650 -Maximum 1150
      } else {
        $delay = Get-Random -Minimum 1150 -Maximum $MaxDelayMs
      }
      $finished = 0
      if ($evt.finished_in_ms) { $finished = [int]$evt.finished_in_ms }
      $budgetLeft = $BudgetMs - $finished - 300
      if ($budgetLeft -lt 120) { $budgetLeft = 120 }
      if ($delay -gt $budgetLeft) { $delay = $budgetLeft }
      $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
      if ($evt.expires_at_unix_ms) {
        $leaseLeft = [int]($evt.expires_at_unix_ms - $now) - 120
        if ($leaseLeft -lt 120) { $leaseLeft = 120 }
        if ($delay -gt $leaseLeft) { $delay = $leaseLeft }
      }
      $started = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
      Start-Sleep -Milliseconds $delay
      if (-not $DryRun) {
        & (Join-Path $PSScriptRoot 'table-input.ps1') -Action clicktop -Hwnd $Hwnd -X $pt[0] -Y $pt[1] -Repeat 1 | Out-Null
      }
      $elapsed = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() - $started + $delay
      $stamp = Get-Date -Format 'HH:mm:ss.fff'
      ("$stamp exec action=$action amount=$($evt.amount) ev=$($evt.ev) finished_ms=$finished delay_ms=$delay total_ms=$($finished + $elapsed) point=$($pt -join ',')") |
        Out-File -Append -Encoding utf8 $log
    }
  } catch {
    ("exec error: " + $_.Exception.Message) | Out-File -Append -Encoding utf8 $log
  }
  Start-Sleep -Milliseconds $PollMs
}
