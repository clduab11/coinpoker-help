# lobby-clicker.ps1 -- keep any seated hero in rotation. Discovers every live
# Unity table window each cycle, shoots it, and clicks the bottom-right
# "Join Now"/"Play Next Game" spot ONLY when the action bar is absent (bar up =
# the hero is to act and the raise button sits near that spot). Uses clicktop
# (no uncloak, so a live WGC capture survives). Bar detection mirrors the run's
# vendored action_buttons red check on a PrintWindow frame.
param(
  [int]$EverySec = 8
)
Add-Type -AssemblyName System.Drawing
# action_buttons content box for the 800x613 practice layout.
$BX = @(480, 542, 800, 613)
function Get-UnityWindows {
  $hwnds = @()
  foreach ($line in (& (Join-Path $PSScriptRoot 'table-input.ps1') -Action list)) {
    $text = "$line"
    if ($text -match 'class=UnityWndClass' -and $text -match 'hwnd=(0x[0-9a-fA-F]+)') {
      $hwnds += $Matches[1]
    }
  }
  return $hwnds
}
function Test-BarPresent([string]$hwnd) {
  $tmp = Join-Path $env:TEMP ("clicker-{0}.png" -f $hwnd.TrimStart('0x'))
  & (Join-Path $PSScriptRoot 'table-input.ps1') -Action pwshot -Hwnd $hwnd -Path $tmp | Out-Null
  $bmp = [System.Drawing.Bitmap]::FromFile((Resolve-Path $tmp))
  try {
    $red = 0
    $total = 0
    for ($y = $BX[1]; $y -lt [Math]::Min($BX[3], $bmp.Height); $y += 2) {
      for ($x = $BX[0]; $x -lt [Math]::Min($BX[2], $bmp.Width); $x += 2) {
        $c = $bmp.GetPixel($x, $y)
        $total++
        if ($c.R -ge 150 -and ($c.R - $c.G) -ge 40 -and ($c.R - $c.B) -ge 40) { $red++ }
      }
    }
  } finally {
    $bmp.Dispose()
  }
  return ($total -gt 0 -and ($red / $total) -gt 0.05)
}
while ($true) {
  foreach ($h in Get-UnityWindows) {
    try {
      if (-not (Test-BarPresent $h)) {
        & (Join-Path $PSScriptRoot 'table-input.ps1') -Action clicktop -Hwnd $h -X 731 -Y 581 -Repeat 1 | Out-Null
      }
    } catch {}
  }
  Start-Sleep -Seconds $EverySec
}
