"""独立真实子进程验证：根退出、脱离进程组、无关进程隔离及停止写入。"""
from pathlib import Path
import sys,json,time,os
import psutil,pytest
R=Path(__file__).resolve().parent
sys.path.insert(0,str(R.parent/'scripts'))
import bounded_execution as b

WORKER='''import sys,os,time,json,subprocess
from pathlib import Path
import psutil
mode=sys.argv[1];r=Path(sys.argv[2]);kind=sys.argv[3]
p=psutil.Process();(r/(mode+'.json')).write_text(json.dumps({'pid':p.pid,'created_at':p.create_time(),'pgid':os.getpgrp()}))
if mode=='root':
 child=subprocess.Popen([sys.executable,__file__,'child',str(r),kind],start_new_session=(kind=='detached'), stdout=subprocess.DEVNULL if kind=='detached' else None, stderr=subprocess.DEVNULL if kind=='detached' else None)
 while not (r/'child.json').exists():time.sleep(.01)
 (r/'ready').touch()
 if kind=='root_exit':sys.exit(0)
for _ in range(1500):
 with (r/(mode+'.ticks')).open('a')as f:f.write('tick\\n')
 time.sleep(.02)
'''
def live(rec):
    try:
        p=psutil.Process(rec['pid'])
        return abs(p.create_time()-rec['created_at'])<.01 and p.is_running()and p.status()!=psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:return False

@pytest.mark.parametrize('kind',['first','late','root_exit','detached'])
def test_real_cleanup_and_unrelated_isolation(kind,monkeypatch,tmp_path):
    import subprocess
    worker=tmp_path/'worker.py';worker.write_text(WORKER)
    unrelated_dir=tmp_path/'unrelated';unrelated_dir.mkdir()
    unrelated=subprocess.Popen([sys.executable,str(worker),'unrelated',str(unrelated_dir),'unrelated'],start_new_session=True)
    records=[];before=time.monotonic();real_pids=b.psutil.pids
    def denied():
        if (tmp_path/'ready').exists()and(kind!='late'or time.monotonic()-before>1.2):
            raise SystemError('independent discovery failure after real child started')
        return real_pids()
    monkeypatch.setattr(b.psutil,'pids',denied)
    real_children=b.psutil.Process.children
    def denied_children(self,*args,**kwargs):
        if kind=='detached'and(tmp_path/'ready').exists():
            raise SystemError('child tree unavailable after detached task started')
        return real_children(self,*args,**kwargs)
    monkeypatch.setattr(b.psutil.Process,'children',denied_children)
    real_discover=b.launched_members
    def discover_after_ready(*args,**kwargs):
        if kind=='detached':
            limit=time.monotonic()+3
            while not(tmp_path/'ready').exists()and time.monotonic()<limit:time.sleep(.01)
        return real_discover(*args,**kwargs)
    monkeypatch.setattr(b,'launched_members',discover_after_ready)
    try:
        result=b.run_bounded([sys.executable,str(worker),'root',str(tmp_path),kind],cwd=tmp_path,receipt_dir=tmp_path/'receipts',operation='cleanup',timeout_seconds=10,interval_seconds=.1,rss_limit=1024**3,memory_metric='rss')
        records=[json.loads(p.read_text())for p in [tmp_path/'root.json',tmp_path/'child.json']]
        actual_alive=[r for r in records if live(r)]
        paths=[tmp_path/'root.ticks',tmp_path/'child.ticks'];sizes0=[p.stat().st_size if p.exists()else 0 for p in paths]
        u=unrelated_dir/'unrelated.ticks';u0=u.stat().st_size if u.exists()else 0;time.sleep(.25)
        sizes1=[p.stat().st_size if p.exists()else 0 for p in paths];u1=u.stat().st_size if u.exists()else 0
        evidence={'kind':kind,'actual_alive':actual_alive,'growth':[c-a for a,c in zip(sizes0,sizes1)],'unrelated_alive':unrelated.poll()is None,'unrelated_growth':u1-u0,'result':result}
        (tmp_path/'REAL_CLEANUP.json').write_text(json.dumps(evidence,indent=2))
        assert unrelated.poll()is None and u1>u0,'unrelated process was disturbed'
        if kind=='detached'and actual_alive:
            assert result['status']=='cleanup_unconfirmed'and not result['cleanup']['confirmed']and result['cleanup']['unverified'],'unseen detached owned child remains alive but cleanup is reported confirmed'
        else:
            assert not actual_alive,'actual owned process remained alive'
            assert sizes0==sizes1,'owned process continued writing after cleanup'
            assert result['cleanup']['confirmed']
    finally:
        for p in [tmp_path/'root.json',tmp_path/'child.json']:
            if p.exists():
                rec=json.loads(p.read_text())
                if live(rec):
                    target=psutil.Process(rec['pid']);target.kill()
                    try:target.wait(timeout=3)
                    except psutil.NoSuchProcess:pass
        if unrelated.poll()is None:unrelated.kill()
        unrelated.wait(timeout=3)
