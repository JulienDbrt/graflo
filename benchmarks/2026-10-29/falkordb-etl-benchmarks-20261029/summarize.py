"""Summarize repeated trials; preserve per-trial quantiles rather than pool samples."""

import argparse
import json
import statistics
from pathlib import Path

ROOT=Path(__file__).parent
ENGINES=['c','rust','edge']
KINDS=['point','one_hop','two_hops','range_sort','group_count']


def distribution(values):
    return {'median':statistics.median(values),'min':min(values),'max':max(values),'trials':len(values)}


def percentile(values,p):
    values=sorted(values)
    position=(len(values)-1)*p
    lo=int(position);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(position-lo)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def window(result,phase):
    if phase in ['initial','mixed']:return result[phase]['started'],result[phase]['ended']
    if phase=='idle':return result['idle_read_started'],result['idle_read_ended']
    return result['post_read_started'],result['post_read_ended']


def summarize_trial(path):
    result=json.loads((path/'result.json').read_text())
    memory=read_jsonl(path/'memory.jsonl')
    events=read_jsonl(path/'events.jsonl')
    assert not any(r['kind']=='monitor_error' for r in events)
    assert result['passed'] and not result['read_failures']
    for field in ['initial_validation','final_validation']:
        validation=result[field]
        assert {r[0]:set(r[1]) for r in validation['indexes']}=={
            'Item':{'tenant','id','score','seq'},'Category':{'tenant','id'}}
        assert {(c['label'],tuple(c['properties']),c['type'],c['entitytype'],c['status'])
                for c in validation['constraints']}=={
                    ('Item',('tenant','id'),'UNIQUE','NODE','OPERATIONAL'),
                    ('Category',('tenant','id'),'UNIQUE','NODE','OPERATIONAL')}
    result['reader_control_retries']=sum(int(p.read_text()) for p in path.glob('reader-*-control-retries.txt'))
    reads=[r for f in path.glob('reader-*.jsonl') for r in read_jsonl(f)]
    assert all(r['passed'] for r in reads)
    result['read_metrics']={}
    for phase in ['idle','mixed','post_idle']:
        start,end=window(result,phase)
        selected=[r for r in reads if r['phase']==phase and start<=r['started']<=end]
        assert len(selected)>100,(path,phase,len(selected))
        result['read_metrics'][phase]={'queries':len(selected),'seconds':end-start,
            'achieved_qps':len(selected)/(end-start),'failures':sum(not r['passed'] for r in selected),'kinds':{}}
        for kind in KINDS:
            rows=[r for r in selected if r['kind']==kind]
            assert len(rows)>20,(path,phase,kind,len(rows))
            values=[r['latency_ms'] for r in rows]
            result['read_metrics'][phase]['kinds'][kind]={
                'queries':len(rows),'p50_ms':percentile(values,.5),'p95_ms':percentile(values,.95),
                'p99_ms':percentile(values,.99),'max_ms':max(values),
                'schedule_lag_p95_ms':percentile([r['schedule_lag_ms'] for r in rows],.95)}
    result['resource_metrics']={}
    for phase in ['initial','mixed','idle','post_idle']:
        start,end=window(result,phase)
        rows=[r for r in memory if start<=r['time']<=end]
        assert len(rows)>2
        span=rows[-1]['time']-rows[0]['time']
        result['resource_metrics'][phase]={
            'samples':len(rows),'max_sampling_gap_seconds':max(b['time']-a['time'] for a,b in zip(rows,rows[1:])),
            'server_rss_peak_bytes':max(r['server_rss']['VmRSS'] for r in rows),
            'server_cgroup_peak_sampled_bytes':max(r['server_cgroup']['memory_current'] for r in rows),
            'server_anon_peak_bytes':max(r['server_cgroup']['memory_anon'] for r in rows),
            'client_cgroup_peak_sampled_bytes':max(r['client_cgroup']['memory_current'] for r in rows),
            'client_anon_peak_bytes':max(r['client_cgroup']['memory_anon'] for r in rows),
            'ingester_rss_peak_bytes':max(r['ingester_rss']['VmRSS'] for r in rows),
            'server_cpu_average_cores':(rows[-1]['server_cgroup']['usage_usec']-rows[0]['server_cgroup']['usage_usec'])/1e6/span,
            'client_cpu_average_cores':(rows[-1]['client_cgroup']['usage_usec']-rows[0]['client_cgroup']['usage_usec'])/1e6/span,
            'server_throttled_seconds':(rows[-1]['server_cgroup']['throttled_usec']-rows[0]['server_cgroup']['throttled_usec'])/1e6,
            'client_throttled_seconds':(rows[-1]['client_cgroup']['throttled_usec']-rows[0]['client_cgroup']['throttled_usec'])/1e6,
        }
    result['lifetime_cgroup_peaks']={side:max(r[side+'_cgroup']['memory_peak'] for r in memory) for side in ['server','client']}
    return result


