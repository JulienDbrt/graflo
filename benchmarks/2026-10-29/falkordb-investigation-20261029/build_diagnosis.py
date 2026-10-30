"""Build a checked summary and plot from the native SDK investigation."""

import json
import re
import statistics
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path('/evidence')


def load(stem):
    rows=[json.loads(line) for line in (ROOT/(stem+'.jsonl')).read_text().splitlines()]
    assert rows[-1].get('kind')=='finished', stem
    return rows


def timings(stem,size=10000):
    rows=[r for r in load(stem) if r.get('size')==size and 'seconds' in r]
    values=[r['seconds'] for r in rows]
    return {'median_seconds':statistics.median(values),'min_seconds':min(values),
            'max_seconds':max(values),'samples':len(values)}


def pending_rows(row):
    line=next(s for s in row['plan'] if 'Include Pending' in s)
    return int(re.search(r'Records produced: (\d+)',line).group(1))


def expected_pending(size):
    return sum(min(1024,size-start)*start for start in range(0,size,1024))


boundary=[r for r in load('rust-boundary') if 'seconds' in r]
for row in boundary:
    assert pending_rows(row)==expected_pending(row['size'])
old_profile=next(r for r in load('rust-profiles') if r.get('size')==10000 and r.get('operation')=='merge_new')
new_profile=next(r for r in load('edge-profiles') if r.get('size')==10000 and r.get('operation')=='merge_new')
assert pending_rows(old_profile)==expected_pending(10000)==44974080
assert pending_rows(new_profile)==0
old=timings('rust-repeat')
new=timings('edge-confirmed-repeat')
correctness={e:[r for r in load(e+'-correctness') if r.get('kind') in ['boundary_correctness','duplicates_correctness']] for e in ['c','rust','edge']}
assert all(r['passed'] for e in ['c','edge'] for r in correctness[e])
assert [r['nodes'] for r in correctness['rust']]==[2,1,1,7]
upstream=json.loads((ROOT/'upstream.json').read_text())
summary={
    'date':'2026-10-29 Europe/Madrid',
    'scope':'Native FalkorDB Python SDK; no GraFlo imports. Fresh graph per timed call.',
    'resources':{'database_cpu_quota':2,'database_cpuset':'0,1','database_memory_bytes':2147483648,
                 'client_cpu_quota':2,'client_cpuset':'2,3','client_memory_bytes':2147483648,
                 'THREAD_COUNT':2,'OMP_THREAD_COUNT':2,'host_shared':True},
    'query':'UNWIND $data AS row MERGE (n:Item {id: row.id}) ON MATCH SET n += row ON CREATE SET n += row',
    'payload':'Distinct text identity plus 100-character payload; range index on Item.id.',
    'stable_rust_6_0_3_merge_new_10000':old,
    'edge_merge_new_10000':new,
    'median_speedup':old['median_seconds']/new['median_seconds'],
    'edge_merge_new_25000':timings('edge-confirmed-large',25000),
    'edge_merge_new_50000':timings('edge-confirmed-large',50000),
    'native_profile':{'stable_pending_records':pending_rows(old_profile),'edge_pending_records':pending_rows(new_profile),
                      'batch_size':1024,'formula':'sum(min(1024,N-start)*start for start in range(0,N,1024))'},
    'root_cause':'Stable MergeOp creates one batch before matching the next. IncludePending pairs previously created nodes with every incoming argument row, then a filter discards nonmatches. Unique new identities incur near-quadratic intermediate work.',
    'boundary_profiles':[{'size':r['size'],'seconds':r['seconds'],'pending_records':pending_rows(r)} for r in boundary],
    'correctness':correctness,
    'upstream_pr':upstream['pr']['url'],'upstream_merge_commit':upstream['pr']['merge_commit_sha'],
    'upstream_merged_at':upstream['pr']['merged_at'],'edge_image_digest':upstream['edge_digest'],
    'image_provenance':'Official promotion job 123153842387 logs map rc-mg-b47d6d6a3c563818fec2f2655ad6f92583e2a62f to this exact edge/edge-rs digest.',
    'limitations':['Local ARM64 shared host; three timing samples per confirmed comparison.',
                   'Edge is a development image, not a stable release; no broad compatibility validation of this image.',
                   'Native-SDK timings differ from the earlier GraFlo ingestion protocol; do not combine their absolute times.',
                   'Files with warmup-concurrent in their name are excluded from timing conclusions.'],
    'publication':'Local only; no push or PR before 2026-10-30 Europe/Madrid.'}
(ROOT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')

plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,2,figsize=(12,4.4),layout='constrained')
threshold=[r for r in load('rust-threshold') if 'seconds' in r]
axes[0].plot([r['size'] for r in threshold],[r['seconds']*1000 for r in threshold],marker='o',label='Rust 6.0.3',color='#bf5b22')
sizes=[10000,25000,50000]
vals=[new,timings('edge-confirmed-large',25000),timings('edge-confirmed-large',50000)]
axes[0].errorbar(sizes,[r['median_seconds']*1000 for r in vals],
    yerr=[[(r['median_seconds']-r['min_seconds'])*1000 for r in vals],[(r['max_seconds']-r['median_seconds'])*1000 for r in vals]],
    marker='o',capsize=4,color='#2764b5',label='Rust edge corrigé (3 essais)')
