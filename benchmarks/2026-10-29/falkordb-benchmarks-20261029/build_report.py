"""Render the local benchmark evidence as standalone plots and an HTML report."""

import datetime
import html
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


ROOT=Path('/evidence')
LABELS={'c':'C · 4.22.3','rust':'Rust · 6.0.3'}
COLORS={'c':'#2764b5','rust':'#bf5b22'}


def load(engine,phase):
    rows=[json.loads(line) for line in (ROOT/f'{engine}-{phase}.jsonl').read_text().splitlines()]
    assert rows[-1]['kind']=='finished', (engine,phase)
    return rows


DATA={engine:{phase:load(engine,phase) for phase in ['realistic','parse']} for engine in LABELS}
SUITES={engine:json.loads((ROOT/f'suite-{engine}.json').read_text()) for engine in LABELS}
assert all(suite['exit_status']==0 and len(suite['cases'])==21 for suite in SUITES.values())


def select(engine,kind,indexed=None,batch=None,size=None):
    rows=DATA[engine]['parse' if kind in ['parameter_only','generated_range'] else 'realistic']
    return [r for r in rows if r['kind']==kind
            and (indexed is None or r['indexed']==indexed)
            and (batch is None or r['batch_size']==batch)
            and (size is None or r['documents']==size)]


def stats(records,field):
    values=[row[field] for row in records]
    return {'median':statistics.median(values),'min':min(values),'max':max(values),'samples':len(values)}


def metric(engine,kind,field,**filters):
    return stats(select(engine,kind,**filters),field)


summary={'generated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
         'commit':'3230dfb28d05380b5e0517ec7d6c88fc88f3fe2e',
         'limits':{'database_cpu':2,'database_memory_bytes':2147483648,'client_cpu':2,
                   'client_memory_bytes':2147483648,'thread_count':2,'omp_thread_count':2},
         'engines':{},'ingest':[],'operations':[],'parameters':[]}
summary['findings']={
    'rust_batch_1000_vs_10000_speedup': metric('rust','ingest','documents_per_second',indexed=True,batch=1000)['median']/metric('rust','ingest','documents_per_second',indexed=True,batch=10000)['median'],
    'rust_parameter_only_50000_seconds': metric('rust','parameter_only','seconds',size=50000)['median'],
    'interpretation':'The write-path slowdown is not explained by parameter parsing alone; a server CPU profile is needed to locate it precisely.',
    'practical_setting':'With schema/indexes defined, use --batch-size 1000 as an initial setting for 6.0.3 and measure the workload.',
}
for engine in LABELS:
    summary['engines'][engine]=next(r for r in DATA[engine]['realistic'] if r['kind']=='metadata')
    for indexed in [False,True]:
        for batch in [1,100,1000,10000]:
            summary['ingest'].append({'engine':engine,'indexed':indexed,'batch_size':batch,
                'documents_per_second':metric(engine,'ingest','documents_per_second',indexed=indexed,batch=batch),
                'seconds':metric(engine,'ingest','seconds',indexed=indexed,batch=batch)})
        for kind in ['point_lookup','point_update','category_count']:
            summary['operations'].append({'engine':engine,'indexed':indexed,'kind':kind,
                **{field:metric(engine,kind,field,indexed=indexed) for field in [
                    'operations_per_second','latency_p50_ms','latency_p95_ms','latency_p99_ms']}})
    for size in [1000,5000,10000,25000,50000]:
        summary['parameters'].append({'engine':engine,'documents':size,
            **{field:metric(engine,'parameter_only',field,size=size) for field in [
                'seconds','server_reported_ms','formatting_seconds','payload_bytes']},
            'range_seconds':metric(engine,'generated_range','seconds',size=size)})
(ROOT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')

plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,2,figsize=(12.5,4.6),layout='constrained')
for engine in LABELS:
    for indexed in [False,True]:
        batches=[1,100,1000,10000]
        values=[metric(engine,'ingest','documents_per_second',indexed=indexed,batch=b) for b in batches]
        mids=[v['median'] for v in values]
        axes[0].errorbar(batches,mids,
            yerr=[[v['median']-v['min'] for v in values],[v['max']-v['median'] for v in values]],
            label=LABELS[engine]+(' · schéma défini' if indexed else ' · sans index'),
            color=COLORS[engine],linestyle='-' if indexed else '--',marker='o' if indexed else 's',capsize=3)
    sizes=[1000,5000,10000,25000,50000]
    values=[metric(engine,'parameter_only','seconds',size=s) for s in sizes]
    axes[1].plot(sizes,[v['median']*1000 for v in values],marker='o',color=COLORS[engine],label=LABELS[engine])
axes[0].set(xscale='log',yscale='log',xlabel='Documents par lot',ylabel='Documents / seconde',title='Ingestion de 10 000 documents')
axes[0].legend(fontsize=8)
axes[1].set(xscale='log',yscale='log',xlabel='Maps envoyées en paramètre',ylabel='Aller-retour client (ms)',title='RETURN size($data) · aucune écriture')
axes[1].legend(fontsize=9)
for ax in axes: ax.grid(True,which='both',alpha=.18)
fig.suptitle('FalkorDB : mêmes ressources · médiane de 3 essais (1 pour 25k/50k paramètres)',fontsize=12)
fig.savefig(ROOT/'comparaison.png',dpi=180)
fig.savefig(ROOT/'comparaison.svg')
plt.close(fig)

