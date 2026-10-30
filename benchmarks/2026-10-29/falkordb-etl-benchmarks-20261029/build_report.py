"""Render the checked campaign as standalone figures and a self-contained report."""

import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from summarize import build,read_jsonl

ROOT=Path(__file__).parent
SUMMARY=build()
LABELS={'c':'C 4.22.3','rust':'Rust 6.0.3','edge':'Rust edge · #3067'}
COLORS={'c':'#2764b5','rust':'#bf5b22','edge':'#27806b'}
KINDS={'point':'Identité','one_hop':'1 saut','two_hops':'2 sauts','range_sort':'Filtre + tri','group_count':'Agrégation'}
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})


def value(engine,section,phase,field):
    return SUMMARY['engines'][engine][section][phase][field]


def err(records):
    return [[r['median']-r['min'] for r in records],[r['max']-r['median'] for r in records]]


fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
for index,engine in enumerate(LABELS):
    offset=(index-1)*.24
    values=[value(engine,'ingestion',phase,'documents_per_second') for phase in ['initial','mixed']]
    axes[0].bar([offset,1+offset],[r['median'] for r in values],width=.22,color=COLORS[engine],label=LABELS[engine])
    axes[0].errorbar([offset,1+offset],[r['median'] for r in values],yerr=err(values),fmt='none',color='#333',capsize=3)
    values=[SUMMARY['engines'][engine]['reads']['mixed']['kinds'][kind]['p95_ms'] for kind in KINDS]
    axes[1].bar([i+offset for i in range(5)],[r['median'] for r in values],width=.22,color=COLORS[engine],label=LABELS[engine])
    axes[1].errorbar([i+offset for i in range(5)],[r['median'] for r in values],yerr=err(values),fmt='none',color='#333',capsize=3)
axes[0].set_xticks([0,1],['100k documents neufs','100k : mises à jour + ajouts\navec lectures concurrentes'])
axes[0].set(ylabel='Documents source / seconde',title='Pipeline GraFlo complète · CSV + JSONL')
axes[1].set_xticks(range(5),list(KINDS.values()))
axes[1].set(ylabel='Latence p95 (ms)',title='Lectures pendant la seconde ingestion')
for ax in axes:ax.grid(axis='y',alpha=.2);ax.legend(fontsize=8)
fig.suptitle('Médianes de 3 essais · barres min–max · mêmes ressources · 29 octobre 2026')
fig.savefig(ROOT/'debit-latences.png',dpi=180);fig.savefig(ROOT/'debit-latences.svg');plt.close(fig)

fig,axes=plt.subplots(1,2,figsize=(12,4.4),layout='constrained')
for index,engine in enumerate(LABELS):
    offset=(index-1)*.24
    for ax,field,title in [(axes[0],'server_rss_peak_bytes','Serveur : pic RSS observé'),
                           (axes[1],'client_cgroup_peak_sampled_bytes','Client complet : pic cgroup observé')]:
        records=[value(engine,'resources',phase,field) for phase in ['initial','mixed']]
        vals=[r['median']/2**20 for r in records]
        errors=[[v/2**20 for v in side] for side in err(records)]
        ax.bar([offset,1+offset],vals,width=.22,color=COLORS[engine],label=LABELS[engine])
        ax.errorbar([offset,1+offset],vals,yerr=errors,fmt='none',color='#333',capsize=3)
        ax.set_xticks([0,1],['Ingestion initiale','Ingestion avec lectures'])
        ax.set(ylabel='Mio',title=title);ax.grid(axis='y',alpha=.2);ax.legend(fontsize=8)
fig.suptitle('Mémoire réelle · échantillonnage cible 100 ms · client incluant 4 lecteurs en charge mixte')
fig.savefig(ROOT/'memoire.png',dpi=180);fig.savefig(ROOT/'memoire.svg');plt.close(fig)

