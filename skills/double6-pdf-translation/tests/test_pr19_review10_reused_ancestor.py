"""恢复发现的身份负例：旧成员PID被复用后，新进程的孩子不能继承旧归属。仅模拟查询，不发任何信号。"""
from pathlib import Path
import json,sys,os
R=Path(__file__).resolve().parent
sys.path.insert(0,str(R.parent/'scripts'))
import bounded_execution as b

def test_reused_known_parent_does_not_authorize_unrelated_child(monkeypatch,tmp_path):
    old_pid,child_pid=98765001,98765002
    class Fake:
        def __init__(self,pid):self.pid=pid
        def create_time(self):return 200.0 if self.pid==old_pid else 201.0
        def status(self):return b.psutil.STATUS_RUNNING
        def ppid(self):return 1 if self.pid==old_pid else old_pid
        def environ(self):return {} # 无本任务nonce
        def uids(self):return type('UID',(),{'real':os.getuid()})()
    monkeypatch.setattr(b,'_enumerate_all_pids',lambda:([old_pid,child_pid],'independent-fake',[{'ok':True}]))
    monkeypatch.setattr(b.psutil,'Process',Fake)
    identity={'pid':old_pid,'created_at':100.0,'process_group':old_pid}
    result=b._recovery_scan(identity,{old_pid:100.0},'original-task-nonce',False,'identity-negative')
    (tmp_path/'REUSED_ANCESTOR.json').write_text(json.dumps({'old_known_identity':identity,'current_parent_created_at':200.0,'child_created_at':201.0,'result':result},indent=2))
    assert not result['owned_found'],'reused parent PID incorrectly authorizes unrelated child as owned ancestry'