fig,ax=plt.subplots(figsize=(9.4,4.2),layout='constrained')
operation_labels={'point_lookup':'Lecture par identité','point_update':'Mise à jour par identité','category_count':'Comptage par catégorie'}
for offset,engine in [(-.18,'c'),(.18,'rust')]:
    xs=[i+offset for i in range(3)]
    values=[metric(engine,kind,'latency_p95_ms',indexed=True) for kind in operation_labels]
    ax.bar(xs,[v['median'] for v in values],width=.34,color=COLORS[engine],label=LABELS[engine])
    ax.errorbar(xs,[v['median'] for v in values],fmt='none',color='#333333',capsize=4,
        yerr=[[v['median']-v['min'] for v in values],[v['max']-v['median'] for v in values]])
ax.set_xticks(range(3),list(operation_labels.values()))
ax.set(ylabel='Latence p95 (ms)',title='10 000 sommets · schéma et index définis · 200 opérations par essai')
ax.legend()
ax.grid(axis='y',alpha=.2)
fig.savefig(ROOT/'latences.png',dpi=180)
fig.savefig(ROOT/'latences.svg')
plt.close(fig)


def number(value,decimals=2):
    return f'{value:,.{decimals}f}'.replace(',','\u202f').replace('.',',')


def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(h))+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table>'


ingest_rows=[]
for indexed in [True,False]:
    for batch in [1,100,1000,10000]:
        values={engine:metric(engine,'ingest','documents_per_second',indexed=indexed,batch=batch)['median'] for engine in LABELS}
        ingest_rows.append(['Défini' if indexed else 'Absent',number(batch,0),number(values['c'],0),number(values['rust'],0),number(values['rust']/values['c'],2)+'×'])
operation_rows=[]
for indexed in [True,False]:
    for kind,label in operation_labels.items():
        for engine in LABELS:
            operation_rows.append(['Défini' if indexed else 'Absent',label,LABELS[engine],
                *[number(metric(engine,kind,key,indexed=indexed)['median'],3) for key in ['latency_p50_ms','latency_p95_ms','latency_p99_ms']],
                number(metric(engine,kind,'operations_per_second',indexed=indexed)['median'],0)])
parameter_rows=[]
for size in [1000,5000,10000,25000,50000]:
    c=metric('c','parameter_only','seconds',size=size)['median']
    rust=metric('rust','parameter_only','seconds',size=size)['median']
    parameter_rows.append([number(size,0),number(metric('c','parameter_only','payload_bytes',size=size)['median']/1024/1024,2),
        number(c*1000,2),number(rust*1000,2),number(rust/c,1)+'×',
        metric('c','parameter_only','seconds',size=size)['samples']])

suite_rows=[]
for engine in LABELS:
    suite=SUITES[engine]
    flags=[line.strip() for case in suite['cases'].values() for line in case['stdout'].splitlines()
           if ('Errors:' in line and line.strip().split(':')[-1].strip()!='0') or 'FAIL:' in line]
    suite_rows.append([LABELS[engine],sum(c['outcome']=='passed' for c in suite['cases'].values()),
        number(sum(c['seconds'] for c in suite['cases'].values()),1),'; '.join(flags) if flags else '0 erreur signalée'])

