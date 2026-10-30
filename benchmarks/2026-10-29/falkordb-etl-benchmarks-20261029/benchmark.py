"""File-backed GraFlo ETL, paced concurrent reads and real cgroup/RSS sampling."""

import argparse
import contextlib
import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from graflo import GraphManifest
from graflo.connections.onto import FalkordbConfig
from graflo.data_source.file import FileDataSource,JsonlFileDataSource,TableFileDataSource
from graflo.data_source.registry import DataSourceRegistry
from graflo.db.manager import ConnectionManager
from graflo.hq import GraphEngine
from graflo.hq.caster import Caster,IngestionParams
from graflo.hq.db_writer import DBWriter

from scenario import expected_record,manifest_config,query_case

logging.basicConfig(level=logging.WARNING,format='%(levelname)s %(name)s %(message)s')
p=argparse.ArgumentParser()
p.add_argument('--engine',required=True)
p.add_argument('--trial',type=int,default=1)
p.add_argument('--documents',type=int,default=100000)
p.add_argument('--readers',type=int,default=4)
p.add_argument('--idle-seconds',type=float,default=10)
args=p.parse_args()
ROOT=Path('/evidence')
directory=ROOT/f'{args.engine}-trial-{args.trial}'
directory.mkdir(exist_ok=True)
graph_name=f'graflobench_{args.engine.replace("-","_")}_{args.trial}'
config=FalkordbConfig(uri='redis://localhost:6379',database=graph_name)
params=IngestionParams(batch_size=1000,n_cores=1,cast_executor='inline',batch_prefetch=2,
    max_in_flight_batches=1,max_concurrent_sources=1,max_concurrent_db_ops=1,max_doc_errors=0)
phase='startup'
stats={}
readers=[]


def emit(kind,**fields):
    row={'kind':kind,'engine':args.engine,'trial':args.trial,'time':time.perf_counter(),**fields}
    with (directory/'events.jsonl').open('a') as handle:handle.write(json.dumps(row)+'\n')
    print(json.dumps(row),flush=True)


def metric(name,seconds,count=0):
    row=stats.setdefault(phase,{}).setdefault(name,{'seconds':0.,'calls':0,'records':0})
    row['seconds']+=seconds;row['calls']+=1;row['records']+=count


original_iter=FileDataSource.iter_batches
def timed_iter(self,*a,**kw):
    iterator=iter(original_iter(self,*a,**kw))
    while True:
        start=time.perf_counter()
        try:batch=next(iterator)
        except StopIteration:
            metric('source_read',time.perf_counter()-start)
            return
        metric('source_read',time.perf_counter()-start,len(batch))
        yield batch
FileDataSource.iter_batches=timed_iter
original_cast=Caster.cast_normal_resource
async def timed_cast(self,*a,**kw):
    start=time.perf_counter()
    try:return await original_cast(self,*a,**kw)
    finally:metric('cast',time.perf_counter()-start,len(a[0]))
Caster.cast_normal_resource=timed_cast
original_write=DBWriter.write
async def timed_write(self,*a,**kw):
    start=time.perf_counter()
    try:return await original_write(self,*a,**kw)
    finally:metric('write',time.perf_counter()-start)
DBWriter.write=timed_write


def read_integer(path):
    return int(Path(path).read_text().strip())


def memory_status(pid):
    values={}
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        if line.startswith(('VmRSS:','VmHWM:')):
            key,value,*_=line.split();values[key.rstrip(':')]=int(value)*1024
    return values


def cgstats(root):
    result={'memory_current':read_integer(root/'memory.current'),'memory_peak':read_integer(root/'memory.peak')}
    for line in (root/'cpu.stat').read_text().splitlines():
        key,value=line.split()
        if key in ['usage_usec','nr_throttled','throttled_usec']:result[key]=int(value)
    for line in (root/'memory.stat').read_text().splitlines():
        key,value=line.split()
        if key in ['anon','file']:result['memory_'+key]=int(value)
    return result


