"""Collect final regression evidence without substituting previous results."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

p=Path(__file__).resolve().parent
repo=p.parent/'falkordb-compat'
results={}
for label in ['unit','c','rust','offline']:
    log=(p/(label+'.log')).read_text()
    found=re.findall(r'(\d+) passed(?:, (\d+) skipped)?(?:, \d+ warning)? in ([\d.]+)s',log)
    assert found,(label,log[-1000:])
    passed,skipped,seconds=found[-1]
    results[label]={'passed':int(passed),'skipped':int(skipped or 0),'seconds':float(seconds)}
assert results['unit']['passed']==31
assert results['c']['passed']==results['rust']['passed']==194
assert results['offline']['passed']==5221
assert '6 failed, 25 deselected' in (p/'regression-before.log').read_text()
assert 'Failed' not in (p/'precommit.log').read_text()
sha=hashlib.sha256((repo/'graflo/db/falkordb/conn.py').read_bytes()).hexdigest()
audits=[json.loads(f.read_text()) for f in p.glob('*-source-*.json')]
assert len(audits)>=4 and all(a['sha256']==sha for a in audits)
summary={'review_head':'686ce68e81e15569e14d5fd1e2caa5c60d8a1b20',
 'fix_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
 'connector_sha256':sha,'results':results,'pre_commit':'all hooks passed',
 'red_regression':'Six expected failures on the reviewed implementation: each records one earlier write query before OverflowError.',
 'coverage':['later absent code group','later null code group','positive and negative overflow','no driver query on rejected batch','no stored relationship on either engine','both valid groups written','head excludes invalid tail','dry behaviour preserved'],
 'server_options':{'TIMEOUT':1000,'threads':2,'openmp_threads':2,'cpu_quota':2,'memory_bytes':2147483648,'persistence':'disabled'},
 'images':{'c':'falkordb/falkordb@sha256:725b74d400124862c9e0f318c56bfb3c55b97cd7f301d9dfe8685980fb3c8195','rust':'falkordb/falkordb@sha256:0fb85036662ce3d1206530a38fdf7df5a92b1fb31ad23087f8d4e89038ce0812'},
 'source_audits':audits,'scope':'Only PR400 connector preflight and regression tests changed; PR401 remains untouched and draft.'}
(p/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(results))
