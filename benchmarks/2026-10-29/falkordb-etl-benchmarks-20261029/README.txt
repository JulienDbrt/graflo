Campagne ETL GraFlo / FalkorDB du 29 octobre 2026

9 essais : trois par moteur C 4.22.3, Rust 6.0.3 et edge corrigé #3067.
100 000 documents source CSV/JSONL puis 100 000 (50 000 mises à jour, 50 000 ajouts).
Graphe final par essai : 150 000 items, 1 000 catégories et 150 000 relations.

C 4.22.3 | 27,18 | 29,13 | 3 679 | 3 433 | 92,6
Rust 6.0.3 | 21,14 | 22,04 | 4 730 | 4 537 | 94,9
Rust edge · #3067 | 20,85 | 26,31 | 4 797 | 3 801 | 89,4

Colonnes : moteur ; durée initiale s ; durée avec lectures s ; docs/s initial ; docs/s avec lectures ; requêtes de lecture/s atteintes.

Lectures vérifiées : 41383, erreurs : 0. Empreintes de toutes les propriétés identiques entre moteurs et essais.

Rapport autonome : rapport.html. Détails numériques : summary.json. Protocole : protocol.json.
Figures : debit-latences.png/svg, memoire.png/svg, chronologie.png/svg.
Reproducteurs : scenario.py, benchmark.py, reader.py, run_campaign.py.

Mesures locales sur hôte partagé, lots de 1 000 ; aucune conclusion générale de supériorité d’un moteur. Les durées de lecture/casting/DBWriter peuvent se chevaucher via la prélecture. La seconde ingestion diffère de la première en contenu ; la différence de durée ne mesure pas le seul effet des lectures.

Le casting représente environ 59 à 75 % du temps initial dans cette configuration. Les lectures visent 100 req/s, mais atteignent 85 à 100 selon l’essai. Les pics mémoire par phase sont échantillonnés ; le plus grand intervalle de mesure observé atteint 2.52 s. Les pics transitoires peuvent être manqués et les maxima du noyau sont conservés séparément.

Un essai incomplet est exclu dans excluded/ après un ENOENT sur le fichier de synchronisation. Le correctif ne change pas les requêtes ni leur chronométrage ; six lectures de contrôle ont été retentées hors chronométrage. Les premiers essais réussis sont conservés, comme décrit dans protocol.json.

Pilotes et tentative de démarrage Docker par sous-processus refusée dans l’environnement sont conservés sous pilot-* et bootstrap-* et exclus. La campagne mesurée utilise des invocations Docker directes autorisées, sans changer le protocole.
Aucun push ni PR avant le 30 octobre 2026 Europe/Madrid.
