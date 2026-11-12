# p1-probe.ps1 -- manual p1_hero_cards predict: crops the two hero card slots per
# the vendored regions.json and asks rank/suit of each, mirroring the run's wire.
# Usage: p1-probe.ps1 -Image <file.png> [ -Hwnd H | -Shot <file.png> ]
param(
  [string]$Hwnd = '0x2561d34',
  [string]$Image = '',
  [string]$Shot = '',
  [string]$OutDir = ''
)
$ErrorActionPreference = 'Stop'
if ($Shot) {
  & (Join-Path $PSScriptRoot 'table-input.ps1') -Action pwshot -Hwnd $Hwnd -Path $Shot
  $Image = $Shot
}
if (-not $Image) { throw 'need -Image or -Shot' }
if (-not $OutDir) { $OutDir = Split-Path -Parent (Resolve-Path $Image) }
Add-Type -AssemblyName System.Drawing
$root = Split-Path -Parent $PSScriptRoot
$regions = Get-Content (Join-Path $root 'crates\ingest\assets\laya\regions.json') -Raw | ConvertFrom-Json
$g = $regions.geometry

function Get-ContentRect([int]$w, [int]$h) {
  $t = $h - [Math]::Round(([double]$w / [double]$g.content_aspect), [MidpointRounding]::ToEven)
  if ($t -ge [int]$g.title_bar_range_px[0] -and $t -le [int]$g.title_bar_range_px[1]) {
    return @(0, [int]$t, $w, [int]($h - $t))
  }
  $tp = [int]$g.title_bar_px
  $avail = $h - $tp
  if ($avail -le 0) { return @(0, $tp, $w, 0) }
  if ($w / $avail -gt $g.content_aspect) {
    $cw = [int][Math]::Round(([double]$avail * [double]$g.content_aspect), [MidpointRounding]::ToEven)
    return @([math]::Floor(($w - $cw) / 2), $tp, $cw, $avail)
  } else {
    $ch = [int][Math]::Round(([double]$w / [double]$g.content_aspect), [MidpointRounding]::ToEven)
    return @(0, $tp + [math]::Floor(($avail - $ch) / 2), $w, $ch)
  }
}

function Get-BoxPx([string]$name, [int]$w, [int]$h) {
  $bx = $regions.regions.$name
  $cr = Get-ContentRect $w $h
  $x0 = [double]$cr[0]; $y0 = [double]$cr[1]; $cw = [double]$cr[2]; $ch = [double]$cr[3]
  $a = [int][math]::Floor($x0 + [double]$bx[0] * $cw); $a = [math]::Max(0, [math]::Min($a, $w))
  $b = [int][math]::Floor($y0 + [double]$bx[1] * $ch); $b = [math]::Max(0, [math]::Min($b, $h))
  $c = [int][math]::Ceiling($x0 + [double]$bx[2] * $cw); $c = [math]::Max(0, [math]::Min($c, $w))
  $d = [int][math]::Ceiling($y0 + [double]$bx[3] * $ch); $d = [math]::Max(0, [math]::Min($d, $h))
  @($a, $b, $c, $d)
}

$img = [System.Drawing.Image]::FromFile((Resolve-Path $Image))
$crops = @()
foreach ($name in @('hero_card_1', 'hero_card_2')) {
  $box = Get-BoxPx $name $img.Width $img.Height
  "DEBUG box type=$($box.GetType().Name) val=$($box -join ',')"
  $rect = New-Object System.Drawing.Rectangle -ArgumentList @([int]$box[0], [int]$box[1], [int]($box[2] - $box[0]), [int]($box[3] - $box[1]))
  $bmp = New-Object System.Drawing.Bitmap -ArgumentList @($rect.Width, $rect.Height)
  $gr = [System.Drawing.Graphics]::FromImage($bmp)
  $gr.DrawImage($img, (New-Object System.Drawing.Rectangle -ArgumentList @(0, 0, $rect.Width, $rect.Height)), $rect, [System.Drawing.GraphicsUnit]::Pixel)
  $gr.Dispose()
  $p = Join-Path $OutDir ("p1probe-$name.png")
  $bmp.Save($p, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  "$name box=$(($box -join ',')) -> $p"
  $crops += [Convert]::ToBase64String([IO.File]::ReadAllBytes($p))
}
$img.Dispose()

$qs = Get-Content (Join-Path $root 'crates\ingest\assets\laya\question-set.json') -Raw | ConvertFrom-Json
$p1 = $qs.passes | Where-Object { $_.id -eq 'p1_hero_cards' }
$questions = [ordered]@{}
foreach ($q in $p1.questions) {
  $entry = [ordered]@{ type = $q.type; instructions = $q.instructions }
  if ($q.criteria) {
    if ($q.criteria -is [Array]) { $entry.criteria = @($q.criteria) }
    else {
      $c = [ordered]@{}
      foreach ($label in $q.option_order) { $c[$label] = $q.criteria.$label }
      $entry.criteria = $c
    }
  }
  $questions[$q.id] = $entry
}
$body = [ordered]@{
  model = 'coinpoker-laya-vision'; pass = 'p1_hero_cards'; note = $p1.note
  layout = $p1.layout; images_png_b64 = @($crops); questions = $questions
}
$json = $body | ConvertTo-Json -Depth 8 -Compress
try {
  $r = Invoke-WebRequest -Method POST -Uri 'http://127.0.0.1:18090/v1/laya/predict' -Body $json -ContentType 'application/json' -UseBasicParsing -TimeoutSec 60
} catch {
  'STATUS ' + $_.Exception.Response.StatusCode.value__
  if ($_.Exception.Response) {
    $sr = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream()); $sr.ReadToEnd()
  }
  exit 1
}
$j = $r.Content | ConvertFrom-Json
"model=$($j.model) pass=$($j.pass) floor=$($j.acceptance_floor)"
$j.answers.PSObject.Properties | ForEach-Object {
  $a = $_.Value
  $v = if ($null -ne $a.choice) { $a.choice } elseif ($null -ne $a.noul) { $a.noul } else { '?' }
  "$($_.Name) = $v conf=$($a.confidence)"
}
