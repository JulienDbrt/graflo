"""Run fresh, equally limited Docker server/client pairs sequentially."""

import datetime
import hashlib
import json
import subprocess
import time
from pathlib import Path

from scenario import generate,manifest_config

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent/'falkordb-compat'
VENV=Path('/private/tmp/graflo-falkordb-20261028/.venv')
HELPER='graflo-falkordb-testenv:20261028'
IMAGES={
    'c':'falkordb/falkordb@sha256:725b74d400124862c9e0f318c56bfb3c55b97cd7f301d9dfe8685980fb3c8195',
    'rust':'falkordb/falkordb@sha256:0fb85036662ce3d1206530a38fdf7df5a92b1fb31ad23087f8d4e89038ce0812',
    'edge':'falkordb/falkordb-server@sha256:3d08d1a1536394210d7f435bcfc777a58ba9d21f58f23cf2b86918772028b941',
}
ORDER=[(trial,engine) for trial,engines in [(1,['c','rust','edge']),(2,['rust','edge','c']),(3,['edge','c','rust'])] for engine in engines]


def command(*args,**kw):
    result=subprocess.run(list(args),text=True,capture_output=True,**kw)
    if result.returncode:
        raise RuntimeError(f'{args[0]} {args[1:3]}: {result.stderr.strip()}')
    return result.stdout.strip()


def emit(kind,**fields):
    row={'kind':kind,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),**fields}
    with (ROOT/'campaign.jsonl').open('a') as handle:handle.write(json.dumps(row)+'\n')
    print(json.dumps(row),flush=True)


generate(ROOT,100000)
(ROOT/'manifest.json').write_text(json.dumps(manifest_config(),indent=2)+'\n')
protocol={
    'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'repo_commit':command('git','-C',str(REPO),'rev-parse','HEAD'),
    'repo_status':command('git','-C',str(REPO),'status','--short'),
    'images':IMAGES,'helper_image':HELPER,
    'order':[{'trial':t,'engine':e} for t,e in ORDER],
    'resources':{'server_cpus':'0,1','server_cpu_quota':2,'server_memory_bytes':2147483648,
                 'client_cpus':'2,3','client_cpu_quota':2,'client_memory_bytes':2147483648,
                 'THREAD_COUNT':2,'OMP_THREAD_COUNT':2},
    'scenario':{'initial_source_records':100000,'initial_items':100000,'initial_categories':1000,'initial_edges':100000,
                'second_source_records':100000,'second_updates':50000,'second_new_items':50000,
                'final_items':150000,'final_categories':1000,'final_edges':150000,
                'source_formats':['CSV','JSONL'],'source_format_split':'50% each, sequential',
                'batch_size':1000,'cast_executor':'inline','n_cores':1,'max_in_flight_batches':1,
                'max_concurrent_db_ops':1,'max_concurrent_sources':1,'batch_prefetch':2},
    'reads':{'processes':4,'per_process_target_qps':25,'target_qps':100,'warmup_seconds':2,
             'pre_ingest_baseline_seconds':10,'post_ingest_baseline_seconds':10,
             'kinds':['point','one_hop','two_hops','range_sort','group_count'],
             'load_model':'Paced with at most one outstanding query per reader. Achieved rate and scheduling lag are retained; this is not an unbounded open-loop load generator.'},
    'memory':{'sample_interval_seconds':.1,'measurements':['server RSS/HWM','ingester RSS/HWM',
              'server cgroup current/peak/anon/file','client cgroup current/peak/anon/file'],
              'client_cgroup_includes_readers':True,'sampling_overhead_included':True},
    'validation':'Full ordered projection of every Item property and every relationship endpoint after each ingestion; identical canonical SHA256 expected across engines. All reader results checked. Index and unique-constraint catalogues checked.',
    'timing':'Schema definition, process startup, reader warmup, final validation and PROFILE excluded from ingestion timing. Source reading, transformations, casting and writes included. Component durations can overlap with source prefetch and must not be summed as wall-clock partitions.',
    'limits':['Shared ARM64 OrbStack host. Local CPU pinning does not reserve cores from other workloads.',
              'File-system cache is not flushed; this is not a cold-disk benchmark.',
              'The graph grows during mixed load; pre-100k and post-150k idle baselines bracket this change.',
              'No crash recovery, persistence or cross-version migration is tested by this scenario.',
              'Only batch size 1000 and one casting/DB-write concurrency configuration are compared.'],
    'publication':'Local only. No push or PR before 2026-10-30 Europe/Madrid.',
    'harness_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')},
}
(ROOT/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
for trial,engine in ORDER:
    db=f'graflo-etl-{engine}-t{trial}-20261029'
    client=db+'-client'
    directory=ROOT/f'{engine}-trial-{trial}'
    if (directory/'result.json').exists():
        emit('already_complete',engine=engine,trial=trial)
        continue
    emit('trial_start',engine=engine,trial=trial)
    try:
        command('docker','run','-d','--name',db,'--label','graflo.task=falkordb-etl-20261029',
            '--cpus=2','--cpuset-cpus=0,1','--memory=2g','--entrypoint','redis-server',IMAGES[engine],
            '--loadmodule','/var/lib/falkordb/bin/falkordb.so','THREAD_COUNT','2','OMP_THREAD_COUNT','2')
        command('docker','run','-d','--name',client,'--label','graflo.task=falkordb-etl-20261029',
            '--cpus=2','--cpuset-cpus=2,3','--memory=2g','--network','container:'+db,'--pid','container:'+db,
            '--mount',f'type=bind,src={REPO},dst=/repo,readonly',
            '--mount',f'type=bind,src={VENV},dst=/repo/.venv,readonly',
            '--mount',f'type=bind,src={ROOT},dst=/evidence','-e','PYTHONDONTWRITEBYTECODE=1',HELPER,'sleep','infinity')
        with (ROOT/f'{engine}-trial-{trial}.log').open('w') as handle:
            process=subprocess.Popen(['docker','exec','-e','PYTHONPATH=/repo:/evidence',client,
                'uv','run','--frozen','--no-sync','python','/evidence/benchmark.py','--engine',engine,'--trial',str(trial)],
                stdout=handle,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+900
            seen=0
            while process.poll() is None:
                if time.monotonic()>deadline:
                    process.terminate()
                    raise TimeoutError('trial exceeded 900 seconds')
                events=directory/'events.jsonl'
                if events.exists():
                    lines=events.read_text().splitlines()
                    for line in lines[seen:]:
                        row=json.loads(line)
                        if row['kind'] in ['phase_start','phase_finished','validated','failed']:
                            emit('progress',engine=engine,trial=trial,event={k:v for k,v in row.items() if k in ['kind','phase','seconds','documents_per_second','items','edges','error']})
                    seen=len(lines)
                time.sleep(.5)
            if process.returncode!=0:raise RuntimeError(f'benchmark exit {process.returncode}; see {engine}-trial-{trial}.log')
        result=json.loads((directory/'result.json').read_text())
        emit('trial_passed',engine=engine,trial=trial,initial_seconds=result['initial']['seconds'],
             mixed_seconds=result['mixed']['seconds'],reads=result['read_count'])
    except Exception as error:
        emit('trial_failed',engine=engine,trial=trial,error=repr(error))
    finally:
        if directory.exists():
            for name in [db,client]:
                info=subprocess.run(['docker','inspect',name,'--format','{{json .State}}'],capture_output=True,text=True)
                (directory/(name+'-state.json')).write_text(info.stdout)
        subprocess.run(['docker','rm','-f',client,db],capture_output=True)
emit('campaign_finished')
