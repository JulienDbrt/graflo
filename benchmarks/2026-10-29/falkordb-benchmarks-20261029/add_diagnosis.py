"""Attach the subsequent native MERGE diagnosis to the original benchmark report."""

import json
from pathlib import Path


def apply(root):
    path=root/'diagnosis.json'
    if not path.exists():
        return
    diagnosis=json.loads(path.read_text())
    summary=json.loads((root/'summary.json').read_text())
    summary['diagnosis']=diagnosis
    summary['findings']['interpretation']=diagnosis['root_cause']
    (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    report=(root/'rapport.html').read_text()
    report=report.replace('Le chemin d’écriture doit être profilé pour localiser la cause exacte.',
        'Le profil natif a depuis identifié un croisement quasi quadratique dans MERGE ; voir le diagnostic ci-dessous.')
    report=report.replace('Les contrôles sans écriture isolent la voie des paramètres ; leur interprétation ne remplace pas un profil CPU du serveur.',
        'Les contrôles sans écriture isolent la voie des paramètres. Le diagnostic complémentaire utilise PROFILE, opérateur par opérateur, et le code du moteur.')
    if 'id="diagnosis-merge"' not in report:
        section='''<section id="diagnosis-merge"><h2>Cause identifiée : MERGE dans Rust 6.0.3</h2>
<p>Reproduction avec le SDK FalkorDB seul, sans GraFlo. Sur un graphe neuf, le moteur crée un bloc interne de 1 024 sommets avant de chercher les correspondances du suivant. <code>Include Pending</code> croise les sommets créés avec les nouvelles entrées : <b>44 974 080 lignes intermédiaires pour 10 000 nouveaux sommets</b>, toutes éliminées par le filtre. Ce travail quasi quadratique explique la chute. CREATE et MERGE sur des sommets déjà présents restent rapides.</p>
<p>Le correctif <a href="https://github.com/FalkorDB/FalkorDB/pull/3067">FalkorDB #3067</a>, fusionné le 29 octobre à 00:01 Europe/Madrid, effectue toutes les recherches avant les créations. L’image officielle de développement correspondante a été vérifiée par digest et par les journaux de promotion CI. Avec la même requête SDK, le même index et les mêmes ressources, trois essais successifs donnent :</p>
<table><thead><tr><th>10 000 créations MERGE · SDK seul</th><th>Médiane</th><th>Lignes Include Pending</th></tr></thead><tbody>
<tr><td>Rust 6.0.3</td><td>2 588,53 ms</td><td>44 974 080</td></tr>
<tr><td>Rust edge corrigé</td><td>38,47 ms</td><td>0</td></tr></tbody></table>
<p>Soit environ <b>67 fois moins de temps</b> dans cette sonde. Ces durées SDK ont un protocole distinct du débit d’ingestion GraFlo ci-dessus. Le reproducer amont de l’erreur de cardinalité selon la frontière des blocs est aussi confirmé sur 6.0.3 et corrigé sur edge ; les doublons conservent leur identité.</p>
<figure>'''+(root/'diagnostic.svg').read_text().split('<svg',1)[-1].join(['<svg',''])+'''</figure>
<p><b>Portée :</b> edge est une image de développement, pas une version stable validée par toute notre suite. La recommandation <code>--batch-size 1000</code> reste mesurée pour 6.0.3. Détails, profils natifs et reproducteur : <a href="../falkordb-investigation-20261029/README.txt">diagnostic complet</a> ; <a href="diagnosis.json">résumé JSON du diagnostic</a>.</p></section>'''
        report=report.replace('<h2>Ingestion et taille des paramètres</h2>',section+'<h2>Ingestion et taille des paramètres</h2>')
    (root/'rapport.html').write_text(report)


if __name__=='__main__':
    apply(Path(__file__).parent)