stop_monitor=threading.Event()
def monitor():
    with (directory/'memory.jsonl').open('w') as handle:
        while not stop_monitor.is_set():
            try:
                row={'time':time.perf_counter(),'phase':phase,'server_rss':memory_status(1),
                     'ingester_rss':memory_status(os.getpid()),
                     'server_cgroup':cgstats(Path('/proc/1/root/sys/fs/cgroup')),
                     'client_cgroup':cgstats(Path('/sys/fs/cgroup'))}
                handle.write(json.dumps(row)+'\n');handle.flush()
            except Exception as error:
                emit('monitor_error',error=repr(error));return
            stop_monitor.wait(.1)
thread=threading.Thread(target=monitor,daemon=True)
thread.start()


def control(state):
    temporary=directory/'control.tmp'
    temporary.write_text(json.dumps({'phase':state}))
    temporary.replace(directory/'control.json')


def wait_readers(state):
    deadline=time.monotonic()+40
    while any(not (directory/f'reader-{i}-status.txt').exists() or
              (directory/f'reader-{i}-status.txt').read_text()!=state for i in range(args.readers)):
        if any(r.poll() is not None for r in readers):raise RuntimeError('reader exited early')
        if time.monotonic()>deadline:raise RuntimeError(f'readers did not reach {state}')
        time.sleep(.02)


def run_ingest(name):
    global phase
    phase=name
    source_phase='initial' if name=='initial_ingest' else 'delta'
    registry=DataSourceRegistry()
    data=ROOT/f'data-{args.documents}'
    registry.register(TableFileDataSource(path=data/f'{source_phase}.csv'),'items')
    registry.register(JsonlFileDataSource(path=data/f'{source_phase}.jsonl'),'items')
    start=time.perf_counter()
    emit('phase_start',phase=name)
    engine.ingest(manifest=manifest,target_db_config=config,ingestion_params=params,
                  data_source_registry=registry,graph_target_namespace=graph_name)
    end=time.perf_counter()
    assert stats[name]['source_read']['records']==args.documents,stats[name]
    assert stats[name]['cast']['records']==args.documents,stats[name]
    emit('phase_finished',phase=name,seconds=end-start,documents=args.documents,
         documents_per_second=args.documents/(end-start),instrumentation=stats[name])
    return {'started':start,'ended':end,'seconds':end-start,'documents_per_second':args.documents/(end-start),
            'instrumentation':stats[name]}


