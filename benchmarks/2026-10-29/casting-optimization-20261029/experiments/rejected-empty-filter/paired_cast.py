"""AB/BA pairs across independent persistent, warmed source interpreters."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path('/evidence')
out=ROOT/'paired-cast.jsonl'
if out.exists():raise FileExistsError(out)
CASES=[('etl',5000,1000,12),('flat',5000,1000,12),('nested',2000,1000,12),
       ('errors',2000,1000,12),('transform_stress',5000,1000,12),
       ('etl',5000,100,8),('etl',10000,10000,8)]
workers={}


def ask(variant,request):
    worker=workers[variant]
    worker.stdin.write(json.dumps(request)+'\n');worker.stdin.flush()
    line=worker.stdout.readline()
    if not line:raise RuntimeError(f'{variant} exited {worker.poll()}')
    result=json.loads(line)
    if 'error' in result:raise RuntimeError(json.dumps(result))
    return result


try:
    for variant,root in [('base','/repo'),('candidate','/candidate')]:
        env={**os.environ,'PYTHONPATH':root+':/evidence:/scenario','CAST_SOURCE_ROOT':root}
        workers[variant]=subprocess.Popen([sys.executable,'/evidence/cast_worker.py'],env=env,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(ROOT/(variant+'-worker.log')).open('w'),text=True,bufsize=1)
        print(variant,workers[variant].stdout.readline().strip(),flush=True)
    with out.open('x') as handle:
        for block in range(12):
            cases=CASES[block%len(CASES):]+CASES[:block%len(CASES)]
            for name,n,batch,repetitions in cases:
                if block>=repetitions:continue
                request={'case':name,'documents':n,'batch_size':batch}
                order=['base','candidate'] if block%2==0 else ['candidate','base']
                pair={}
                for position,variant in enumerate(order):
                    row=ask(variant,request)
                    row.update(block=block,variant=variant,position=position,recorded_at=time.time())
                    handle.write(json.dumps(row)+'\n');handle.flush();pair[variant]=row
                for field in ['digest','input_digest','items','edges','failures']:
                    assert pair['base'][field]==pair['candidate'][field],(name,batch,block,field,pair)
                print(json.dumps({'block':block,'case':name,'batch':batch,'cpu_speedup':pair['base']['cpu_seconds']/pair['candidate']['cpu_seconds'],
                                  'wall_speedup':pair['base']['seconds']/pair['candidate']['seconds'],'exact':True}),flush=True)
    (ROOT/'paired-cast-finished.txt').write_text('All typed output and input digests agree.\n')
finally:
    for worker in workers.values():
        if worker.poll() is None:
            worker.stdin.write('{"stop":true}\n');worker.stdin.flush()
            try:worker.wait(timeout=15)
            except subprocess.TimeoutExpired:worker.kill()
