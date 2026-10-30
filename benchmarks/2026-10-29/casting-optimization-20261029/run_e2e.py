"""Reproduce the fresh-server paired validation (requires local Docker)."""
import argparse
import json
from pathlib import Path
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument('--pilot', action='store_true')
args = p.parse_args()
evidence = Path(__file__).resolve().parent
workspace = evidence.parent
venv = Path('/private/tmp/graflo-falkordb-20261028/.venv')
image = 'falkordb/falkordb@sha256:725b74d400124862c9e0f318c56bfb3c55b97cd7f301d9dfe8685980fb3c8195'
plan = [('pilot',0)] if args.pilot else [(v,b) for b in range(4) for v in (['base','candidate'] if b%2==0 else ['candidate','base'])]
for variant, block in plan:
    name = f'graflo-cast-e2e-{variant}-{block}-20261029'
    source = workspace/('cast-baseline' if variant in ['base','pilot'] else 'cast-optimization')
    server = ['docker','run','-d','--name',name,'--label','graflo.task=casting-optimization-20261029',
        '--network','none','--cpuset-cpus','0,1','--cpus','2','--memory','2g',
        '--entrypoint','redis-server',image,'--loadmodule','/var/lib/falkordb/bin/falkordb.so',
        'THREAD_COUNT','2','OMP_THREAD_COUNT','2','--save','','--appendonly','no']
    client = ['docker','run','--rm','--name',name+'-client','--label','graflo.task=casting-optimization-20261029',
        '--network','container:'+name,'--pid','container:'+name,'--cpuset-cpus','2','--cpus','1','--memory','3g',
        '--mount',f'type=bind,source={source},target=/repo,readonly',
        '--mount',f'type=bind,source={venv},target=/repo/.venv,readonly',
        '--mount',f'type=bind,source={workspace}/falkordb-etl-benchmarks-20261029,target=/scenario,readonly',
        '--mount',f'type=bind,source={evidence},target=/evidence',
        '-e','PYTHONDONTWRITEBYTECODE=1','-e','PYTHONPATH=/repo:/scenario',
        '-e',f'PYTHONHASHSEED={20261029+block}','graflo-falkordb-testenv:20261028','sh','-c',
        f'uv run --frozen --no-sync python /evidence/etl_verify.py --variant {variant} --trial {block} --documents {2000 if args.pilot else 100000} > /evidence/e2e-{variant}-{block}.log 2>&1']
    (evidence/f'e2e-commands-{variant}-{block}.json').write_text(json.dumps({'server':server,'client':client},indent=2)+'\n')
    subprocess.run(server,check=True)
    try:
        for _ in range(100):
            if subprocess.run(['docker','exec',name,'redis-cli','PING'],capture_output=True).stdout.strip()==b'PONG':break
            time.sleep(.1)
        else:raise RuntimeError('Server did not become ready')
        with (evidence/f'e2e-server-{variant}-{block}.json').open('w') as handle:
            subprocess.run(['docker','inspect',name],stdout=handle,check=True)
        subprocess.run(client,check=True)
        print((evidence/'e2e'/f'{variant}-{block}'/'result.json').read_text(),flush=True)
    finally:
        with (evidence/f'e2e-server-{variant}-{block}.log').open('w') as handle:
            subprocess.run(['docker','logs',name],stdout=handle,stderr=subprocess.STDOUT)
        subprocess.run(['docker','rm','-f',name],check=True)
