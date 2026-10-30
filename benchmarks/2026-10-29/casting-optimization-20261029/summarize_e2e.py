import json
from pathlib import Path
import statistics

p=Path(__file__).resolve().parent
rows=[json.loads((p/'e2e'/f'{v}-{b}'/'result.json').read_text()) for b in range(4) for v in ['base','candidate']]
locks=json.loads((p/'locked-source-hardened.json').read_text())
base=json.loads((p/'differential-fusion-hardened.json').read_text())['base_sha256']
for r in rows:
    assert r['passed'] and r['documents']==100000 and r['affinity']==[2]
    assert r['source_sha256']==(base if r['variant']=='base' else locks['graflo/architecture/graph_types/merge.py'])
    assert {(c['type'],c['label'],tuple(c['properties']),c['entitytype'],c['status']) for c in r['constraints']}=={('UNIQUE',label,('tenant','id'),'NODE','OPERATIONAL') for label in ['Item','Category']}
    for field in ['files','typed_nodes_sha256','typed_edges_sha256','items','categories','edges']:
        assert r[field]==rows[0][field],(r['variant'],r['trial'],field)
    # The unsorted index-listing query changes row order even on the reference.
    # Preserve that observed difference explicitly; retain property order.
    assert {(label,tuple(properties)) for label,properties in r['indexes']}=={
        ('Category',('tenant','id')),('Item',('tenant','id','score','seq'))}
index_audit={'raw_row_orders':[{k:r[k] for k in ['variant','trial','indexes']} for r in rows],
             'raw_order_identical_across_trials':all(r['indexes']==rows[0]['indexes'] for r in rows),
             'full_rows_identical_as_set':True,'property_order_identical':True,
             'explanation':'Unsorted db.indexes listing enumerates labels in different orders, including between two reference trials. Initial strict list comparison raised on base trial1. Raw lists retained; equality of complete rows checked as a set, while property order is preserved. Graph data are not normalized.'}
(p/'index-listing-order-audit.json').write_text(json.dumps(index_audit,indent=2)+'\n')
metrics={}
for field in ['seconds','client_cpu_seconds','server_cpu_seconds']:
    ratios=[]
    for block in range(4):
        pair={r['variant']:r for r in rows if r['trial']==block}
        ratios.append(pair['base'][field]/pair['candidate'][field])
    median=statistics.median(ratios)
    metrics[field]={'paired_speedups':ratios,'median_speedup':median,'median_time_reduction_percent':100*(1-1/median),
        'durations':{v:[r[field] for r in rows if r['variant']==v] for v in ['base','candidate']}}
summary={'pairs':4,'measured_runs':8,'all_typed_hashes_equal':True,'passed':True,
         'validated_items':sum(r['items'] for r in rows),'validated_categories':sum(r['categories'] for r in rows),'validated_edges':sum(r['edges'] for r in rows),
         'metrics':metrics,'results':[f'e2e/{r["variant"]}-{r["trial"]}/result.json' for r in rows],
         'index_listing_order_difference':'index-listing-order-audit.json',
         'memory':'Kernel lifetime peaks include startup and are recorded before exhaustive verification; no causal memory reduction claim.',
         'memory_peaks_at_ingestion_end':[{k:r[k] for k in ['variant','trial','kernel_peaks_at_ingestion_end']} for r in rows],
         'interpretation':'Exploratory corroboration; only four pairs on a shared host, no outliers excluded.'}
(p/'e2e-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v['median_time_reduction_percent'] for k,v in metrics.items()},indent=2))
