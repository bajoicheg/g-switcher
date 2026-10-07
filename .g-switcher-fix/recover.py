import os,runpy,subprocess,json
from pathlib import Path
root=Path(os.environ['RUNNER_TEMP'])/'cdc-word-native-37642293763-1'
request=json.loads((root/'protocol/start.json').read_text())
assert request['attempt_id']=='word-native-37642293763-1-a1'
assert request['plan']['base_sha']=='e2159a7856ea12b4c6237820965263f5d6f92a4b'
assert request['repo_root']==os.environ['CDC_REPO_ROOT']
assert request['argv'][-1]==os.environ['CDC_WORKER_PATH']
real_run=subprocess.run
def diagnosed_run(*args,**kwargs):
    result=real_run(*args,**kwargs)
    argv=args[0] if args else kwargs.get('args',[])
    if result.returncode and isinstance(argv,list) and argv and argv[0]=='git':
        diagnostic=(str(result.stderr or '')+' '+str(result.stdout or '')).lower()
        needles=['authentication failed','could not read username','permission denied','not found','repository not found','non-fast-forward','remote rejected','cannot lock ref','failed to connect','could not resolve','502','503','504','rpc failed','timed out','refusing to allow','workflow','server error','too many','422']
        print(json.dumps({'event':'git_failure_classification','exit_code':result.returncode,'categories':[n for n in needles if n in diagnostic]}),flush=True)
    return result
subprocess.run=diagnosed_run
os.environ['GITHUB_RUN_ID']='37642293763'
os.environ['GITHUB_RUN_ATTEMPT']='1'
runpy.run_path('orchestration/.g-switcher-fix/runner.py',run_name='__main__')
