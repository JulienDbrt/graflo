Diagnostic du ralentissement FalkorDB Rust 6.0.3 — 29 octobre 2026

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
Rust 6.0.3 : médiane 2588.53 ms ;
Rust edge corrigé : médiane 38.47 ms ;
gain 67.29 fois. Le profil edge produit 0 ligne pending.
Edge 50 000 créations : médiane 203.96 ms.

Correctif amont déjà fusionné : https://github.com/FalkorDB/FalkorDB/pull/3067
Commit b47d6d6a3c563818fec2f2655ad6f92583e2a62f
Fusion 2026-10-28T23:01:57Z (29 octobre, 00:01:57 Europe/Madrid).
Le correctif fait toutes les recherches MERGE avant de créer les sommets.
L'image officielle edge testée est reliée au commit par les journaux de
promotion CI, conservés en extrait dans upstream.json :
falkordb/falkordb-server@sha256:3d08d1a1536394210d7f435bcfc777a58ba9d21f58f23cf2b86918772028b941

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