document='''<!doctype html><html lang="fr"><meta charset="utf-8"><title>FalkorDB — benchmarks locaux du 29 octobre 2026</title>
<style>body{font:16px/1.6 system-ui,sans-serif;max-width:1200px;margin:36px auto;padding:0 24px;color:#192738;background:#fcfcfd}h1,h2{line-height:1.2}h2{margin-top:42px}p,li{max-width:1000px}table{border-collapse:collapse;width:100%;font-size:14px;margin:18px 0;overflow:auto}th,td{padding:9px 12px;border-bottom:1px solid #dce2eb;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#eaf0f8}figure{margin:24px 0}figure svg{width:100%;height:auto}code{background:#edf1f7;padding:2px 5px;border-radius:4px}a{color:#245da8}.note{padding:16px 22px;background:#eef3fa;border-left:4px solid #2764b5}small{color:#526174}</style>
<h1>FalkorDB C 4.22.3 et Rust 6.0.3</h1><p>Benchmarks locaux du 29 octobre 2026, connecteur GraFlo au commit <code>3230dfb</code>. Les résultats mesurent ce connecteur et ces charges de travail ; ils ne classent pas les moteurs dans tous les usages.</p>
<div class="note"><b>Protocole.</b> Moteurs exécutés successivement, chacun limité à 2 CPU et 2 Gio, avec <code>THREAD_COUNT=2</code> et <code>OMP_THREAD_COUNT=2</code>. Client limité à 2 autres CPU et 2 Gio. Python 3.11.13, client FalkorDB 1.8.1 et redis-py 8.1.0. Linux aarch64 / OrbStack, hôte partagé avec d’autres activités.</div>
<h2>Résultats à retenir</h2><ul><li>Avec schéma défini et lots de 1 000 : environ <b>148 000 docs/s en C</b> et <b>138 000 docs/s en Rust</b>.</li><li>Avec des lots de 10 000, Rust tombe à environ <b>3 400 docs/s</b>. Revenir à 1 000 améliore son débit d’environ <b>40 fois</b> dans ce protocole. GraFlo utilise 10 000 par défaut ; <code>--batch-size 1000</code> est un point de départ mesuré pour 6.0.3.</li><li>Recevoir 50 000 maps sans écrire prend environ <b>90 ms sous Rust</b>, alors que l’écriture d’un lot de 50 000 prend environ <b>72 s</b> dans la suite historique. Le parsing seul ne peut expliquer le ralentissement. Le chemin d’écriture doit être profilé pour localiser la cause exacte.</li><li><b>21/21 cas de performance réussis sur chaque moteur</b>, sans erreur de concurrence signalée.</li></ul>
<h2>Ingestion et taille des paramètres</h2><figure>'''+(ROOT/'comparaison.svg').read_text().split('<svg',1)[-1].join(['<svg',''])+'''</figure>
<p>Chaque ingestion écrit 10 000 documents neufs (identité texte, charge utile de 100 caractères). Trois essais sur trois graphes distincts par condition. « Schéma défini » comprend l’index et la contrainte d’unicité de l’identité, plus un index de catégorie. La création du schéma, la génération des documents et les vérifications sont hors mesure. Les barres montrent le minimum et le maximum des trois essais.</p>'''+table(['Schéma','Taille du lot','C : docs/s','Rust : docs/s','Rust / C'],ingest_rows)+'''
<h2>Latences sur données indexées</h2><figure>'''+(ROOT/'latences.svg').read_text().split('<svg',1)[-1].join(['<svg',''])+'''</figure>
<p>10 000 sommets préchargés ; 20 opérations d’échauffement, puis 200 opérations mesurées par essai. Les valeurs sont les médianes des trois essais. Le comptage porte sur une catégorie contenant exactement 1 000 sommets. Les lectures et les comptages sont vérifiés ; les mises à jour conservent la cardinalité et leur dernière valeur est contrôlée.</p>'''+table(['Schéma','Opération','Moteur','p50 (ms)','p95 (ms)','p99 (ms)','op/s'],operation_rows)+'''
<h2>Sonde sans écriture</h2><p><code>RETURN size($data)</code> reçoit une liste de maps identique à celle envoyée en ingestion. Il ne crée aucun sommet et n’utilise aucun index. Le temps mesuré inclut validation du connecteur, sérialisation du SDK, transport, traitement serveur et décodage d’un seul entier. Le coût de formatage du SDK et le temps annoncé par le serveur figurent séparément dans <code>summary.json</code>. Le contrôle <code>RETURN size(range(0, $last))</code> calcule la même cardinalité avec un petit paramètre.</p>'''+table(['Maps','Payload (Mio)','C : total ms','Rust : total ms','Rust / C','Essais'],parameter_rows)+'''
<h2>Suite historique complète</h2>'''+table(['Moteur','Cas réussis','Durée des cas (s)','Erreurs imprimées'],suite_rows)+'''
<p>Les 21 cas opt-in couvrent débit, concurrence, charge soutenue, tailles de lots, limites, relations et parcours. Leur métrique « mémoire de lot » est une estimation superficielle d’objets Python ; elle ne mesure pas la RAM du serveur. Les premières exécutions avec les points d’entrée par défaut sont conservées en <code>suite-*-default.*</code>, mais exclues des tableaux : les images y choisissaient 18 threads pour C et 2 pour Rust.</p>
<h2>Portée et reproductibilité</h2><ul><li>Ce sont des mesures locales, sur un hôte partagé. Trois essais constituent une petite série ; les min–max ne sont pas des intervalles de confiance.</li><li>Les latences d’ingestion portent sur un lot ; les débits sont en documents par seconde. Les latences de lecture/mise à jour sont par opération.</li><li>Les contrôles sans écriture isolent la voie des paramètres ; leur interprétation ne remplace pas un profil CPU du serveur.</li><li>Les graphes sont neufs, dans des conteneurs isolés. Aucune migration, persistance après redémarrage ou réplication n’est évaluée.</li><li>La contribution reste locale : aucun push ni PR avant le 30 octobre 2026, Europe/Madrid.</li></ul>
<p>Données : <a href="summary.json">résumé JSON</a>, <a href="c-realistic.jsonl">mesures C</a>, <a href="rust-realistic.jsonl">mesures Rust</a>, <a href="c-parse.jsonl">sondes C</a>, <a href="rust-parse.jsonl">sondes Rust</a>. Reproduction : <a href="benchmark.py">harness</a> et <a href="perf_capture.py">capture pytest</a>. Journaux : <a href="suite-c.log">suite C</a> / <a href="suite-rust.log">suite Rust</a>.</p>
</html>'''
(ROOT/'rapport.html').write_text(document)
from add_diagnosis import apply
apply(ROOT)
print((ROOT/'summary.json').read_text())
