Benchmarks FalkorDB du 29 octobre 2026

Résultats et graphiques : rapport.html (autonome), comparaison.png/svg, latences.png/svg.
Résumé numérique : summary.json. Protocole exact : protocol.json.
Sources reproductibles : benchmark.py et perf_capture.py.

21/21 cas de performance passent sur chaque version. Aucun message Errors non nul ni FAIL dans leurs sorties. Ces suites incluent les 21 cas ignorés dans la validation précédente.

Mesures complémentaires : 84 essais d'ingestion et d'opérations, plus 44 sondes sans écriture. Données et latences individuelles : c-realistic.jsonl, rust-realistic.jsonl, c-parse.jsonl, rust-parse.jsonl.

Résultats avec schéma défini (médianes de 3 essais, 10 000 documents par essai)
Lot       C docs/s      Rust docs/s
1            6 237            8 503
100        124 416          125 717
1 000      147 638          138 199
10 000     152 115            3 408

Sur Rust, passer de 10 000 à 1 000 par lot améliore ici le débit de 40,55 fois. Le réglage est documenté comme point de départ à mesurer sur la charge réelle, pas comme optimum universel.

Sonde sans écriture : RETURN size($data), 50 000 maps : C ~41,6 ms, Rust ~90,1 ms. L'écriture du lot de 50 000 dans la suite historique prend C ~0,19 s, Rust ~71,82 s. Le parsing seul n'explique pas cet écart. Il faut profiler le chemin d'écriture pour localiser précisément la cause.

Environnement : Linux aarch64/OrbStack, 2 CPU et 2 Gio par moteur, 2 CPU distincts et 2 Gio pour le client, 2 threads et 2 threads OpenMP. Exécutions successives, sans concurrence entre les deux moteurs ; l'hôte reste partagé avec d'autres activités. Les premières mesures avec les points d'entrée par défaut sont conservées dans suite-*-default.*, mais écartées du comparatif car les moteurs choisissaient 18 et 2 threads respectivement.

La métrique mémoire du test historique est superficielle (objets Python), pas une mesure de RAM serveur. Les tests ne mesurent pas une migration, la persistance ou la réplication. Ces débits sont ceux du connecteur direct, sans lecture/transformations de la pipeline ETL complète.

Le code testé reste 3230dfb. Une note de documentation a été ajoutée dans un second commit local. Aucun changement du comportement du connecteur n'est intervenu pendant ces benchmarks. Aucun push et aucune PR avant le 30 octobre 2026 ; aucune publication future programmée.

Diagnostic complémentaire : cause confirmée dans MERGE de Rust 6.0.3 (croisement des sommets pending entre blocs de 1 024). Le correctif amont FalkorDB #3067 est déjà fusionné ; l’image edge correspondante ramène la sonde SDK de 10 000 créations de 2 588,53 ms à 38,47 ms (médianes de trois essais, ~67 fois). Aucun changement du connecteur nécessaire pour cette cause. Détails : ../falkordb-investigation-20261029/README.txt ; profils et reproduction dans ce dossier. Le rapport HTML et summary.json intègrent le diagnostic.

Campagne suivante : ingestion GraFlo complète CSV/JSONL de 100 000 documents avec relations, puis 100 000 documents avec quatre lecteurs concurrents. Rapport : ../falkordb-etl-benchmarks-20261029/rapport.html. Ce protocole diffère des appels directs au connecteur mesurés ici.