fig,axes=plt.subplots(3,1,figsize=(12,8),layout='constrained',sharex=True)
for ax,engine in zip(axes,LABELS):
    trial=SUMMARY['trials'][engine][1]
    rows=read_jsonl(ROOT/f'{engine}-trial-2/memory.jsonl')
    origin=trial['initial']['started']
    xs=[r['time']-origin for r in rows]
    ax.plot(xs,[r['server_rss']['VmRSS']/2**20 for r in rows],label='RSS serveur',color='#2764b5')
    ax.plot(xs,[r['client_cgroup']['memory_current']/2**20 for r in rows],label='Cgroup client + lecteurs',color='#bf5b22')
    ax.plot(xs,[r['ingester_rss']['VmRSS']/2**20 for r in rows],label='RSS ingesteur seul',color='#777',linestyle=':')
    for phase,color in [('initial','#dce9f9'),('mixed','#dcefe5')]:
        ax.axvspan(trial[phase]['started']-origin,trial[phase]['ended']-origin,color=color,alpha=.7)
    ax.set(title=LABELS[engine]+' · essai 2',ylabel='Mio');ax.grid(alpha=.15)
axes[0].legend(fontsize=8,ncol=3)
axes[-1].set_xlabel('Secondes depuis le début de l’ingestion initiale · bleu : ingestion initiale ; vert : ingestion mixte')
fig.suptitle('Évolution de la mémoire · validations et baselines visibles entre les ingestions')
fig.savefig(ROOT/'chronologie.png',dpi=180);fig.savefig(ROOT/'chronologie.svg');plt.close(fig)


def number(v,d=2):
    return f'{v:,.{d}f}'.replace(',','\u202f').replace('.',',')


def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(h))+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows)+'</tbody></table>'


def figure(name):
    svg=(ROOT/(name+'.svg')).read_text()
    return '<figure><svg'+svg.split('<svg',1)[1]+'</figure>'


overview=[];components=[];reads=[];memory=[]
for engine,label in LABELS.items():
    data=SUMMARY['engines'][engine]
    overview.append([label,*[number(data['ingestion'][phase]['seconds']['median']) for phase in ['initial','mixed']],
        *[number(data['ingestion'][phase]['documents_per_second']['median'],0) for phase in ['initial','mixed']],
        number(data['reads']['mixed']['achieved_qps']['median'],1)])
    for phase,name in [('initial','Initiale'),('mixed','Avec lectures')]:
        components.append([label,name,*[number(data['ingestion'][phase]['components'][kind]['median']) for kind in ['source_read','cast','write']]])
        resource=data['resources'][phase]
        memory.append([label,name,*[number(resource[field]['median']/2**20,1) for field in ['server_rss_peak_bytes','server_cgroup_peak_sampled_bytes','client_cgroup_peak_sampled_bytes','client_anon_peak_bytes']],
            number(resource['server_cpu_average_cores']['median'],2),number(resource['client_cpu_average_cores']['median'],2)])
    for kind,kind_label in KINDS.items():
        reads.append([label,kind_label,*[number(data['reads'][phase]['kinds'][kind]['p95_ms']['median'],2) for phase in ['idle','mixed','post_idle']],
                      number(data['reads']['mixed']['kinds'][kind]['p99_ms']['median'],2)])