def validate(final):
    global phase
    phase='validation_final' if final else 'validation_initial'
    total=args.documents+args.documents//2 if final else args.documents
    with ConnectionManager(connection_config=config) as db:
        assert db.execute('MATCH (n:Item) RETURN count(n)').result_set==[[total]]
        assert db.execute('MATCH (n:Category) RETURN count(n)').result_set==[[1000]]
        assert db.execute('MATCH ()-[r:IN_CATEGORY]->() RETURN count(r)').result_set==[[total]]
        actual=db.execute('MATCH (n:Item) RETURN n.seq,n.tenant,n.id,n.title,n.score,n.revision,n.payload,n.category ORDER BY n.seq').result_set
        assert len(actual)==total
        digest=hashlib.sha256()
        for i,row in enumerate(actual):
            revision=2 if final and i>=args.documents//2 else 1
            assert row==expected_record(i,revision),(i,row,expected_record(i,revision))
            # Both versions expose integers as either int or integral float: normalize only for the digest.
            canonical=[int(row[0]),row[1],row[2],row[3],float(row[4]),int(row[5]),row[6],row[7]]
            digest.update(json.dumps(canonical,ensure_ascii=False,separators=(',',':')).encode())
        del actual
        edges=db.execute('MATCH (n:Item)-[:IN_CATEGORY]->(g:Category) RETURN n.seq,g.tenant,g.id ORDER BY n.seq').result_set
        assert len(edges)==total
        for i,row in enumerate(edges):assert row==[i,f'tenant{i%10}',str((i//10)%100)],(i,row)
        constraints=db.graph.list_constraints()
        assert len(constraints)==2 and all(c['status']=='OPERATIONAL' for c in constraints),constraints
        indexes=db.execute('CALL db.indexes() YIELD label,properties,entitytype RETURN label,properties,entitytype').result_set
        emit('validated',phase=phase,items=total,categories=1000,edges=total,sha256=digest.hexdigest(),
             constraints=constraints,indexes=indexes)
        return {'items':total,'categories':1000,'edges':total,'sha256':digest.hexdigest(),
                'constraints':constraints,'indexes':indexes}


try:
    with ConnectionManager(connection_config=config) as db:
        db.graph.query('RETURN 1')
        emit('metadata',modules=db.client.connection.execute_command('MODULE','LIST'),
             server_config={k:db.client.connection.execute_command('GRAPH.CONFIG','GET',k)
                            for k in ['THREAD_COUNT','OMP_THREAD_COUNT','MAX_QUEUED_QUERIES','TIMEOUT','RESULTSET_SIZE']},
             ingestion_params=params.model_dump(mode='json'))
    manifest=GraphManifest.from_config(manifest_config());manifest.finish_init()
    engine=GraphEngine(target_db_flavor=config.connection_type)
    phase='schema'
    start=time.perf_counter()
    engine.define_schema(manifest=manifest,target_db_config=config,recreate_schema=True,graph_target_namespace=graph_name)
    with ConnectionManager(connection_config=config) as db:
        deadline=time.monotonic()+30
        while not (len(cs:=db.graph.list_constraints())==2 and all(c['status']=='OPERATIONAL' for c in cs)):
            if time.monotonic()>deadline:raise RuntimeError(f'constraints: {cs}')
            time.sleep(.02)
    emit('schema_ready',seconds=time.perf_counter()-start)
    first=run_ingest('initial_ingest')
    first_check=validate(False)
    control('ready')
    for i in range(args.readers):
        log=(directory/f'reader-{i}.log').open('w')
        readers.append(subprocess.Popen([sys.executable,str(ROOT/'reader.py'),'--graph',graph_name,
            '--worker',str(i),'--documents',str(args.documents),'--directory',str(directory)],stdout=log,stderr=subprocess.STDOUT))
        log.close()
    if readers:
        wait_readers('ready')
        phase='reader_warmup';control('warmup');time.sleep(2)
        control('pause');wait_readers('pause')
        phase='idle_reads';idle_start=time.perf_counter();control('idle')
        emit('phase_start',phase=phase)
        time.sleep(args.idle_seconds)
        control('pause');wait_readers('pause');idle_end=time.perf_counter()
        emit('phase_finished',phase=phase,seconds=idle_end-idle_start)
        control('mixed')
    else:idle_start=idle_end=None
    second=run_ingest('mixed_ingest')
    control('pause')
    if readers:wait_readers('pause')
    if readers:
        phase='post_reads';post_start=time.perf_counter();control('post_idle')
        emit('phase_start',phase=phase)
        time.sleep(args.idle_seconds)
        control('pause');wait_readers('pause');post_end=time.perf_counter()
        emit('phase_finished',phase=phase,seconds=post_end-post_start)
    else:post_start=post_end=None
    control('stop')
    for r in readers:assert r.wait(timeout=20)==0
    second_check=validate(True)
    phase='profiles'
    plans={}
    with ConnectionManager(connection_config=config) as db:
        for iteration in range(5):
            kind,_,query,values=query_case(0,iteration,args.documents)
            plans[kind]={'query':query,'params':values,'plan':db.graph.profile(query,params=values).plan}
    (directory/'profiles.json').write_text(json.dumps(plans,indent=2)+'\n')
    read_rows=[json.loads(line) for path in sorted(directory.glob('reader-*.jsonl')) for line in path.read_text().splitlines()]
    failures=[r for r in read_rows if not r['passed']]
    assert not failures,failures[:5]
    result={'engine':args.engine,'trial':args.trial,'documents_per_ingest':args.documents,
            'graph':graph_name,'initial':first,'mixed':second,'initial_validation':first_check,
            'final_validation':second_check,'idle_read_started':idle_start,'idle_read_ended':idle_end,
            'post_read_started':post_start,'post_read_ended':post_end,
            'reader_processes':args.readers,'target_read_queries_per_second':args.readers*25,
            'read_count':len(read_rows),'read_failures':len(failures),'passed':True}
    (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    emit('finished',passed=True,initial_seconds=first['seconds'],mixed_seconds=second['seconds'],read_queries=len(read_rows))
except BaseException as error:
    emit('failed',error=repr(error))
    raise
finally:
    control('stop')
    for r in readers:
        with contextlib.suppress(subprocess.TimeoutExpired):r.wait(timeout=12)
        if r.poll() is None:r.kill()
    stop_monitor.set();thread.join(timeout=5)
