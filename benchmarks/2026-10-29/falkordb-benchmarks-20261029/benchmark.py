"""Repeatable connector benchmarks on isolated C or Rust FalkorDB instances.

Each sample owns a fresh graph. Setup and correctness checks are excluded from
latencies. Run one engine at a time with identical Docker CPU/memory settings.
"""

import argparse
import contextlib
import datetime
import importlib.metadata
import json
import platform
import statistics
import time
import uuid
from pathlib import Path

from falkordb import FalkorDB
from redis.backoff import NoBackoff
from redis.retry import Retry

from graflo.architecture.schema import Schema
from graflo.connections.onto import FalkordbConfig
from graflo.db.falkordb.conn import FalkordbConnection


parser = argparse.ArgumentParser()
parser.add_argument('--engine', required=True, choices=['c', 'rust'])
parser.add_argument('--phase', required=True, choices=['realistic', 'parse'])
parser.add_argument('--out', required=True)
args = parser.parse_args()
output = Path(args.out).open('w')


def emit(**row):
    row.update(engine=args.engine, phase=args.phase)
    output.write(json.dumps(row) + '\n')
    output.flush()
    print(json.dumps({k:v for k,v in row.items() if k!='latencies_ms'}), flush=True)


@contextlib.contextmanager
def fresh_db():
    name = 'graflo_bench_' + args.engine + '_' + uuid.uuid4().hex
    db = FalkordbConnection(FalkordbConfig(uri='redis://localhost:6379', database=name))
    # A read timeout bounds diagnostics without retrying or replaying a write.
    db.client.connection.close()
    client = FalkorDB(socket_timeout=180, socket_connect_timeout=5, retry=Retry(NoBackoff(), 0))
    db.client = client
    db.graph = client.select_graph(name)
    db.execute('RETURN 1')
    try:
        yield db
    finally:
        try:
            db.delete_database(name)
        finally:
            client.connection.close()
            db.close()


def define_schema(db):
    schema = Schema.model_validate({
        'metadata': {'name': 'benchmark'},
        'core_schema': {
            'vertex_config': {'vertices': [{
                'name': 'Item', 'properties': ['id','payload','category','value'],
                'identity': ['id'],
            }]},
            'edge_config': {'edges': []},
        },
        'db_profile': {'db_flavor': 'falkordb', 'vertex_indexes': {'Item': [{'fields': ['category']}]}},
    })
    db.define_indexes(schema)
    deadline = time.monotonic()+5
    while True:
        constraints = db.graph.list_constraints()
        if constraints and all(c['status']=='OPERATIONAL' for c in constraints):
            return
        if time.monotonic()>=deadline or any(c['status']=='FAILED' for c in constraints):
            raise RuntimeError(f'Constraint setup failed: {constraints}')
        time.sleep(0.01)


def summary(latencies):
    ordered = sorted(latencies)
    def percentile(p):
        pos=(len(ordered)-1)*p
        lo=int(pos)
        hi=min(lo+1,len(ordered)-1)
        return ordered[lo]+(ordered[hi]-ordered[lo])*(pos-lo)
    return {
        'latencies_ms': latencies,
        'latency_mean_ms': statistics.mean(latencies),
        'latency_p50_ms': percentile(.5),
        'latency_p95_ms': percentile(.95),
        'latency_p99_ms': percentile(.99),
    }


def operations(db, kind, operation, verify, indexed, repeat, count=200):
    for i in range(20):
        verify(operation(i), i)
    latencies=[]
    start_all=time.perf_counter()
    for i in range(count):
        start=time.perf_counter()
        result=operation(i)
        latencies.append((time.perf_counter()-start)*1000)
        verify(result,i)
    elapsed=time.perf_counter()-start_all
    emit(kind=kind, indexed=indexed, repeat=repeat, operations=count,
         seconds=elapsed, operations_per_second=count/elapsed, **summary(latencies))


