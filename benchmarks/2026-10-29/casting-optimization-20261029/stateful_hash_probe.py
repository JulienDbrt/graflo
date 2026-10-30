"""Adversarial identity callbacks can mutate the input while it is fused."""

import importlib.util
import json
import argparse
from pathlib import Path


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.fuse_doc_basis


def run(function):
    docs=[]
    class Identity:
        calls=0
        def __hash__(self):
            self.calls+=1
            if self.calls==1:docs.append(None)
            return 7
    identity=Identity();docs.append({'id':identity})
    try:
        function(docs,('id',))
        return {'outcome':'returned','hash_calls':identity.calls,'input_length':len(docs)}
    except Exception as error:
        return {'outcome':'raised','error_type':type(error).__name__,'message':str(error),
                'hash_calls':identity.calls,'input_length':len(docs)}


rows={v:run(load(v,path)) for v,path in [
    ('base','/repo/graflo/architecture/graph_types/merge.py'),
    ('candidate','/candidate/graflo/architecture/graph_types/merge.py')]}
print(json.dumps(rows),flush=True)
parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--assert-equivalent',action='store_true')
args=parser.parse_args()
with Path(args.out).open('x') as handle:handle.write(json.dumps(rows,indent=2)+'\n')
if args.assert_equivalent:assert rows['base']==rows['candidate']