def build(strict=True):
    trials={engine:[summarize_trial(p.parent) for p in sorted(ROOT.glob(engine+'-trial-*/result.json'))] for engine in ENGINES}
    if strict:assert all(len(v)==3 for v in trials.values()),{k:len(v) for k,v in trials.items()}
    all_trials=[r for rs in trials.values() for r in rs]
    for field in ['initial_validation','final_validation']:
        assert len({r[field]['sha256'] for r in all_trials})==1
    summary={'protocol':'protocol.json','completed_trials':len(all_trials),'expected_trials':9,
             'source_records_processed':sum(2*r['documents_per_ingest'] for r in all_trials),
             'read_queries_including_warmup':sum(r['read_count'] for r in all_trials),
             'read_failures':sum(r['read_failures'] for r in all_trials),
             'control_file_retries':sum(r['reader_control_retries'] for r in all_trials),
             'validation_digests':{field:all_trials[0][field]['sha256'] for field in ['initial_validation','final_validation']},
             'engines':{},'trials':trials}
    for engine,records in trials.items():
        if not records:continue
        data={'trials':len(records),'ingestion':{},'reads':{},'resources':{}}
        for phase in ['initial','mixed']:
            data['ingestion'][phase]={field:distribution([r[phase][field] for r in records]) for field in ['seconds','documents_per_second']}
            data['ingestion'][phase]['components']={kind:distribution([r[phase]['instrumentation'][kind]['seconds'] for r in records]) for kind in ['source_read','cast','write']}
        for phase in ['idle','mixed','post_idle']:
            data['reads'][phase]={'achieved_qps':distribution([r['read_metrics'][phase]['achieved_qps'] for r in records]),'kinds':{}}
            for kind in KINDS:
                data['reads'][phase]['kinds'][kind]={field:distribution([r['read_metrics'][phase]['kinds'][kind][field] for r in records]) for field in ['p50_ms','p95_ms','p99_ms','max_ms','schedule_lag_p95_ms']}
        for phase in ['initial','mixed','idle','post_idle']:
            data['resources'][phase]={field:distribution([r['resource_metrics'][phase][field] for r in records]) for field in records[0]['resource_metrics'][phase]}
        summary['engines'][engine]=data
    (ROOT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    for engine,data in summary['engines'].items():
        print(engine,'trials',data['trials'],'initial',round(data['ingestion']['initial']['seconds']['median'],2),
            'mixed',round(data['ingestion']['mixed']['seconds']['median'],2),
            'server peak MiB',round(data['resources']['mixed']['server_rss_peak_bytes']['median']/2**20,1),
            'client peak MiB',round(data['resources']['mixed']['client_cgroup_peak_sampled_bytes']['median']/2**20,1))
    print('completed',summary['completed_trials'],'reads',summary['read_queries_including_warmup'],'errors',summary['read_failures'])
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--partial',action='store_true')
    build(strict=not parser.parse_args().partial)