document='''<!doctype html><html lang="fr"><meta charset="utf-8"><title>GraFlo / FalkorDB — ETL et lectures concurrentes</title>
<style>body{font:16px/1.6 system-ui,sans-serif;color:#192738;background:#fcfcfd;max-width:1200px;margin:36px auto;padding:0 24px}h1,h2{line-height:1.2}h2{margin-top:38px}table{border-collapse:collapse;width:100%;font-size:14px;margin:18px 0}th,td{padding:9px 10px;border-bottom:1px solid #dce2eb;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#eaf0f8}figure{margin:24px 0}figure svg{width:100%;height:auto}.note{background:#eef3fa;border-left:4px solid #2764b5;padding:16px 22px}code{background:#edf1f7;padding:2px 5px;border-radius:4px}a{color:#245da8}</style>
<h1>GraFlo : ingestion complète et lectures concurrentes</h1>
<p>Campagne locale du 29 octobre 2026. C 4.22.3, Rust 6.0.3 et image Rust de développement contenant le correctif #3067. Trois essais neufs par moteur ; l’ordre des moteurs tourne entre les essais. Ce protocole évalue une configuration précise du connecteur, sans prétendre mesurer le débit maximal des moteurs.</p>
<div class="note"><b>Charge.</b> Une première ingestion lit 100 000 documents : moitié CSV, moitié JSONL. Cinq transformations fonctionnelles et une étape de projection, deux identités composites, 1 000 catégories et une relation par document. La seconde ingestion lit 100 000 documents : 50 000 mises à jour et 50 000 ajouts. Graphe final : 150 000 items, 1 000 catégories et 150 000 relations.</div>
<p>Chaque serveur dispose de 2 CPU et 2 Gio, avec 2 threads et 2 threads OpenMP. Le client dispose de 2 autres CPU et 2 Gio, partagés entre la pipeline, le suivi mémoire et les quatre processus lecteurs. Lots de 1 000, casting dans un processus, un lot et une opération DB à la fois ; prélecture de deux lots.</p>
<h2>Résultats de l’ingestion</h2>'''+table(['Moteur','Initiale (s)','Avec lectures (s)','Initiale (docs/s)','Avec lectures (docs/s)','Lectures atteintes (req/s)'],overview)+figure('debit-latences')+'''
<p>Les durées incluent la lecture et le décodage des fichiers, les transformations, le casting et les écritures. Elles excluent la création du schéma, le lancement des processus, l’échauffement, les validations et PROFILE. Le second chargement mélange mises à jour et ajouts ; ses durées ne mesurent donc pas le seul coût de la concurrence par rapport au premier chargement.</p>
<h2>Où passe le temps ?</h2>'''+table(['Moteur','Ingestion','Lecture/décodage cumulé (s)','Casting cumulé (s)','DBWriter.write cumulé (s)'],components)+'''
<p>Les composants sont chronométrés autour des méthodes réelles de GraFlo, sans modifier leur résultat. DBWriter.write comprend la préparation des écritures, leur attente et leur exécution ; ce n’est pas le seul temps serveur. La prélecture peut chevaucher le casting ou les écritures. De plus, les médianes des composants ne proviennent pas forcément du même essai : ces colonnes ne sont pas une partition additive du temps total.</p>
<h2>Latences de lecture</h2>
<p>Quatre lecteurs, chacun plafonné à 25 requêtes/s avec au plus une requête en vol, visent 100 requêtes/s au total. Les cinq types sont répartis également. Deux secondes d’échauffement sont exclues. Baseline avant ingestion sur 100 000 items pendant dix secondes, lectures pendant le chargement, puis baseline sur 150 000 items pendant dix secondes. Le jeu de points d’entrée porte sur 10 000 items préexistants non modifiés ; les parcours traversent des catégories dont les effectifs augmentent de 100 à 150.</p>'''+table(['Moteur','Requête','p95 avant (ms)','p95 pendant (ms)','p95 après (ms)','p99 pendant (ms)'],reads)+'''
<p>Chaque cellule est la médiane des quantiles calculés séparément sur les trois essais. Toutes les latences individuelles, le retard de programmation des lecteurs et les débits atteints sont conservés. Cette charge plafonnée ne recherche pas le point de saturation. Une requête commencée pendant l’ingestion est retenue même si elle termine après celle-ci.</p>
<h2>Mémoire et CPU</h2>'''+figure('memoire')+table(['Moteur','Ingestion','RSS serveur (Mio)','Cgroup serveur (Mio)','Cgroup client (Mio)','Anon client (Mio)','CPU serveur (cœurs)','CPU client (cœurs)'],memory)+'''
<p>Les valeurs mémoire sont les médianes des pics observés par essai pendant les fenêtres mesurées. Échantillonnage nominal de 100 ms ; les intervalles réels figurent dans summary.json. RSS et cgroup sont des mesures différentes : le cgroup inclut aussi caches de fichiers et mémoire du noyau ; l’anonyme du client est fourni séparément. Le client en charge mixte comprend les quatre lecteurs. Les HWM et pics cgroup de toute la vie du conteneur sont conservés à part, car ils incluent les validations intégrales.</p>'''+figure('chronologie')+'''
<h2>Exactitude et portée</h2>
<p>'''+str(SUMMARY['completed_trials'])+' essais terminés ; '+number(SUMMARY['source_records_processed'],0)+' documents source lus et castés ; '+number(SUMMARY['read_queries_including_warmup'],0)+' lectures vérifiées, échauffement inclus ; <b>'+str(SUMMARY['read_failures'])+''' erreur de lecture</b>. Après chaque ingestion, toutes les propriétés de chaque item et les extrémités de chaque relation sont comparées aux valeurs attendues. Les empreintes canoniques sont identiques sur tous les essais et moteurs. Les deux contraintes uniques sont opérationnelles et les index attendus sont présents.</p>
<ul><li>Hôte ARM64 OrbStack partagé ; les CPU sont épinglés mais ne sont pas réservés face aux autres activités.</li><li>Les caches du système de fichiers ne sont pas purgés : ceci ne mesure pas les performances d’un disque à froid.</li><li>Une seule configuration de taille de lots et de parallélisme est évaluée. Les index et le graphe font partie du protocole ; ces résultats ne classent pas tous les usages.</li><li>Le graphe grandit pendant la charge mixte. Les baselines avant et après permettent de voir les deux tailles, sans isoler tous les facteurs.</li><li>L’image edge est figée par digest et reliée au correctif amont #3067 ; elle reste une image de développement.</li><li>Persistance, panne brutale, restauration et migration C → Rust ne sont pas évaluées ici.</li><li>Tout reste local. Aucun push ni PR avant le 30 octobre 2026, Europe/Madrid.</li></ul>
<p><a href="protocol.json">Protocole et images exactes</a> · <a href="summary.json">Résultats détaillés</a> · <a href="manifest.json">Manifeste</a> · <a href="scenario.py">Données et requêtes</a> · <a href="benchmark.py">Instrumentation</a> · <a href="reader.py">Lecteurs</a> · <a href="run_campaign.py">Reproduction Docker</a>. Les sous-dossiers ENGINE-trial-N contiennent les mesures mémoire, chaque requête, les plans PROFILE, les validations et les résultats ; les fichiers pilot-* et bootstrap-* sont exclus.</p></html>'''
max_gap=max(r['resource_metrics'][phase]['max_sampling_gap_seconds'] for rows in SUMMARY['trials'].values() for r in rows for phase in ['initial','mixed'])
document=document.replace('Échantillonnage nominal de 100 ms ; les intervalles réels figurent dans summary.json.',
    'Échantillonnage cible de 100 ms, avec des pauses observées allant jusqu’à '+number(max_gap,2)+' s. Des pics transitoires peuvent donc être manqués ; les intervalles réels et les maxima du noyau sur toute la vie du conteneur figurent dans summary.json.')
