"""Paired AB/BA fusion timings in one process, with CPU time and raw samples."""

import importlib.util
import json
import statistics
import time
from pathlib import Path

from graflo.architecture.graph_types import VertexRep


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.fuse_doc_basis


functions={
    'base':load('frozen_fusion','/repo/graflo/architecture/graph_types/merge.py'),
    'candidate':load('candidate_fusion','/candidate/graflo/architecture/graph_types/merge.py'),
}
item={'id':'a','tenant':'t','seq':1,'title':'Élément · 東京','score':1.25,'revision':1,'payload':'x'*100,'category':'c'}
cases={
    'singleton_dict':[dict(item)],
    'singleton_rep':[VertexRep(vertex=dict(item))],
    'six_empty_fragments':[dict(item),{},{},{},{},{},{}],
    'all_empty':[{},{}],
    'two_keyed':[dict(item),{**item,'id':'b'}],
    '64_keyed':[{**item,'id':str(i)} for i in range(64)],
    '64_reps':[VertexRep(vertex={**item,'id':str(i)}) for i in range(64)],
}
rows=[]
for name,docs in cases.items():
    for function in functions.values():
        for _ in range(500):function(docs,('tenant','id'))
    loops=3000 if len(docs)<10 else 200
    for block in range(12):
        order=['base','candidate'] if block%2==0 else ['candidate','base']
        for variant in order:
            cpu=time.process_time();wall=time.perf_counter()
            for _ in range(loops):functions[variant](docs,('tenant','id'))
            rows.append({'case':name,'block':block,'variant':variant,'calls':loops,
                         'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu})
root=Path('/evidence')
(root/'micro-fusion.json').write_text(json.dumps(rows,indent=2)+'\n')
for name in cases:
    ratios=[]
    for block in range(12):
        samples={r['variant']:r for r in rows if r['case']==name and r['block']==block}
        ratios.append(samples['base']['cpu_seconds']/samples['candidate']['cpu_seconds'])
    print(name,'paired CPU speedup',round(statistics.median(ratios),3),'range',round(min(ratios),3),round(max(ratios),3),flush=True)
