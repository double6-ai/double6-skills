"""真实macOS回放暴露的非所属进程可选遥测异常；不豁免任务自身资源计量。"""
from pathlib import Path
import sys
R=Path(__file__).resolve().parent
sys.path[:0]=[str(R.parent/'scripts')]
import bounded_execution as b

def test_unowned_process_permission_error_does_not_crash_snapshot(monkeypatch):
    def denied(*args,**kwargs):
        # macOS psutil process_iter(attrs=...)取name时的实际异常类别。
        raise SystemError('proc_cmdline returned a result with an exception set: KERN_PROCARGS2 permission denied')
        yield
    monkeypatch.setattr(b.psutil,'process_iter',denied)
    result=b.snapshot([])
    assert result['task_rss']>0 and result['process_count']>=1
    assert result['codex']==[]