findings='''<h2>Ce que montre cette charge</h2><ul>
<li>Le casting représente environ <b>59 à 75 %</b> de la durée d’ingestion initiale : 15,5 à 16,1 secondes médianes. Dans cette configuration à un processus de casting, la pipeline côté client compte fortement dans le débit total.</li>
<li>Les durées initiales médianes sont de <b>27,18 s en C</b>, <b>21,14 s en Rust 6.0.3</b> et <b>20,85 s sur edge</b>. Les min–max figurent sur les graphiques et dans le JSON ; ils décrivent trois essais locaux sur un hôte partagé.</li>
<li>La p95 de lecture par identité pendant l’ingestion vaut <b>8,72 ms en C</b>, <b>2,75 ms en Rust 6.0.3</b> et <b>3,12 ms sur edge</b>. Le débit réellement atteint varie de 85 à 100 requêtes/s selon l’essai ; les valeurs ne constituent pas une comparaison à débit strictement identique ni un test de saturation.</li>
<li>Les pics RSS serveur observés pendant l’ingestion mixte, médians sur trois essais, sont d’environ <b>154 / 181 / 188 Mio</b> respectivement. Les valeurs du client incluent ses lecteurs et ses caches selon la mesure utilisée.</li>
</ul>'''
document=document.replace('<h2>Résultats de l’ingestion</h2>',findings+'<h2>Résultats de l’ingestion</h2>')
document=document.replace('<p><a href="protocol.json">Protocole et images exactes</a>',
    '<p>Un essai incomplet a été exclu et rejoué après une erreur de fichier de contrôle sur le volume partagé. Six lectures de contrôle ont ensuite été retentées, hors chronométrage des requêtes. Les requêtes, données, ressources et temporisations de charge sont inchangées ; les journaux et le changement sont conservés dans excluded/ et protocol.json.</p><p><a href="protocol.json">Protocole et images exactes</a>')
