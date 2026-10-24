"""CI安装链路：只用合成材料，验证复制后的Skill和实际启动入口。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

NAME = 'double6-offline-material-redaction'
FORBIDDEN = {'agents', 'evals', 'security', 'reports', 'dist', '.cache', '__pycache__'}


def files(root):
    result = {}
    for p in sorted(root.rglob('*')):
        relative = p.relative_to(root)
        if any(part in FORBIDDEN for part in relative.parts) or p.suffix == '.pyc':
            continue
        if p.is_symlink():
            raise ValueError('安装源码中不接受符号链接文件')
        if p.is_file():
            if p.name == 'manifest.json':
                raise ValueError('安装源码包含本地治理文件')
            result[relative.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def request(base, route, payload, headers=None):
    body = json.dumps(payload).encode() if isinstance(payload, dict) else payload
    headers = {'Origin': base.split('/', 3)[0] + '//' + base.split('/', 3)[2],
               'Content-Type': 'application/json' if isinstance(payload, dict) else 'application/octet-stream',
               **(headers or {})}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(urllib.request.Request(base + route, body, headers, method='POST'), timeout=90)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    source = args.source.resolve()
    installed = args.work.resolve() / '项目 技能' / NAME
    expected = files(source)
    shutil.copytree(source, installed, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'agents', 'evals', 'security', 'manifest.json', 'reports', 'dist', '.cache'))
    if files(installed) != expected:
        raise ValueError('复制后源码与当前候选不一致')
    report = {'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version(),
              'head_revision': os.environ.get('GITHUB_SHA'), 'installed_files': expected, 'steps': [], 'ok': False}
    report_path = args.work / 'install-chain.json'

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    child = None
    try:
        env = args.work.resolve() / '运行 环境'
        command = [sys.executable, str(installed / 'scripts/bootstrap.py'), '--venv', str(env)]
        if args.wheelhouse:
            command += ['--wheelhouse', str(args.wheelhouse.resolve())]
        log_path = args.work / 'install.log'
        with log_path.open('wb') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=300, check=True)
        receipt = json.loads(log_path.read_text(encoding='utf-8').splitlines()[-1])
        acceptance = json.loads(Path(receipt['acceptance']).read_text(encoding='utf-8'))
        assert acceptance['ok'] and acceptance['positive']['passed'] == acceptance['positive']['total'] and acceptance['negative']['passed'] == acceptance['negative']['total']
        report.update(receipt=receipt, acceptance=acceptance)
        report['steps'].append('复制后的完整Skill安装与正反例验收')
        with (args.work / 'regression.log').open('wb') as log:
            # 加墨回归大约多了 90 份双渲染导出。Windows 上原先接近 180 秒，放到 300 秒，不删漏脱样例。
            subprocess.run([receipt['python'], '-m', 'unittest', 'discover', '-s', str(installed / 'scripts/tests'), '-v'], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
        report['steps'].append('安装目录内源码回归')
        save()
        for iteration in range(2):
            session = args.work.resolve() / ('session-' + str(iteration) + '.json')
            launch_log = (args.work / ('launch-' + str(iteration) + '.log')).open('wb')
            launcher = receipt['launcher']
            command = ('cmd.exe /d /s /c ""' + launcher + '" --no-browser --session-file "' + str(session) + '""') if sys.platform == 'win32' else [launcher, '--no-browser', '--session-file', str(session)]
            child = subprocess.Popen(command, stdout=launch_log, stderr=subprocess.STDOUT)
            started = time.monotonic()
            info = None
            try:
                deadline = started + 90
                while time.monotonic() < deadline:
                    if session.exists():
                        try:
                            info = json.loads(session.read_text(encoding='utf-8'))
                        except json.JSONDecodeError:
                            info = None
                        else:
                            break
                    if child.poll() is not None and not session.exists():
                        raise RuntimeError('生成的启动器提前退出')
                    time.sleep(.1)
                if not info:
                    raise TimeoutError('启动器90秒内未生成会话回执，查看对应launch日志')
                report.setdefault('launches', []).append({'iteration': iteration, 'pid': child.pid, 'ready_seconds': round(time.monotonic() - started, 3)})
                save()
                url = info['url']
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                assert 'pdf-mode' in opener.open(url, timeout=10).read().decode('utf-8')
                if iteration == 0:
                    # 导入/下载来自实际本地HTTP服务，不把返回ok当作唯一核对。
                    probe = args.work / 'probe.py'
                    probe.write_text('''import sys,json,io,urllib.parse
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
from redaction_install_smoke import request
import acceptance as a,pdf_preserve,image_native
url=sys.argv[3];opener=__import__('urllib.request',fromlist=['build_opener']).build_opener(__import__('urllib.request',fromlist=['ProxyHandler']).ProxyHandler({}))
job=json.load(request(url,'api/import',a.word(),{'X-File-Kind':'word','X-File-Extension':'.docx','X-File-Name':urllib.parse.quote(a.SECRET+'_13800000000.docx')}))
r=json.load(request(url,'api/export',{'id':job['id'],**a.plan('word')}));response=opener.open(url+r['download']);data=response.read();header=urllib.parse.unquote(response.headers['Content-Disposition']);assert a.SECRET not in header and '13800000000'not in header and 'redacted-'in header
import output_policy
assert all(output_policy.verify(data,'.docx',a.plan('word'))['checks'].values())
request(url,'api/clear',{}).read()
source=a.pdf();job=json.load(request(url,'api/import',source,{'X-File-Kind':'pdf','X-File-Extension':'.pdf'}));opener.open(url+'file/'+job['id']+'/page/1').read()
plan=a.pdf_plan();region=json.load(request(url,'api/snap-pdf',{'id':job['id'],'page':1,'rectangle':plan['pages'][0]['rectangles'][0]}))['rectangle'];plan['pages'][0]['rectangles']=[region]
r=json.load(request(url,'api/export',{'id':job['id'],**plan}));data=opener.open(url+r['download']).read();report=pdf_preserve.verify(data,plan,source)
with pdf_preserve.backend().open(stream=data,filetype='pdf')as d:text='\\n'.join(p.get_text()for p in d)
assert a.SECRET not in text and a.KEEP in text
request(url,'api/invalidate',{'id':job['id']}).read()
try:opener.open(url+r['download'])
except __import__('urllib.error',fromlist=['HTTPError']).HTTPError as exc:assert exc.code==404
else:raise AssertionError('旧下载未撤销')
print(json.dumps({'word_download_neutral':True,'pdf_native_reverified':report['checks'],'private_absent':True,'business_present':True,'revoked_status':404}))
''', encoding='utf-8')
                    with (args.work / 'delivery-probe.log').open('wb') as log:
                        subprocess.run([receipt['python'], str(probe), str(Path(__file__).parent.resolve()), str(installed / 'scripts'), url], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
                    report['delivery_probe'] = json.loads((args.work / 'delivery-probe.log').read_text(encoding='utf-8').splitlines()[-1])
                    report['steps'].append('合成Word/PDF实际HTTP导出与独立副本复检')
                assert json.load(request(url, 'api/stop', {}))['stopped']
                child.wait(timeout=15)
                assert child.returncode == 0
                try:
                    opener.open(url, timeout=2)
                except (urllib.error.URLError, OSError):
                    pass
                else:
                    raise AssertionError('结束后服务仍可访问')
                report['steps'].append('生成入口启动/正常结束' if iteration == 0 else '原启动入口再次打开/正常结束')
            finally:
                if child.poll() is None:
                    try:
                        if info is None:
                            raise RuntimeError('启动尚未生成会话，停止本次子进程')
                        request(info['url'], 'api/stop', {}).read()
                        child.wait(timeout=5)
                    except Exception:
                        child.terminate()
                        child.wait(timeout=5)
                launch_log.close()
        report['ok'] = True
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        save()
    print(json.dumps({'ok': True, 'report': str(report_path), 'positive': acceptance['positive'], 'negative': acceptance['negative']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
