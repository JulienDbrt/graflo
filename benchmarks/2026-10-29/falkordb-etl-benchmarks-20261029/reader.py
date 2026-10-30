"""Paced readers in separate processes, with no GraFlo casting GIL contention."""

import argparse
import json
import time
from pathlib import Path

from falkordb import FalkorDB
from redis.backoff import NoBackoff
from redis.retry import Retry

from scenario import check_query,query_case

p=argparse.ArgumentParser()
p.add_argument('--graph',required=True)
p.add_argument('--worker',type=int,required=True)
p.add_argument('--documents',type=int,required=True)
p.add_argument('--directory',type=Path,required=True)
p.add_argument('--qps',type=float,default=25)
args=p.parse_args()
graph=FalkorDB(socket_timeout=10,socket_connect_timeout=5,retry=Retry(NoBackoff(),0)).select_graph(args.graph)
assert graph.query('RETURN 1').result_set==[[1]]
control=args.directory/'control.json'
status=args.directory/f'reader-{args.worker}-status.txt'
out=(args.directory/f'reader-{args.worker}.jsonl').open('w')
status.write_text('ready')
iteration=0
due=time.perf_counter()
previous=None
control_retries=0
while True:
    try:
        state=json.loads(control.read_text())
    except (FileNotFoundError,json.JSONDecodeError):
        # The host bind mount can briefly expose ENOENT during rename. This
        # retries control-plane I/O only, outside every query latency interval.
        control_retries+=1
        time.sleep(.001)
        continue
    phase=state['phase']
    if phase!=previous:
        status.write_text(phase)
        previous=phase
        due=time.perf_counter()+args.worker/(args.qps*4)
    if phase=='stop':break
    if phase in ['pause','ready']:
        time.sleep(.01)
        continue
    delay=due-time.perf_counter()
    if delay>0:time.sleep(delay)
    kind,i,query,params=query_case(args.worker,iteration,args.documents)
    started=time.perf_counter()
    row={'phase':phase,'worker':args.worker,'kind':kind,'started':started,'due':due}
    try:
        result=graph.query(query,params=params)
        row['passed']=check_query(kind,i,result.result_set,args.documents,phase)
        if not row['passed']:row['unexpected_result']=result.result_set[:10]
    except Exception as error:
        row.update(passed=False,error=repr(error))
    ended=time.perf_counter()
    row.update(ended=ended,latency_ms=(ended-started)*1000,schedule_lag_ms=max(0,started-due)*1000)
    out.write(json.dumps(row)+'\n');out.flush()
    iteration+=1
    due+=1/args.qps
    if ended-due>1/args.qps:
        # At most one outstanding query per worker; never hide inability to meet the target.
        due=ended
out.close()
(args.directory/f'reader-{args.worker}-control-retries.txt').write_text(str(control_retries))
