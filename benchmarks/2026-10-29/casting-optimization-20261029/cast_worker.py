"""Persistent isolated interpreter: time casting, then check every typed field."""

import asyncio
from collections import defaultdict
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import struct
import sys
import time

# Pin before importing NumPy/pandas through GraFlo, and before creating the
# default executor. A shared {2,3} cpuset does not fix a thread to one CPU.
pin_cpu=os.environ.get('CAST_PIN_CPU')
if pin_cpu is not None:os.sched_setaffinity(0,{int(pin_cpu)})

from pydantic import BaseModel

from graflo import GraphManifest
from graflo.hq.document_caster import DocumentCaster
from graflo.hq.ingestion_parameters import IngestionParams
import graflo.architecture.graph_types.merge as fusion_module
from cases import case
from scenario import expected_record

logging.disable(logging.CRITICAL)
root=os.environ['CAST_SOURCE_ROOT']
assert Path(fusion_module.__file__).resolve()==Path(root+'/graflo/architecture/graph_types/merge.py').resolve()
source_hash=hashlib.sha256(Path(fusion_module.__file__).read_bytes()).hexdigest()
contexts={}


def typed(value,memo=None,diagnostic=False):
    if memo is None:memo={}
    name=type(value).__module__+'.'+type(value).__qualname__
    if isinstance(value,(BaseModel,dict,list)):
        if id(value) in memo:return ('ref',memo[id(value)])
        memo[id(value)]=len(memo)
    if isinstance(value,BaseModel):
        return ('model',name,tuple((field,typed(getattr(value,field),memo,field=='traceback')) for field in type(value).model_fields))
    if isinstance(value,dict):
        factory=None
        if isinstance(value,defaultdict):
            f=value.default_factory
            factory=None if f is None else f.__module__+'.'+f.__qualname__
        return ('mapping',name,factory,tuple((typed(k,memo),typed(v,memo)) for k,v in value.items()))
    if isinstance(value,(tuple,list)):return ('sequence',name,tuple(typed(v,memo) for v in value))
    if isinstance(value,float):return ('float',name,struct.pack('!d',value).hex())
    if isinstance(value,bytes):return ('bytes',name,value.hex())
    if isinstance(value,str):
        # These roots are the only accepted diagnostic difference between interpreters.
        return ('str',name,value.replace('/candidate/','<source>/').replace('/repo/','<source>/') if diagnostic else value)
    if value is None or isinstance(value,(int,bool)):return ('scalar',name,value)
    raise TypeError(f'Uncovered comparison type {name}')


def digest(value):
    return hashlib.sha256(json.dumps(typed(value),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


async def run_case(name,n,batch):
    assert hashlib.sha256(Path(fusion_module.__file__).read_bytes()).hexdigest()==source_hash,'source changed during campaign'
    key=(name,n,batch)
    if key not in contexts:
        config,docs=case(name,n)
        manifest=GraphManifest.from_config(config);manifest.finish_init()
        caster=DocumentCaster(manifest.require_ingestion_model())
        params=IngestionParams(cast_executor='inline',n_cores=1,batch_size=batch)
        before=digest(docs)
        start=time.perf_counter()
        await caster.cast_batch(docs[:batch],'items',params=params)
        contexts[key]=(caster,params,docs,before,time.perf_counter()-start)
    caster,params,docs,before,warm_seconds=contexts[key]
    gc.collect()
    output=[]
    start=time.perf_counter();cpu=time.process_time()
    for offset in range(0,n,batch):
        output.append(await caster.cast_batch(docs[offset:offset+batch],'items',params=params))
    cpu_seconds=time.process_time()-cpu;seconds=time.perf_counter()-start
    assert hashlib.sha256(Path(fusion_module.__file__).read_bytes()).hexdigest()==source_hash,'source changed during campaign'
    assert digest(docs)==before,'source input mutated'
    # Exact independent cardinality/error expectations in addition to paired digests.
    items=sum(len(r.graph.vertices.get('Item',[])) for r in output)
    edges=sum(sum(map(len,r.graph.edges.values())) for r in output)
    failures=sum(len(r.failures) for r in output)
    if name=='flat':assert (items,edges,failures)==(n,0,0),(items,edges,failures)
    elif name=='nested':assert (items,edges,failures)==(n,3*n,0),(items,edges,failures)
    elif name=='errors':
        bad={i for i in range(n) if i%20==0 or i%23==0}
        assert items==n-len(range(0,n,20)) and failures==len(bad),(items,failures,len(bad))
        for offset,result in zip(range(0,n,batch),output):
            assert [f.doc_index for f in result.failures]==[i-offset for i in range(offset,min(offset+batch,n)) if i in bad]
    else:assert (items,edges,failures)==(n,n,0),(items,edges,failures)
    if name in ['etl','transform_stress','errors']:
        seen=[]
        for result in output:
            for item in result.graph.vertices['Item']:
                i=item['seq'];expected=expected_record(i,1)
                if name=='errors' and i%23==0:expected[4]=None
                actual=[item.get(k) for k in ['seq','tenant','id','title','score','revision','payload','category']]
                assert typed(actual)==typed(expected),(name,i,actual,expected)
                assert name!='errors' or i%20!=0
                seen.append(i)
            for source,target,attributes in result.graph.edges['Item','Category','IN_CATEGORY']:
                i=int(source['id'])*10+int(source['tenant'].removeprefix('tenant'))
                assert source=={'tenant':f'tenant{i%10}','id':str(i//10)}
                assert target=={'tenant':f'tenant{i%10}','id':str((i//10)%100)}
                assert attributes=={}
        assert seen==[i for i in range(n) if name!='errors' or i%20!=0]
    return {'case':name,'documents':n,'batch_size':batch,'seconds':seconds,'cpu_seconds':cpu_seconds,
            'digest':digest(output),'input_digest':before,'items':items,'edges':edges,'failures':failures,
            'warmup_seconds':warm_seconds}


if __name__=='__main__':
    loop=asyncio.new_event_loop()
    print(json.dumps({'ready':True,'source':root,'loaded_module':fusion_module.__file__,
                      'fusion_sha256':hashlib.sha256(Path(fusion_module.__file__).read_bytes()).hexdigest(),
                      'gc_threshold':gc.get_threshold(),'affinity':sorted(os.sched_getaffinity(0))}),flush=True)
    try:
        for line in sys.stdin:
            request=json.loads(line)
            if request.get('stop'):break
            try:
                result=loop.run_until_complete(run_case(request['case'],request['documents'],request['batch_size']))
                print(json.dumps(result),flush=True)
            except BaseException as error:
                import traceback
                print(json.dumps({'error':repr(error),'traceback':traceback.format_exc()}),flush=True)
    finally:
        for caster,*_ in contexts.values():caster.close()
        loop.run_until_complete(loop.shutdown_default_executor());loop.close()
