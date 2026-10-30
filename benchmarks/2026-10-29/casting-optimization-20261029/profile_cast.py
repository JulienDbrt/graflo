"""Profile one frozen workload; profiling results are not speed measurements."""

import argparse
import asyncio
import cProfile
import json
import pstats
import time
from pathlib import Path

from graflo import GraphManifest
from graflo.hq.document_caster import DocumentCaster
from graflo.hq.ingestion_parameters import IngestionParams
import graflo.hq.document_caster as casting_module
from scenario import manifest_config,source_record

p=argparse.ArgumentParser()
p.add_argument('--documents',type=int,default=10000)
p.add_argument('--executor',default='inline')
p.add_argument('--cores',type=int,default=1)
p.add_argument('--profile',action='store_true')
p.add_argument('--out',required=True)
args=p.parse_args()


async def run():
    manifest=GraphManifest.from_config(manifest_config());manifest.finish_init()
    caster=DocumentCaster(manifest.require_ingestion_model())
    params=IngestionParams(cast_executor=args.executor,n_cores=args.cores)
    docs=[source_record(i,1) for i in range(args.documents)]
    try:
        warm_start=time.perf_counter()
        warm=await caster.cast_batch(docs[:1000],'items',params=params)
        warm_seconds=time.perf_counter()-warm_start
        samples=[]
        cpu_samples=[]
        profiler=cProfile.Profile()
        chunk_profiles=[]
        original_chunk=casting_module._cast_chunk
        def profiled_chunk(*values,**kwargs):
            chunk_profiler=cProfile.Profile()
            try:return chunk_profiler.runcall(original_chunk,*values,**kwargs)
            finally:chunk_profiles.append(chunk_profiler)
        if args.profile:
            casting_module._cast_chunk=profiled_chunk
            profiler.enable()
        for _ in range(3):
            started=time.perf_counter()
            cpu_started=time.process_time()
            for offset in range(0,len(docs),1000):
                result=await caster.cast_batch(docs[offset:offset+1000],'items',params=params)
                assert len(result.graph.vertices['Item'])==len(docs[offset:offset+1000])
                assert len(result.graph.edges['Item','Category','IN_CATEGORY'])==len(docs[offset:offset+1000])
                assert not result.failures
            samples.append(time.perf_counter()-started)
            cpu_samples.append(time.process_time()-cpu_started)
        if args.profile:
            profiler.disable()
            casting_module._cast_chunk=original_chunk
            stats=pstats.Stats(profiler)
            for chunk_profiler in chunk_profiles:stats.add(chunk_profiler)
            stats.dump_stats(args.out+'.pstats')
            with Path(args.out+'.profile.txt').open('w') as handle:
                stats.stream=handle
                stats.strip_dirs().sort_stats('tottime').print_stats(55)
                stats.sort_stats('cumulative').print_stats(55)
        row={'documents':len(docs),'executor':args.executor,'cores':args.cores,
             'profiled':args.profile,'warm_start_seconds':warm_seconds,'seconds':samples,
             'process_cpu_seconds':cpu_samples}
        Path(args.out+'.json').write_text(json.dumps(row,indent=2)+'\n')
        print(json.dumps(row),flush=True)
    finally:caster.close()


if __name__=='__main__':asyncio.run(run())
