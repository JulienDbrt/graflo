"""Fresh-graph file ETL; kernel peaks and complete typed verification afterwards."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time

os.sched_setaffinity(0,{2})

from graflo import GraphManifest
from graflo.connections.onto import FalkordbConfig
from graflo.data_source.file import TableFileDataSource,JsonlFileDataSource
from graflo.data_source.registry import DataSourceRegistry
from graflo.db.manager import ConnectionManager
from graflo.hq import GraphEngine
from graflo.hq.ingestion_parameters import IngestionParams
import graflo.architecture.graph_types.merge as fusion
from scenario import manifest_config,expected_record

p=argparse.ArgumentParser();p.add_argument('--variant',required=True);p.add_argument('--trial',type=int,required=True)
p.add_argument('--documents',type=int,default=100000);args=p.parse_args()
directory=Path('/evidence/e2e')/f'{args.variant}-{args.trial}'
directory.mkdir(parents=True,exist_ok=False)
config=FalkordbConfig(uri='redis://localhost:6379',database='benchmark')
params=IngestionParams(batch_size=1000,n_cores=1,cast_executor='inline',batch_prefetch=2,
    max_in_flight_batches=1,max_concurrent_sources=1,max_concurrent_db_ops=1,max_doc_errors=0)


def stats(path):
    return {k:int(v) for k,v in (line.split() for line in Path(path).read_text().splitlines())}


def rss(pid):
    out={}
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        if line.startswith(('VmRSS:','VmHWM:')):
            key,value,*_=line.split();out[key.rstrip(':')]=int(value)*1024
    return out


def memory():
    return {'server':rss(1),'client':rss(os.getpid()),
            'server_cgroup_peak':int(Path('/proc/1/root/sys/fs/cgroup/memory.peak').read_text()),
            'client_cgroup_peak':int(Path('/sys/fs/cgroup/memory.peak').read_text())}


def scalar(value):
    return [type(value).__name__,struct.pack('!d',value).hex() if type(value)is float else value]


def emit(handle,digest,row):
    line=json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n'
    digest.update(line.encode());handle.write(line)


manifest=GraphManifest.from_config(manifest_config());manifest.finish_init()
engine=GraphEngine(target_db_flavor=config.connection_type)
engine.define_schema(manifest=manifest,target_db_config=config,recreate_schema=True,graph_target_namespace='benchmark')
with ConnectionManager(connection_config=config) as db:
    deadline=time.monotonic()+15
    while not(len(cs:=db.graph.list_constraints())==2 and all(c['status']=='OPERATIONAL' for c in cs)):
        if time.monotonic()>deadline:raise RuntimeError(cs)
        time.sleep(.01)

with tempfile.TemporaryDirectory(prefix='cast-input-') as temp:
    registry=DataSourceRegistry();files=[]
    for fmt,cls in [('csv',TableFileDataSource),('jsonl',JsonlFileDataSource)]:
        source=Path(f'/scenario/data-{args.documents}/initial.{fmt}')
        target=Path(temp)/source.name;shutil.copyfile(source,target)
        files.append({'format':fmt,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        registry.register(cls(path=target),'items')
    before=memory();server_cpu=stats('/proc/1/root/sys/fs/cgroup/cpu.stat')['usage_usec']
    started=time.perf_counter();cpu_started=time.process_time()
    engine.ingest(manifest=manifest,target_db_config=config,ingestion_params=params,
                  data_source_registry=registry,graph_target_namespace='benchmark')
    cpu_seconds=time.process_time()-cpu_started;seconds=time.perf_counter()-started
    server_cpu_seconds=(stats('/proc/1/root/sys/fs/cgroup/cpu.stat')['usage_usec']-server_cpu)/1e6
    after=memory()

nodes_digest=hashlib.sha256();edges_digest=hashlib.sha256()
with ConnectionManager(connection_config=config) as db:
    assert db.execute('MATCH (n) RETURN count(n)').result_set==[[args.documents+1000]]
    assert db.execute('MATCH ()-[r]->() RETURN count(r)').result_set==[[args.documents]]
    records=db.execute('MATCH (n:Item) RETURN n.seq,properties(n) ORDER BY n.seq').result_set
    assert len(records)==args.documents
    with gzip.open(directory/'nodes.jsonl.gz','wt',encoding='utf-8') as handle:
        fields=['seq','tenant','id','title','score','revision','payload','category']
        for i,(seq,props) in enumerate(records):
            expected=dict(zip(fields,expected_record(i,1)))
            assert scalar(seq)==scalar(i)
            assert set(props)==set(expected),(i,props)
            assert {k:scalar(v) for k,v in props.items()}=={k:scalar(v) for k,v in expected.items()},(i,props,expected)
            emit(handle,nodes_digest,['Item',i,[[k,scalar(v)] for k,v in props.items()]])
        del records
        categories=db.execute('MATCH (n:Category) RETURN properties(n) ORDER BY n.tenant,n.id').result_set
        assert len(categories)==1000
        assert {(r[0]['tenant'],r[0]['id']) for r in categories}=={(f'tenant{t}',str(c)) for t in range(10) for c in range(100)}
        for (props,) in categories:
            assert set(props)=={'tenant','id'} and all(type(v)is str for v in props.values())
            emit(handle,nodes_digest,['Category',[[k,scalar(v)] for k,v in props.items()]])
    edges=db.execute('MATCH (n:Item)-[r:IN_CATEGORY]->(g:Category) RETURN n.seq,properties(g),properties(r) ORDER BY n.seq').result_set
    assert len(edges)==args.documents
    with gzip.open(directory/'edges.jsonl.gz','wt',encoding='utf-8') as handle:
        for i,(seq,target,attributes) in enumerate(edges):
            assert scalar(seq)==scalar(i) and target=={'tenant':f'tenant{i%10}','id':str((i//10)%100)} and attributes=={}
            assert all(type(v)is str for v in target.values())
            emit(handle,edges_digest,[i,[[k,scalar(v)] for k,v in target.items()],attributes])
    constraints=db.graph.list_constraints()
    assert len(constraints)==2 and all(c['status']=='OPERATIONAL' for c in constraints)
    indexes=db.execute('CALL db.indexes() YIELD label,properties RETURN label,properties').result_set
    assert {r[0]:set(r[1]) for r in indexes}=={'Item':{'tenant','id','score','seq'},'Category':{'tenant','id'}}

result={'variant':args.variant,'trial':args.trial,'documents':args.documents,'seconds':seconds,
        'client_cpu_seconds':cpu_seconds,'server_cpu_seconds':server_cpu_seconds,'affinity':sorted(os.sched_getaffinity(0)),
        'source_file':fusion.__file__,'source_sha256':hashlib.sha256(Path(fusion.__file__).read_bytes()).hexdigest(),
        'memory_before_ingestion':before,'kernel_peaks_at_ingestion_end':after,'files':files,
        'typed_nodes_sha256':nodes_digest.hexdigest(),'typed_edges_sha256':edges_digest.hexdigest(),
        'items':args.documents,'categories':1000,'edges':args.documents,'constraints':constraints,'indexes':indexes,'passed':True}
(directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