axes[0].set(xscale='log',yscale='log',xlabel='Nouveaux sommets dans un seul MERGE',ylabel='Aller-retour SDK (ms)',title='Le correctif supprime la chute de débit')
axes[0].legend(fontsize=9)
axes[1].plot([r['size'] for r in boundary],[pending_rows(r) for r in boundary],marker='o',color='#bf5b22')
axes[1].axvline(1024,color='#777',linestyle='--',label='Bloc interne : 1 024 lignes')
axes[1].set(xlabel='Nouveaux sommets dans un seul MERGE',ylabel='Lignes intermédiaires Include Pending',title='Le surcoût commence après 1 024 entrées')
axes[1].legend(fontsize=9)
for ax in axes:ax.grid(True,alpha=.2)
fig.suptitle('Diagnostic natif FalkorDB · 2 CPU / 2 Gio par moteur · 29 octobre 2026')
fig.savefig(ROOT/'diagnostic.png',dpi=180)
fig.savefig(ROOT/'diagnostic.svg')
plt.close(fig)

report=f'''Diagnostic du ralentissement FalkorDB Rust 6.0.3 — 29 octobre 2026

Cause confirmée sans GraFlo, avec le SDK FalkorDB 1.8.1 / redis-py 8.1.0.
MERGE traite les entrées par blocs internes de 1 024 lignes. En 6.0.3, il
crée les sommets d'un bloc avant de chercher les correspondances du suivant.
Include Pending croise les sommets nouvellement créés avec chaque entrée
du nouveau bloc. Le filtre élimine ces lignes après leur construction.
Avec des identités toutes distinctes, le travail intermédiaire est quasi quadratique.

Preuve : PROFILE de 10 000 créations MERGE montre 44 974 080 lignes
Include Pending, puis 0 après Filter. La formule de croisement entre blocs
reproduit exactement les 7 profils autour de la frontière 1 024.

En 6.0.3, 10 000 CREATE prennent ~28 ms, MERGE sur des sommets existants
~29 ms, MERGE sur des sommets neufs ~2,55 s (sondes initiales).
Ni l'index range ni la contrainte unique ne suppriment le défaut.

Comparaison confirmée, trois appels neufs par moteur, exécutés successivement :
Rust 6.0.3 : médiane {old['median_seconds']*1000:.2f} ms ;
Rust edge corrigé : médiane {new['median_seconds']*1000:.2f} ms ;
gain {summary['median_speedup']:.2f} fois. Le profil edge produit 0 ligne pending.
Edge 50 000 créations : médiane {summary['edge_merge_new_50000']['median_seconds']*1000:.2f} ms.

Correctif amont déjà fusionné : {summary['upstream_pr']}
Commit {summary['upstream_merge_commit']}
Fusion {summary['upstream_merged_at']} (29 octobre, 00:01:57 Europe/Madrid).
Le correctif fait toutes les recherches MERGE avant de créer les sommets.
L'image officielle edge testée est reliée au commit par les journaux de
promotion CI, conservés en extrait dans upstream.json :
falkordb/falkordb-server@{summary['edge_image_digest']}

Ce mécanisme affectait aussi le résultat de certains MERGE : le reproducer
amont retourne 2 sommets en C, mais 1 en Rust 6.0.3 au-delà de la frontière.
La vérification locale retrouve 2 pour N=2,1025,3000 sur C et edge corrigé,
contre 2,1,1 sur Rust 6.0.3. Le contrôle 3 000 doublons / 7 identités conserve
7 sommets sur les trois moteurs. Données dans *-correctness.jsonl.

Reproduction : isolate.py --phase matrix|profiles|threshold|boundary|repeat|large|correctness
  --engine LABEL --out RESULT.jsonl, avec Python et FalkorDB local sur 6379.
Chaque graphe est neuf et supprimé après vérification du nombre de sommets
et de leur payload. Les mises en place, vérifications et suppressions ne
sont pas incluses dans les durées. Même requête, index et données avant/après.
Source 6.0.3 : https://github.com/FalkorDB/FalkorDB/blob/v6.0.3/graph/src/runtime/ops/include_pending.rs#L109
Taille du bloc : https://github.com/FalkorDB/FalkorDB/blob/v6.0.3/graph/src/runtime/batch.rs#L81

Ressources : serveurs 2 CPU (0,1), 2 Gio, THREAD_COUNT=2, OMP_THREAD_COUNT=2 ;
clients 2 autres CPU (2,3), 2 Gio ; Linux aarch64 / OrbStack, hôte partagé.
Démarrage direct redis-server --loadmodule /var/lib/falkordb/bin/falkordb.so
THREAD_COUNT 2 OMP_THREAD_COUNT 2. Images stables et environnement détaillés
dans ../falkordb-benchmarks-20261029/protocol.json.
Les fichiers *-warmup-concurrent.* sont exclus des conclusions de timing.
Leurs premiers essais ont partagé les cœurs ; les comparaisons retenues
sont rust-repeat.jsonl puis edge-confirmed-repeat/large.jsonl, successivement.

La recommandation --batch-size 1000 reste valable pour 6.0.3. L'image edge
est une version de développement ; cette enquête ne valide pas son ensemble
fonctionnel. Aucun changement du connecteur nécessaire pour cette cause.
Le comportement de MERGE est conservé ; CREATE n'est pas un remplacement.

Tout reste local. Aucun push ni PR avant le 30 octobre 2026 Europe/Madrid.
'''
(ROOT/'README.txt').write_text(report)
print(json.dumps({k:summary[k] for k in ['stable_rust_6_0_3_merge_new_10000','edge_merge_new_10000','median_speedup','edge_merge_new_50000','native_profile']},indent=2))
