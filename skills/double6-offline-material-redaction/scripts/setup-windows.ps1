param([Parameter(Mandatory=$true)][string]$Venv,[string]$Wheelhouse)
$ErrorActionPreference='Stop'
# 安装入口兼容Windows PowerShell5；无Python时给出指引，不调用远程脚本。
$chosen=$null
if(Get-Command py -ErrorAction SilentlyContinue){
    foreach($minor in @('3.14','3.13','3.12','3.11','3.10')){
        $previous=$ErrorActionPreference;$ErrorActionPreference='Continue'
        try{$found=& py ('-'+$minor) -c 'import sys;print(sys.executable)' 2>$null}finally{$ErrorActionPreference=$previous}
        if($LASTEXITCODE -eq 0 -and $found){$chosen=[string]($found|Select-Object -Last 1);break}
    }
}
if(-not $chosen){
    foreach($name in @('python','python3')){
        $cmd=Get-Command $name -ErrorAction SilentlyContinue
        if($cmd){
            $found=& $cmd.Source -c 'import sys,platform;sys.exit(not ((3,10)<=sys.version_info[:2]<=(3,14) and platform.machine().lower() in {"amd64","x86_64"}));print(sys.executable)' 2>$null
            if($LASTEXITCODE -eq 0 -and $found){$chosen=[string]($found|Select-Object -Last 1);break}
        }
    }
}
if(-not $chosen){throw 'Python3.10-3.14 x64 is required. Install from python.org normally, then retry. Do not replace other Python installations.'}
$params=@((Join-Path $PSScriptRoot 'bootstrap.py'),'--venv',$Venv)
if($Wheelhouse){$params+=@('--wheelhouse',$Wheelhouse)}
& $chosen @params
if($LASTEXITCODE -ne 0){throw 'Installation or acceptance did not pass; no ready-to-use state was granted.'}