with fresh_db() as db:
    configs={name:db.client.connection.execute_command('GRAPH.CONFIG','GET',name) for name in [
        'THREAD_COUNT','OMP_THREAD_COUNT','MAX_QUEUED_QUERIES','TIMEOUT','TIMEOUT_DEFAULT',
        'TIMEOUT_MAX','RESULTSET_SIZE',
    ]}
    emit(kind='metadata', started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
         python=platform.python_version(), machine=platform.machine(),
         packages={name:importlib.metadata.version(name) for name in ['falkordb','redis']},
         server=db.client.connection.info('server')['redis_version'], config=configs)


if args.phase=='realistic':
    size=10000
    for indexed in [False,True]:
        for batch_size in [1,100,1000,10000]:
            for repeat in range(3):
                with fresh_db() as db:
                    if indexed:
                        define_schema(db)
                    docs=[{'id':str(i),'payload':'x'*100} for i in range(size)]
                    latencies=[]
                    start_all=time.perf_counter()
                    for start in range(0,size,batch_size):
                        batch=docs[start:start+batch_size]
                        start_one=time.perf_counter()
                        db.upsert_docs_batch(batch,'Item',['id'])
                        latencies.append((time.perf_counter()-start_one)*1000)
                    elapsed=time.perf_counter()-start_all
                    assert db.execute('MATCH (n:Item) RETURN count(n)').result_set==[[size]]
                    emit(kind='ingest', indexed=indexed, batch_size=batch_size, repeat=repeat,
                         documents=size, seconds=elapsed, documents_per_second=size/elapsed,
                         **summary(latencies))
        for repeat in range(3):
            with fresh_db() as db:
                if indexed:
                    define_schema(db)
                docs=[{'id':str(i),'payload':'x'*100,'category':f'c{i%10}','value':i} for i in range(size)]
                start=time.perf_counter()
                for offset in range(0,size,500):
                    db.upsert_docs_batch(docs[offset:offset+500],'Item',['id'])
                emit(kind='setup', indexed=indexed, repeat=repeat, documents=size,
                     seconds=time.perf_counter()-start)
                def lookup(i):
                    return db.fetch_docs('Item',filters=['==',str((i*37)%size),'id'],limit=1)
                def verify_lookup(rows,i):
                    assert len(rows)==1 and rows[0]['id']==str((i*37)%size)
                operations(db,'point_lookup',lookup,verify_lookup,indexed,repeat)
                def update(i):
                    db.upsert_docs_batch([{'id':str((i*37)%size),'value':-i}], 'Item',['id'])
                operations(db,'point_update',update,lambda value,i:None,indexed,repeat)
                assert db.fetch_docs('Item',filters=['==',str((199*37)%size),'id'])[0]['value']==-199
                def count_category(i):
                    return db.execute('MATCH (n:Item) WHERE n.category=$category RETURN count(n)',category=f'c{i%10}').result_set
                def verify_count(rows,i):
                    assert rows==[[size//10]]
                operations(db,'category_count',count_category,verify_count,indexed,repeat)
else:
    for size in [1000,5000,10000,25000,50000]:
        for repeat in range(3 if size<=10000 else 1):
            with fresh_db() as db:
                docs=[{'id':str(i),'payload':'x'*100} for i in range(size)]
                start=time.perf_counter()
                header=db.graph._build_params_header({'data':docs})
                formatting=time.perf_counter()-start
                payload_bytes=len(header.encode())
                start=time.perf_counter()
                result=db.execute('RETURN size($data)',data=docs)
                elapsed=time.perf_counter()-start
                assert result.result_set==[[size]]
                emit(kind='parameter_only', documents=size, repeat=repeat, seconds=elapsed,
                     server_reported_ms=result.run_time_ms, formatting_seconds=formatting,
                     payload_bytes=payload_bytes)
                start=time.perf_counter()
                result=db.execute('RETURN size(range(0, $last))',last=size-1)
                elapsed=time.perf_counter()-start
                assert result.result_set==[[size]]
                emit(kind='generated_range', documents=size, repeat=repeat, seconds=elapsed,
                     server_reported_ms=result.run_time_ms)

emit(kind='finished', finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
output.close()
