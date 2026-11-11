# p0-probe.ps1 -- manual p0_full predict against the Laya monitor using a saved
# PNG, replicating the run's request shape from the vendored question set.
# Usage: p0-probe.ps1 -Image <file.png>              (probe an existing frame)
#        p0-probe.ps1 -Shot <file.png> [-Hwnd H]     (pwshot first, then probe)
param(
  [string]$Hwnd = '0x2561d34',
  [string]$Image = '',
  [string]$Shot = ''
)
$ErrorActionPreference = 'Stop'
if ($Shot) {
  & (Join-Path $PSScriptRoot 'table-input.ps1') -Action pwshot -Hwnd $Hwnd -Path $Shot
  $Image = $Shot
}
if (-not $Image) { throw 'need -Image or -Shot' }
$root = Split-Path -Parent $PSScriptRoot
$qs = Get-Content (Join-Path $root 'crates\ingest\assets\laya\question-set.json') -Raw | ConvertFrom-Json
$p0 = $qs.passes | Where-Object { $_.id -eq 'p0_full' }
$questions = [ordered]@{}
foreach ($q in $p0.questions) {
  $entry = [ordered]@{ type = $q.type; instructions = $q.instructions }
  if ($q.criteria) {
    if ($q.criteria -is [Array]) {
      $entry.criteria = @($q.criteria)
    } else {
      $c = [ordered]@{}
      foreach ($label in $q.option_order) { $c[$label] = $q.criteria.$label }
      $entry.criteria = $c
    }
  }
  $questions[$q.id] = $entry
}
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $Image)))
$body = [ordered]@{
  model = 'coinpoker-laya-vision'; pass = 'p0_full'; note = $p0.note
  layout = $p0.layout; images_png_b64 = @($b64); questions = $questions
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
  $v = if ($null -ne $a.choice) { $a.choice }
       elseif ($null -ne $a.noul) { $a.noul }
       else { '?' }
  $p = ''
  if ($a.probabilities) { $p = ' (' + (($a.probabilities.PSObject.Properties | Sort-Object { -$_.Value } | Select-Object -First 1).Name) + '=' + (($a.probabilities.PSObject.Properties | Sort-Object { -$_.Value } | Select-Object -First 1).Value) + ')' }
  "$($_.Name) = $v$p conf=$($a.confidence)"
}
