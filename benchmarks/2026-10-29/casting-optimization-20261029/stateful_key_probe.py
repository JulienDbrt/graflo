"""Custom dictionary keys may populate earlier empty fragments before merging."""
import argparse
import importlib.util
import json
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fuse_doc_basis


def observe(function):
    leading = {}

    class Key:
        def __hash__(self):
            return hash('id')

        def __eq__(self, other):
            leading['payload'] = 42
            return other == 'id'

    key = Key()
    result = function([leading, {key: 1}], ('id',))
    return {'payload': result[0].get('payload'), 'leading': leading,
            'rows': len(result)}


p = argparse.ArgumentParser()
p.add_argument('--out', required=True)
p.add_argument('--assert-equivalent', action='store_true')
args = p.parse_args()
result = {name: observe(load(name, root+'/graflo/architecture/graph_types/merge.py'))
          for name, root in [('base', '/repo'), ('candidate', '/candidate')]}
with Path(args.out).open('x') as handle:
    handle.write(json.dumps(result, indent=2)+'\n')
print(json.dumps(result))
if args.assert_equivalent:
    assert result['base'] == result['candidate']
