"""rc.8 OCR 路线的真实进程计量与回收（真实 tesseract，绝不 mock；引擎不在时 skip）。

正例：OCR 重建作为 run_bounded 的有界任务运行，tesseract 子进程出现在资源采样（owned tree）中、
       其 PID + create_time 都在 observed_owned_identities 里，任务结束后全部真实死亡；无关进程存活。
负例：任务时限 / 任务内存上限在 tesseract 运行中触发 → 整棵树被回收：tesseract 按 PID + create_time 核实死亡，
       OCR 工作目录停止写入，回执写明 stop_reason；同用户的无关进程不受影响；未核实的不报告为已确认。"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bounded_execution as be  # noqa: E402
import ocr_route  # noqa: E402
import resource_limits as rl  # noqa: E402
from test_ocr_route import scanned_pdf  # noqa: E402

pytestmark = [pytest.mark.skipif(os.name != 'posix', reason='process-tree reclaim is POSIX only'),
              pytest.mark.skipif(not (shutil.which('tesseract') and ocr_route.engine_info().get('available')),
                                 reason='tesseract + chi_sim/eng/osd not installed (OCR route optional)')]


def _alive(pid, created_at):
    try:
        p = psutil.Process(pid)
        if abs(p.create_time() - created_at) > 0.01 or p.status() == psutil.STATUS_ZOMBIE:
            return False
    except psutil.NoSuchProcess:
        return False
    return True


def _multi_page_scan(tmp_path, pages=4):
    import pymupdf
    one = scanned_pdf(tmp_path / 'one.pdf')
    out = pymupdf.open()
    for _ in range(pages):
        out.insert_pdf(pymupdf.open(one))
    path = tmp_path / 'scan-multi.pdf'
    out.save(path)
    return path


def _unrelated(tmp_path):
    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], start_new_session=True)
    return proc, psutil.Process(proc.pid).create_time()


def _tesseract_rows(monitor_path):
    rows = [json.loads(line) for line in monitor_path.read_text().splitlines() if line.strip()]
    return [p for r in rows for p in r.get('processes', []) if p.get('name') == 'tesseract']


def _ocr_argv(pdf, workdir):
    return [sys.executable, str(SKILL / 'scripts' / 'ocr_route.py'), '--input', str(pdf), '--workdir', str(workdir),
            '--target-language', 'zh']


def test_ocr_children_are_metered_and_reclaimed(tmp_path):
    pdf = scanned_pdf(tmp_path / 'scan.pdf')
    unrelated, unrelated_ct = _unrelated(tmp_path)
    try:
        result = be.run_bounded(_ocr_argv(pdf, tmp_path / 'w'), cwd=tmp_path, receipt_dir=tmp_path / 'r',
                                operation='ocr-reconstruct', timeout_seconds=120, interval_seconds=0.05,
                                rss_limit=rl.RSS_TASK_LIMIT_BYTES, max_processes=8,
                                max_total_fraction=rl.EXPLICIT_TOTAL_FRACTION)  # 冻结合同按 50% 主机授权执行（同工作流）
        assert result['status'] == 'succeeded', result
        manifest = json.loads((tmp_path / 'w' / 'OCR_MANIFEST.json').read_text())
        assert manifest['status'] == 'ok'
        engines = manifest['processes']
        assert engines and all(p['pid'] and p['created_at'] for p in engines)
        # 资源采样里出现 tesseract（被计入任务内存），且其身份属于本任务 owned tree
        assert _tesseract_rows(Path(result['resource_receipt']))
        observed = {(i['pid'], round(i['created_at'], 2)) for i in result['observed_owned_identities']}
        seen = [p for p in engines if (p['pid'], round(p['created_at'], 2)) in observed]
        assert seen, 'no tesseract identity was observed inside the owned tree'
        # 结束后：所有 tesseract 与任务根进程真实死亡；回收结论为 confirmed
        assert not any(_alive(p['pid'], p['created_at']) for p in engines)
        assert result['cleanup']['status'] == 'confirmed'
        assert _alive(unrelated.pid, unrelated_ct)
    finally:
        unrelated.kill()


@pytest.mark.parametrize('limit', ['timeout', 'memory'])
def test_ocr_children_are_reclaimed_when_the_task_limit_trips(tmp_path, limit):
    pdf = _multi_page_scan(tmp_path, pages=5)
    unrelated, unrelated_ct = _unrelated(tmp_path)
    workdir = tmp_path / 'w'
    try:
        kwargs = dict(timeout_seconds=120, rss_limit=rl.RSS_TASK_LIMIT_BYTES, max_total_fraction=rl.EXPLICIT_TOTAL_FRACTION)
        if limit == 'timeout':
            kwargs['timeout_seconds'] = 6           # 5 页 OCR 需要远超 6 s
        else:
            # 任务树包含调用方（本测试进程）。实测 ocr_route 进程渲染后约 150 MiB、tesseract 约 120 MiB：
            # 调用方 + 200 MiB 在 ocr_route 单独运行时不越限，第一次 tesseract 运行时越限。
            kwargs['rss_limit'] = psutil.Process().memory_info().rss + 200 * 1024 ** 2
        result = be.run_bounded(_ocr_argv(pdf, workdir), cwd=tmp_path, receipt_dir=tmp_path / 'r',
                                operation='ocr-reconstruct', interval_seconds=0.05, max_processes=8, **kwargs)
        assert result['status'] == 'stopped', result
        assert result['stop_reason'] == ('task_timeout' if limit == 'timeout' else 'task_memory_limit'), result['stop_reason']
        identities = result['observed_owned_identities']
        assert identities
        verified = {(d['pid'], d['created_at']) for d in result['cleanup'].get('verified_dead', [])}
        for ident in identities:                    # 每个观测到的 owned 进程（含 tesseract）都真实死亡
            assert not _alive(ident['pid'], ident['created_at'])
        assert result['cleanup']['status'] == 'confirmed'
        assert verified, 'cleanup must list verified-dead identities'
        assert _tesseract_rows(Path(result['resource_receipt'])), 'tesseract must have been metered before the stop'
        if limit == 'memory':  # 越限的那次采样里就有 tesseract：它的内存被计入并触发了停止
            rows = [json.loads(l) for l in Path(result['resource_receipt']).read_text().splitlines() if l.strip()]
            over = [r for r in rows if r.get('task_rss', 0) > kwargs['rss_limit']]
            assert over and any(p.get('name') == 'tesseract' for p in over[0]['processes']), over[:1]
        # 停止写入
        sizes = sum(p.stat().st_size for p in workdir.rglob('*') if p.is_file()) if workdir.exists() else 0
        time.sleep(0.5)
        later = sum(p.stat().st_size for p in workdir.rglob('*') if p.is_file()) if workdir.exists() else 0
        assert later == sizes
        # 被截断的重建不产生 OK 清单
        manifest = workdir / 'OCR_MANIFEST.json'
        assert not manifest.exists() or json.loads(manifest.read_text())['status'] != 'ok'
        assert _alive(unrelated.pid, unrelated_ct)
    finally:
        unrelated.kill()


def test_engine_timeout_inside_ocr_kills_the_tesseract_child(tmp_path):
    pdf = _multi_page_scan(tmp_path, pages=1)
    import pymupdf
    png = tmp_path / 'big.png'
    pymupdf.open(pdf)[0].get_pixmap(dpi=600).save(png)
    log = []
    with pytest.raises(ocr_route.EngineError):
        ocr_route.run_tesseract([shutil.which('tesseract'), str(png), 'stdout', '-l', 'eng', '--psm', '3'],
                                log=log, purpose='test', timeout=0.3)
    row = log[-1]
    assert row['timed_out'] is True and row['pid'] and row['created_at']
    assert not _alive(row['pid'], row['created_at'])
