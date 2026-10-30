"""Persistent isolated interpreter: time casting, then check every typed field."""

import asyncio
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import struct
import sys
import time

from pydantic import BaseModel

from graflo import GraphManifest
from graflo.hq.document_caster import DocumentCaster
from graflo.hq.ingestion_parameters import IngestionParams
from cases import case

logging.disable(logging.CRITICAL)
root=os.environ['CAST_SOURCE_ROOT']
contexts={}


def typed(value):
    name=type(value).__module__+'.'+type(value).__qualname__
    if isinstance(value,BaseModel):return ('model',name,typed(value.model_dump(mode='python')))
    if isinstance(value,dict):return ('mapping',name,tuple((typed(k),typed(v)) for k,v in value.items()))
    if isinstance(value,(tuple,list)):return ('sequence',name,tuple(typed(v) for v in value))
    if isinstance(value,float):return ('float',name,struct.pack('!d',value).hex())
    if isinstance(value,bytes):return ('bytes',name,value.hex())
    if isinstance(value,str):
        # These roots are the only accepted diagnostic difference between interpreters.
        return ('str',name,value.replace('/candidate/','<source>/').replace('/repo/','<source>/'))
    if value is None or isinstance(value,(int,bool)):return ('scalar',name,value)
    raise TypeError(f'Uncovered comparison type {name}')


def digest(value):
    return hashlib.sha256(json.dumps(typed(value),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


async def run_case(name,n,batch):
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
    assert digest(docs)==before,'source input mutated'
    # Exact independent cardinality/error expectations in addition to paired digests.
    items=sum(len(r.graph.vertices.get('Item',[])) for r in output)
    edges=sum(sum(map(len,r.graph.edges.values())) for r in output)
    failures=sum(len(r.failures) for r in output)
    if name=='flat':assert (items,edges,failures)==(n,0,0),(items,edges,failures)
    elif name=='nested':assert (items,edges,failures)==(n,3*n,0),(items,edges,failures)
    elif name=='errors':
        assert items==n-len(range(0,n,20)) and failures>0,(items,failures)
    else:assert (items,edges,failures)==(n,n,0),(items,edges,failures)
    return {'case':name,'documents':n,'batch_size':batch,'seconds':seconds,'cpu_seconds':cpu_seconds,
            'digest':digest(output),'input_digest':before,'items':items,'edges':edges,'failures':failures,
            'warmup_seconds':warm_seconds}


if __name__=='__main__':
    loop=asyncio.new_event_loop()
    print(json.dumps({'ready':True,'source':root,'fusion_sha256':hashlib.sha256((Path(root)/'graflo/architecture/graph_types/merge.py').read_bytes()).hexdigest()}),flush=True)
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
