"""创建独立环境并按哈希清单安装依赖；材料处理阶段不调用网络。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import venv
import shlex
import secrets
from datetime import datetime


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='strict')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--venv',type=Path,required=True)
    p.add_argument('--wheelhouse',type=Path,help='已准备的本机wheel目录；指定后不访问软件源')
    a=p.parse_args()
    if not ((3,10)<=sys.version_info[:2]<=(3,14)) or sys.platform not in {'darwin','win32'}:
        p.error('请在Windows或macOS使用Python3.10至3.14运行安装。')
    if platform.machine().lower()not in ({'arm64','aarch64'}if sys.platform=='darwin'else{'amd64','x86_64'}):
        p.error('本版已登记macOS Apple芯片和Windows x64依赖。')
    if a.wheelhouse and not a.wheelhouse.is_dir():p.error('wheel目录不存在。')
    root=Path(__file__).resolve().parents[1];lock=root/'requirements-runtime.lock'
    dest=a.venv.expanduser().absolute();receipt=dest/'.redaction-install.json'
    identity={'version':'0.7.1','lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest(),'python_minor':list(sys.version_info[:2]),'machine':platform.machine().lower()}
    python=dest/('Scripts/python.exe'if sys.platform=='win32'else'bin/python')
    if dest.exists():
        if not receipt.is_file()or json.loads(receipt.read_text(encoding='utf-8'))!=identity or not python.is_file():
            p.error('目标目录已有其它或未完成环境；请改用新目录，不覆盖。')
    else:
        venv.EnvBuilder(with_pip=True,symlinks=sys.platform!='win32').create(dest)
        command=[str(python),'-X','utf8','-m','pip','--isolated','--disable-pip-version-check','install','--require-hashes','--only-binary=:all:','--no-input']
        command+=['--no-index','--find-links',str(a.wheelhouse.resolve())]if a.wheelhouse else['--index-url','https://pypi.org/simple']
        subprocess.run(command+['-r',str(lock)],check=True)
    subprocess.run([str(python),'-m','pip','--isolated','check'],check=True)
    subprocess.run([str(python),str(root/'scripts/cli.py'),'doctor'],check=True)
    subprocess.run([str(python),str(root/'scripts/cli.py'),'selftest'],check=True)
    run=dest/'checks'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
    run.mkdir(parents=True,exist_ok=False)
    report=run/'acceptance.json'
    subprocess.run([str(python),str(root/'scripts/acceptance.py'),'--report',str(report)],check=True)
    tested=json.loads(report.read_text(encoding='utf-8'))
    launchers=run/'launchers';launchers.mkdir()
    starter=root/'scripts/offline_start.py'
    if sys.platform=='win32':
        filename=launchers/'Start-Redaction.cmd'
        quote=lambda x:'"'+str(x).replace('%','%%')+'"'
        text='@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\n'+quote(python)+' '+quote(starter)+' %*\r\nif errorlevel 1 pause\r\n'
        filename.write_bytes(text.encode('utf-8'))
        command='& "'+str(python)+'" "'+str(root/'scripts/cli.py')+'" gui'
    else:
        filename=launchers/'Start-Redaction.command'
        filename.write_text('#!/bin/sh\nexec '+shlex.quote(str(python))+' '+shlex.quote(str(starter))+' "$@"\n',encoding='utf-8');filename.chmod(0o700)
        command=shlex.quote(str(python))+' '+shlex.quote(str(root/'scripts/cli.py'))+' gui'
    guide=run/'离线使用说明.md'
    guide.write_text('# 本机材料脱敏\n\n正例 '+str(tested['positive']['passed'])+'/'+str(tested['positive']['total'])+'，反例 '+str(tested['negative']['passed'])+'/'+str(tested['negative']['total'])+' 已通过。\n\n双击同目录launchers文件夹中的 '+filename.name+' 启动；首次系统提示按正常方式打开，不关闭系统安全检查。工具会打开本机浏览器。选择文件，补选敏感内容，声明必须保留的内容，然后导出复检。默认新建同格式副本；不支持的原格式会停止，转换和PDF图像化须明确选择。\n\n也可离线执行：\n\n```text\n'+command+'\n```\n\n关闭标签页不会结束服务；请点击“结束工具并清空会话”。已下载副本保留，需自行在本机打开核对。真实文件、原文和补选词不要发给在线Agent。\n\n旧DOC/XLS/PPT/RTF转换依赖尚未在本次安装验收执行；如有需要按Skill兼容指引另行验证。\n',encoding='utf-8')
    if not receipt.exists():
        with receipt.open('x',encoding='utf-8')as f:json.dump(identity,f)
    print(json.dumps({'ok':True,'version':identity['version'],'python':str(python),'acceptance':str(report),'positive':tested['positive'],'negative':tested['negative'],'launcher':str(filename),'offline_guide':str(guide),'offline_command':command,'first_install_may_require_network':not bool(a.wheelhouse),'materials_uploaded':False},ensure_ascii=False))



if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.CalledProcessError)as exc:
        print(json.dumps({'ok':False,'error':'环境创建、依赖安装或验收未通过；失败目录保留，未生成可用状态。','failure_type':type(exc).__name__},ensure_ascii=False));raise SystemExit(2)
