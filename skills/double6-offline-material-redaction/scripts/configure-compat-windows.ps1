# Run once from an administrator PowerShell after installing an application-private LibreOffice.
param([Parameter(Mandatory=$true)][string]$Converter)
$ErrorActionPreference='Stop'
$exe=(Resolve-Path -LiteralPath $Converter).Path
$allowed=[IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Double6\LibreOffice\'))
if(-not $exe.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Use the application-private LOCALAPPDATA\Double6\LibreOffice copy; do not block a shared Office installation.'}
$bin=Join-Path (Split-Path $exe) 'soffice.bin'
if(-not (Test-Path -LiteralPath $bin -PathType Leaf)){throw 'Incomplete LibreOffice installation'}
if(@(Get-NetFirewallProfile | Where-Object {-not $_.Enabled}).Count -gt 0){throw 'Firewall is disabled for a profile; no configuration changed'}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
if(-not ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator PowerShell is required for these two application-specific outbound block rules'}
foreach($pair in @(@('Double6-Redaction-Compat-Launcher',$exe),@('Double6-Redaction-Compat-Engine',$bin))){
 $name=$pair[0];$program=$pair[1];$old=Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
 if($old){
  $filter=$old|Get-NetFirewallApplicationFilter
  if($filter.Program -ne $program -or $old.Direction -ne 'Outbound' -or $old.Action -ne 'Block' -or $old.Enabled -ne 'True' -or $old.Profile -ne 'Any'){throw 'A rule with this name differs; inspect it before making changes'}
 }else{New-NetFirewallRule -Name $name -DisplayName $name -Program $program -Direction Outbound -Action Block -Enabled True -Profile Any|Out-Null}
}
[Environment]::SetEnvironmentVariable('REDACTION_LIBREOFFICE',$exe,'User')
$env:REDACTION_LIBREOFFICE=$exe
[ordered]@{configured=$true;converter=$exe;scope='two application-private outbound block rules; no global profile changes';next='Open a new terminal and run RUNNER doctor and RUNNER inspect on a synthetic legacy document'}|ConvertTo-Json
