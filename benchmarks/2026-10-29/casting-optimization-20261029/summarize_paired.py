"""Paired CPU/wall summaries; bootstrap resamples pairs, not documents."""

import argparse
import json
import random
import statistics
from pathlib import Path

ROOT=Path(__file__).parent


def summarize(path):
    rows=[json.loads(x) for x in path.read_text().splitlines()]
    summaries=[]
    for name,batch in sorted({(r['case'],r['batch_size']) for r in rows}):
        ratios={field:[] for field in ['cpu_seconds','seconds']}
        durations={v:{f:[] for f in ratios} for v in ['base','candidate']}
        for block in sorted({r['block'] for r in rows if r['case']==name and r['batch_size']==batch}):
            pair={r['variant']:r for r in rows if r['case']==name and r['batch_size']==batch and r['block']==block}
            assert set(pair)=={'base','candidate'}
            for field in ['digest','input_digest','items','edges','failures']:
                assert pair['base'][field]==pair['candidate'][field],(name,batch,block,field)
            for field in ratios:
                ratios[field].append(pair['base'][field]/pair['candidate'][field])
                for variant in durations:durations[variant][field].append(pair[variant][field])
        intervals={}
        for field,values in ratios.items():
            rng=random.Random(20261029)
            boot=sorted(statistics.median(rng.choices(values,k=len(values))) for _ in range(10000))
            intervals[field]=[boot[250],boot[9749]]
        cpu_speedup=statistics.median(ratios['cpu_seconds'])
        summary={'case':name,'documents_per_run':next(r['documents'] for r in rows if r['case']==name and r['batch_size']==batch),
                 'batch_size':batch,'pairs':len(ratios['cpu_seconds']),
                 'median_cpu_speedup':cpu_speedup,'median_cpu_time_reduction_percent':(1-1/cpu_speedup)*100,
                 'cpu_speedup_ci95':intervals['cpu_seconds'],
                 'median_wall_speedup':statistics.median(ratios['seconds']),
                 'wall_speedup_ci95':intervals['seconds'],
                 'timings':{v:{f:{'median':statistics.median(vals),'min':min(vals),'max':max(vals)} for f,vals in fields.items()} for v,fields in durations.items()},
                 'cpu_ratios':ratios['cpu_seconds'],'wall_ratios':ratios['seconds'],
                 'reliable_cpu_regression_over_2_percent':intervals['cpu_seconds'][1] < 1/1.02}
        summaries.append(summary)
    result={'source':path.name,'measured_runs':len(rows),'pairs':len(rows)//2,'all_typed_fingerprints_equal':True,
            'bootstrap':{'unit':'paired run','samples':10000,'seed':20261029,'statistic':'median CPU/wall speedup'},
            'conditions':summaries}
    output=path.with_name(path.stem+'-summary.json')
    output.write_text(json.dumps(result,indent=2)+'\n')
    for s in summaries:print(s['case'],s['batch_size'],s['documents_per_run'],s['pairs'],
        'CPU reduction %',round(s['median_cpu_time_reduction_percent'],2),'speedup CI',*[round(x,4) for x in s['cpu_speedup_ci95']])
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('file',type=Path)
    summarize(parser.parse_args().file)