(ROOT/'rapport.html').write_text(document)
readme='Campagne ETL GraFlo / FalkorDB du 29 octobre 2026\n\n9 essais : trois par moteur C 4.22.3, Rust 6.0.3 et edge corrigé #3067.\n'
readme+='100 000 documents source CSV/JSONL puis 100 000 (50 000 mises à jour, 50 000 ajouts).\nGraphe final par essai : 150 000 items, 1 000 catégories et 150 000 relations.\n\n'
for row in overview:readme+=' | '.join(map(str,row))+'\n'
readme+='\nColonnes : moteur ; durée initiale s ; durée avec lectures s ; docs/s initial ; docs/s avec lectures ; requêtes de lecture/s atteintes.\n\n'
readme+=f"Lectures vérifiées : {SUMMARY['read_queries_including_warmup']}, erreurs : {SUMMARY['read_failures']}. Empreintes de toutes les propriétés identiques entre moteurs et essais.\n"
readme+='\nRapport autonome : rapport.html. Détails numériques : summary.json. Protocole : protocol.json.\nFigures : debit-latences.png/svg, memoire.png/svg, chronologie.png/svg.\nReproducteurs : scenario.py, benchmark.py, reader.py, run_campaign.py.\n'
readme+='\nMesures locales sur hôte partagé, lots de 1 000 ; aucune conclusion générale de supériorité d’un moteur. Les durées de lecture/casting/DBWriter peuvent se chevaucher via la prélecture. La seconde ingestion diffère de la première en contenu ; la différence de durée ne mesure pas le seul effet des lectures.\n'
readme+=f'\nLe casting représente environ 59 à 75 % du temps initial dans cette configuration. Les lectures visent 100 req/s, mais atteignent 85 à 100 selon l’essai. Les pics mémoire par phase sont échantillonnés ; le plus grand intervalle de mesure observé atteint {max_gap:.2f} s. Les pics transitoires peuvent être manqués et les maxima du noyau sont conservés séparément.\n'
readme+='\nUn essai incomplet est exclu dans excluded/ après un ENOENT sur le fichier de synchronisation. Le correctif ne change pas les requêtes ni leur chronométrage ; six lectures de contrôle ont été retentées hors chronométrage. Les premiers essais réussis sont conservés, comme décrit dans protocol.json.\n'
readme+='\nPilotes et tentative de démarrage Docker par sous-processus refusée dans l’environnement sont conservés sous pilot-* et bootstrap-* et exclus. La campagne mesurée utilise des invocations Docker directes autorisées, sans changer le protocole.\nAucun push ni PR avant le 30 octobre 2026 Europe/Madrid.\n'
(ROOT/'README.txt').write_text(readme)
print(ROOT/'rapport.html')
