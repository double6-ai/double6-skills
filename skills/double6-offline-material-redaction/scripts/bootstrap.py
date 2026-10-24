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


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--venv',type=Path,required=True)
    p.add_argument('--wheelhouse',type=Path,help='已准备的本机wheel目录；指定后不访问软件源')
    a=p.parse_args()
    if sys.version_info[:2]!=(3,12) or sys.platform not in {'darwin','win32'}:
        p.error('请在Windows或macOS使用Python3.12运行安装。')
    if platform.machine().lower()not in ({'arm64','aarch64'}if sys.platform=='darwin'else{'amd64','x86_64'}):
        p.error('本版已登记macOS Apple芯片和Windows x64依赖。')
    if a.wheelhouse and not a.wheelhouse.is_dir():p.error('wheel目录不存在。')
    root=Path(__file__).resolve().parents[1];lock=root/'requirements-runtime.lock'
    dest=a.venv.expanduser().absolute();receipt=dest/'.redaction-install.json'
    identity={'version':'0.6.1','lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest()}
    python=dest/('Scripts/python.exe'if sys.platform=='win32'else'bin/python')
    if dest.exists():
        if not receipt.is_file()or json.loads(receipt.read_text(encoding='utf-8'))!=identity or not python.is_file():
            p.error('目标目录已有其它或未完成环境；请改用新目录，不覆盖。')
    else:
        venv.EnvBuilder(with_pip=True).create(dest)
        command=[str(python),'-m','pip','--isolated','--disable-pip-version-check','install','--require-hashes','--only-binary=:all:','--no-input']
        command+=['--no-index','--find-links',str(a.wheelhouse.resolve())]if a.wheelhouse else['--index-url','https://pypi.org/simple']
        subprocess.run(command+['-r',str(lock)],check=True)
    subprocess.run([str(python),'-m','pip','--isolated','check'],check=True)
    subprocess.run([str(python),str(root/'scripts/cli.py'),'doctor'],check=True)
    subprocess.run([str(python),str(root/'scripts/cli.py'),'selftest'],check=True)
    if not receipt.exists():
        with receipt.open('x',encoding='utf-8')as f:json.dump(identity,f)
    print(json.dumps({'ok':True,'version':identity['version'],'python':str(python),'command':[str(python),str(root/'scripts/cli.py')],'first_install_may_require_network':not bool(a.wheelhouse),'materials_uploaded':False},ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.CalledProcessError)as exc:
        print(json.dumps({'ok':False,'error':'安装或自检失败，保留现场；请查看上方具体错误，暂不处理真实材料。'},ensure_ascii=False));raise SystemExit(2)
