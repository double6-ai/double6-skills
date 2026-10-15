# Measure template-fill outputs in Microsoft PowerPoint (Windows, COM). Read-only on the inputs.
param([Parameter(Mandatory=$true)][string]$InDir, [Parameter(Mandatory=$true)][string]$OutDir)
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
$preexisting = $app.Presentations.Count
$all = @()
function Measure-Shape($sh, $slideNo, $base) {
  $rows = @()
  if ($sh.Type -eq 6) { foreach ($g in $sh.GroupItems) { $rows += Measure-Shape $g $slideNo $base }; return $rows }
  if (-not $sh.HasTextFrame) { return $rows }
  $tf = $sh.TextFrame2
  if (-not $tf.HasText) { return $rows }
  $row = [ordered]@{ deck = $base; slide = $slideNo; id = $sh.Id; name = $sh.Name; height = $sh.Height; width = $sh.Width;
    margin_top = $tf.MarginTop; margin_bottom = $tf.MarginBottom; autosize = $tf.AutoSize; word_wrap = $tf.WordWrap;
    bound_height_open = $tf.TextRange.BoundHeight; font_size_first_run = $tf.TextRange.Runs(1).Font.Size }
  if ($tf.AutoSize -eq 2) {
    # force PowerPoint to recompute shrink-on-overflow (msoAutoSizeTextToFitShape) with its own engine
    $tf.AutoSize = 0; $tf.AutoSize = 2
    $row.recomputed = $true
  } else { $row.recomputed = $false }
  $row.bound_height_after = $tf.TextRange.BoundHeight
  $row.font_size_after = $tf.TextRange.Runs(1).Font.Size
  $avail = $sh.Height - $tf.MarginTop - $tf.MarginBottom
  $row.overflow_pt = [math]::Round($row.bound_height_after - $avail, 2)
  return ,([pscustomobject]$row)
}
Get-ChildItem -Path $InDir -Filter *.pptx | ForEach-Object {
  $base = $_.BaseName
  $pres = $app.Presentations.Open($_.FullName, $true, $false, $false)
  try {
    $n = 0
    foreach ($s in $pres.Slides) {
      $n++
      foreach ($sh in $s.Shapes) { $all += Measure-Shape $sh $n $base }
      $s.Export((Join-Path $OutDir ("{0}-slide{1:D2}.png" -f $base, $n)), 'PNG', 1280, 720)
    }
    $pres.SaveCopyAs((Join-Path $OutDir ($base + '.powerpoint.pptx')))
    $pres.SaveCopyAs((Join-Path $OutDir ($base + '.powerpoint.pdf')), 32)
  } finally { $pres.Close() }
}
if ($preexisting -eq 0) { $app.Quit() }
$all | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 (Join-Path $OutDir 'powerpoint_measure.json')
Write-Output "status=passed shapes=$($all.Count) version=$($app.Version)"
