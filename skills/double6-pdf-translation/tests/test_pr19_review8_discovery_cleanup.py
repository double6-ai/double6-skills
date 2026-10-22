"""所属树发现失败后，真实已启动子进程必须退出，不能只报告空列表。"""
from pathlib import Path
import sys,json,time,os
import psutil
R=Path(__file__).resolve().parent
sys.path.insert(0,str(R.parent/'scripts'))
import bounded_execution as b

def test_discovery_failure_does_not_leave_started_child_alive(monkeypatch,tmp_path):
    marker=tmp_path/'started.json'
    code='import os,time,json;from pathlib import Path;Path('+repr(str(marker))+').write_text(json.dumps({"pid":os.getpid()}));time.sleep(30)'
    real_pids=b.psutil.pids
    def denied():
        if marker.exists():raise SystemError('pid list unavailable after actual task started')
        return real_pids()
    monkeypatch.setattr(b.psutil,'pids',denied)
    started=time.monotonic();proc=None;alive=None
    try:
        result=b.run_bounded([sys.executable,'-c',code],cwd=tmp_path,receipt_dir=tmp_path/'receipts',operation='discovery',timeout_seconds=10,interval_seconds=0.1,rss_limit=1024**3,memory_metric='rss')
        assert marker.exists(),'probe task did not start'
        pid=json.loads(marker.read_text())['pid']
        try:proc=psutil.Process(pid);alive=proc.is_running()and proc.status()!=psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:alive=False
        (tmp_path/'DISCOVERY_CLEANUP.json').write_text(json.dumps({'elapsed':time.monotonic()-started,'actual_child_pid':pid,'actual_child_alive':alive,'result':result},indent=2))
        assert result['status']=='stopped',result
        assert not alive,'owned_tree_alive reported empty but launched task still running'
    finally:
        if alive and proc is not None:
            # 只回收上方marker绑定的本次测试子进程，避免测试本身遗留睡眠任务。
            proc.kill()
            try:proc.wait(timeout=3)
            except psutil.NoSuchProcess:pass
