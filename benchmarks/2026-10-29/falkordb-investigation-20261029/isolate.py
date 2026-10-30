"""Isolate large-batch behavior using the FalkorDB SDK, without GraFlo."""

import argparse
import json
import time
import uuid
from pathlib import Path

from falkordb import FalkorDB
from redis.backoff import NoBackoff
from redis.retry import Retry


p=argparse.ArgumentParser()
p.add_argument('--engine',default='rust')
p.add_argument('--phase',choices=['matrix','profiles','threshold','boundary','repeat','large','correctness'],default='matrix')
p.add_argument('--out',required=True)
args=p.parse_args()
out=Path(args.out).open('w')
client=FalkorDB(socket_timeout=120, socket_connect_timeout=5, retry=Retry(NoBackoff(),0))

CREATE='UNWIND $data AS row CREATE (n:Item) SET n = row'
MERGE='UNWIND $data AS row MERGE (n:Item {id: row.id}) ON MATCH SET n += row ON CREATE SET n += row'
MATCH='UNWIND $data AS row MATCH (n:Item {id: row.id}) SET n.payload = row.payload'


def emit(**r):
    r.update(engine=args.engine,phase=args.phase)
    out.write(json.dumps(r)+'\n');out.flush()
    print(json.dumps(r),flush=True)


def run(size,mode,operation,profile=False):
    name='graflo_isolate_'+uuid.uuid4().hex
    graph=client.select_graph(name)
    graph.query('RETURN 1')
    try:
        if mode!='none':
            graph.query('CREATE INDEX FOR (n:Item) ON (n.id)')
        if mode=='unique':
            graph.create_node_unique_constraint('Item','id')
            deadline=time.monotonic()+5
            while not all(c['status']=='OPERATIONAL' for c in graph.list_constraints()):
                if time.monotonic()>deadline:raise RuntimeError('constraint setup timeout')
                time.sleep(.01)
        docs=[{'id':str(i),'payload':'x'*100} for i in range(size)]
        if operation in ['merge_existing','match_update']:
            for offset in range(0,size,500):graph.query(CREATE,params={'data':docs[offset:offset+500]})
        if operation in ['merge_existing','match_update']:
            docs=[{'id':str(i),'payload':'y'*100} for i in range(size)]
        query=CREATE if operation=='create' else MATCH if operation=='match_update' else MERGE
        started=time.perf_counter()
        result=graph.profile(query,params={'data':docs}) if profile else graph.query(query,params={'data':docs})
        seconds=time.perf_counter()-started
        assert graph.query('MATCH (n:Item) RETURN count(n)').result_set==[[size]]
        expected='y'*100 if operation in ['merge_existing','match_update'] else 'x'*100
        assert graph.query('MATCH (n:Item) WHERE n.payload=$value RETURN count(n)',params={'value':expected}).result_set==[[size]]
        row={'size':size,'mode':mode,'operation':operation,'seconds':seconds}
        if profile: row['plan']=result.plan
        else: row.update(server_ms=result.run_time_ms,nodes_created=result.nodes_created,properties_set=result.properties_set)
        emit(**row)
    finally:
        graph.delete()


emit(kind='metadata',modules=client.connection.execute_command('MODULE','LIST'))
if args.phase=='matrix':
    for size in [1000,10000]:
        for mode in ['none','range','unique']:
            for operation in ['create','merge_new']:
                run(size,mode,operation)
        for mode in ['range','unique']:
            run(size,mode,'merge_existing')
        run(size,'range','match_update')
elif args.phase=='profiles':
    for size in [1000,10000]:
        for operation in ['create','merge_new','merge_existing','match_update']:
            run(size,'range',operation,profile=True)
elif args.phase=='boundary':
    for size in [1023,1024,1025,1100,1500,2048,2049]:
        run(size,'range','merge_new',profile=True)
elif args.phase=='repeat':
    for _ in range(3):
        run(10000,'range','merge_new')
elif args.phase=='large':
    for size in [25000,50000]:
        for _ in range(3):
            run(size,'range','merge_new')
elif args.phase=='correctness':
    # Exact upstream #3067 boundary reproducer, plus duplicates across batches.
    # Store actual results: stable 6.0.3 is expected to fail the boundary invariant.
    for size in [2,1025,3000]:
        graph=client.select_graph('graflo_boundary_'+uuid.uuid4().hex)
        try:
            query=('UNWIND range(1, $size) AS x WITH x WHERE x = 1 OR x = $size '
                   'MERGE (n:L {v: CASE x WHEN 1 THEN 1 ELSE 2 END}) ON CREATE SET n.v = 2')
            graph.query(query,params={'size':size})
            count=graph.query('MATCH (n:L) RETURN count(n)').result_set[0][0]
            emit(kind='boundary_correctness',size=size,nodes=count,expected=2,passed=count==2)
        finally:
            graph.delete()
    graph=client.select_graph('graflo_duplicates_'+uuid.uuid4().hex)
    try:
        graph.query('UNWIND range(1,3000) AS x MERGE (n:D {id:x % 7})')
        count=graph.query('MATCH (n:D) RETURN count(n)').result_set[0][0]
        emit(kind='duplicates_correctness',size=3000,nodes=count,expected=7,passed=count==7)
        assert count==7
    finally:
        graph.delete()
else:
    for size in [1000,1500,2000,2048,2500,3000,4000,4096,4097,5000,8192,8193,10000]:
        run(size,'range','merge_new')
emit(kind='finished')
out.close()
client.connection.close()
