# Measure template-fill outputs in Microsoft PowerPoint (Windows, COM). Read-only on the inputs.
param([Parameter(Mandatory=$true)][string]$InDir, [Parameter(Mandatory=$true)][string]$OutDir)
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
$preexisting = $app.Presentations.Count
$all = @()
$frames = @()
function Measure-Shape($sh, $slideNo, $base) {
  $rows = @()
  if ($sh.Type -eq 6) { foreach ($g in $sh.GroupItems) { $rows += Measure-Shape $g $slideNo $base }; return $rows }
  if (-not $sh.HasTextFrame) { return $rows }
  $tf = $sh.TextFrame2
  if (-not $tf.HasText) { return $rows }
  $row = [ordered]@{ deck = $base; slide = $slideNo; id = $sh.Id; name = $sh.Name; left = $sh.Left; top = $sh.Top; height = $sh.Height; width = $sh.Width;
    margin_top = $tf.MarginTop; margin_bottom = $tf.MarginBottom; autosize = $tf.AutoSize; word_wrap = $tf.WordWrap;
    bound_height_open = $tf.TextRange.BoundHeight; font_size_first_run = $tf.TextRange.Runs(1).Font.Size;
    bound_top_open = $tf.TextRange.BoundTop; bound_left_open = $tf.TextRange.BoundLeft; bound_width_open = $tf.TextRange.BoundWidth }
  $availOpen = $sh.Height - $tf.MarginTop - $tf.MarginBottom
  $row.overflow_open_pt = [math]::Round($row.bound_height_open - $availOpen, 2)
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
      foreach ($sh in $s.Shapes) {
        $frames += [pscustomobject]@{ deck = $base; slide = $n; id = $sh.Id; name = $sh.Name; left = $sh.Left; top = $sh.Top; width = $sh.Width; height = $sh.Height }
      }
      foreach ($sh in $s.Shapes) { $all += Measure-Shape $sh $n $base }
      $s.Export((Join-Path $OutDir ("{0}-slide{1:D2}.png" -f $base, $n)), 'PNG', 1280, 720)
    }
    $pres.SaveCopyAs((Join-Path $OutDir ($base + '.powerpoint.pptx')))
    $pres.SaveCopyAs((Join-Path $OutDir ($base + '.powerpoint.pdf')), 32)
  } finally { $pres.Close() }
}
if ($preexisting -eq 0) { $app.Quit() }
$all | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 (Join-Path $OutDir 'powerpoint_measure.json')
$frames | ConvertTo-Json -Depth 4 | Out-File -Encoding utf8 (Join-Path $OutDir 'powerpoint_frames.json')
Write-Output "status=passed shapes=$($all.Count) version=$($app.Version)"
