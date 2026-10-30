"""Keep raw fusion-failure tracebacks separately from semantic equality checks."""

import argparse
import asyncio
import json
from pathlib import Path

from graflo import GraphManifest
from graflo.hq.document_caster import DocumentCaster
from graflo.hq.ingestion_parameters import IngestionParams
from cases import case


async def run():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    args=parser.parse_args()
    config,docs=case('flat',4)
    docs[1]['id']={'bad':1};docs[3]['id']={'bad':3}
    manifest=GraphManifest.from_config(config);manifest.finish_init()
    caster=DocumentCaster(manifest.require_ingestion_model())
    try:
        result=await caster.cast_batch(docs,'items',params=IngestionParams(cast_executor='inline'))
        assert [f.doc_index for f in result.failures]==[1,3]
        assert all(f.exception_type=='TypeError' and f.message=="unhashable type: 'dict'" for f in result.failures)
        assert [d['seq'] for d in result.graph.vertices['Item']]==['0','2']
        semantic=result.model_dump(mode='python')
        traces=[f.pop('traceback') for f in semantic['failures']]
        record={'semantic':semantic,'raw_tracebacks':traces}
        with Path(args.out).open('x') as handle:handle.write(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
        print(json.dumps({'failures':len(traces),'indices':[f.doc_index for f in result.failures]}))
    finally:caster.close()


if __name__=='__main__':asyncio.run(run())
