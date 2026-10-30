"""Generated comparison with the frozen upstream implementation, including aliases."""

from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import argparse

from hypothesis import given,seed,settings,strategies as st
from pydantic import BaseModel
from graflo.architecture.graph_types import VertexRep

ROOT=Path('/evidence')


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.fuse_doc_basis


base=load('frozen_reference','/repo/graflo/architecture/graph_types/merge.py')
candidate=load('candidate_reference','/candidate/graflo/architecture/graph_types/merge.py')
counts=Counter()


def typed(value,memo=None):
    if memo is None:memo={}
    name=type(value).__module__+'.'+type(value).__qualname__
    if isinstance(value,(dict,list,BaseModel)):
        if id(value) in memo:return ('ref',memo[id(value)])
        memo[id(value)]=len(memo)
    if isinstance(value,BaseModel):return ('model',name,tuple((f,typed(getattr(value,f),memo)) for f in type(value).model_fields))
    if isinstance(value,dict):return ('dict',name,tuple((typed(k,memo),typed(v,memo)) for k,v in value.items()))
    if isinstance(value,(tuple,list)):return ('sequence',name,tuple(typed(v,memo) for v in value))
    if isinstance(value,float):return ('float',name,struct.pack('!d',value).hex())
    return ('scalar',name,value)


def snapshot(function,data,keys,union):
    result=None;error=None
    try:result=function(data,keys,union)
    except Exception as exc:error=(type(exc).__module__+'.'+type(exc).__qualname__,exc.args)
    # One traversal captures aliases between inputs and outputs, not only values.
    return typed({'input':data,'output':result,'error':error})


scalars=st.one_of(st.none(),st.booleans(),st.integers(),st.floats(),st.text(max_size=12))
values=st.recursive(scalars,lambda leaves:st.one_of(st.lists(leaves,max_size=4),st.dictionaries(st.sampled_from(['x','y']),leaves,max_size=2)),max_leaves=12)
document=st.dictionaries(st.sampled_from(['id','tenant','name','zones','payload']),values,max_size=5)


@seed(20261029)
@settings(max_examples=3000,deadline=None,database=None)
@given(docs=st.lists(document,max_size=10),
       keys=st.sampled_from([(),('id',),('tenant','id'),('id','id'),(0,),(None,)]),
       union=st.sampled_from([(),('zones',),('id','zones'),None]),
       mode=st.sampled_from(['dict','fragments','reps','mixed']))
def check(docs,keys,union,mode):
    if mode=='fragments':docs=[{'id':0,'tenant':False},{},{},*docs,{}]
    elif mode=='reps':docs=[VertexRep(vertex=d,lookup_only=i%2==0,find='by_id' if i%3==0 else None) for i,d in enumerate(docs)]
    elif mode=='mixed':docs=[{'id':1},{},VertexRep(vertex={'id':2}),*docs]
    left=snapshot(base,deepcopy(docs),keys,union)
    right=snapshot(candidate,deepcopy(docs),keys,union)
    counts[mode]+=1
    if left!=right:
        (ROOT/'differential-counterexample.txt').write_text(repr({'mode':mode,'docs':docs,'keys':keys,'union':union,'base':left,'candidate':right}))
    assert left==right


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    args=parser.parse_args()
    check()
    result={'generated_examples':sum(counts.values()),'modes':dict(counts),'divergences':0,
            'seed':20261029,'checks':['types','float bits','order','multiplicity','error type/args','input mutation','shared-reference topology'],
            'base_sha256':hashlib.sha256(Path('/repo/graflo/architecture/graph_types/merge.py').read_bytes()).hexdigest(),
            'candidate_sha256':hashlib.sha256(Path('/candidate/graflo/architecture/graph_types/merge.py').read_bytes()).hexdigest()}
    with Path(args.out).open('x') as handle:handle.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)
