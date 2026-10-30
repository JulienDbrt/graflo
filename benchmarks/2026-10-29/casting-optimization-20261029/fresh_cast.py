"""Confirmation with independent processes as the unit of each AB/BA pair."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path('/evidence')
label = 'confirmation-fresh-cpu2'
out = root/('paired-cast-'+label+'.jsonl')
assert not out.exists()
with out.open('x') as handle:
    for block in range(12):
        workers = {}
        logs = []
        order = ['base', 'candidate'] if block % 2 == 0 else ['candidate', 'base']
        try:
            for variant in order:
                source = '/repo' if variant == 'base' else '/candidate'
                env = {**os.environ, 'PYTHONPATH': source+':/evidence:/scenario',
                       'CAST_SOURCE_ROOT': source, 'CAST_PIN_CPU': '2',
                       'PYTHONHASHSEED': str(20261029+block)}
                log = (root/f'{variant}-worker-{label}-{block}.log').open('x')
                logs.append(log)
                worker = subprocess.Popen([sys.executable, '/evidence/cast_worker.py'],
                    env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=log, text=True, bufsize=1)
                workers[variant] = worker
                ready = json.loads(worker.stdout.readline())
                assert ready['affinity'] == [2], ready
                print(json.dumps({'block': block, 'variant': variant,
                                  'hash_seed':20261029+block, 'ready': ready}), flush=True)
            pair = {}
            for position, variant in enumerate(order):
                worker = workers[variant]
                worker.stdin.write(json.dumps({'case':'etl', 'documents':50000, 'batch_size':1000})+'\n')
                worker.stdin.flush()
                result = json.loads(worker.stdout.readline())
                assert 'error' not in result, result
                result.update(block=block, variant=variant, position=position, recorded_at=time.time())
                handle.write(json.dumps(result)+'\n'); handle.flush()
                pair[variant] = result
            for field in ['digest', 'input_digest', 'items', 'edges', 'failures']:
                assert pair['base'][field] == pair['candidate'][field], (block, field)
            print(json.dumps({'block':block, 'cpu_speedup':pair['base']['cpu_seconds']/pair['candidate']['cpu_seconds'],
                              'exact':True}), flush=True)
        finally:
            for worker in workers.values():
                if worker.poll() is None:
                    worker.stdin.write('{"stop":true}\n'); worker.stdin.flush()
                    try: worker.wait(timeout=15)
                    except subprocess.TimeoutExpired: worker.kill()
            for log in logs: log.close()
(root/('paired-cast-'+label+'-finished.txt')).write_text('Twelve independent process pairs; all exact fingerprints agree.\n')
