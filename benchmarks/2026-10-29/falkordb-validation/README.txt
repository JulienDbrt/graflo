Validation FalkorDB — travail local du 28 octobre 2026

Publication : aucun push et aucune PR avant le 30 octobre 2026, Europe/Madrid.
Aucune publication effectuée. Aucun envoi futur n'est programmé.

Copie de travail : /Users/julien/graflo/falkordb-compat
Branche : feat/falkordb-c-rust-compatibility
Base : 1ee6e608c9f757e5f303b4358f331e391156cc45 (inclut #397 et #398)
Commit local : 3230dfb28d05380b5e0517ec7d6c88fc88f3fe2e

Changements
- Validation récursive des entiers signés 64 bits avant tout envoi. Les dépassements lèvent OverflowError plutôt que de subir la troncature silencieuse de 4.x.
- Les erreurs de lecture des paramètres du serveur deviennent ValueError ; les autres erreurs gardent leur type, et la cause d'origine reste disponible.
- Les flottants subnormaux sont acceptés par 4.22.3 mais restent refusés par 6.0.3. Le refus est explicite, sans conversion des valeurs ni relance de la requête.
- Défaut Docker 4.22.3, documentation et changelog concis.
- 22 nouveaux cas unitaires et 19 nouveaux cas avec base réelle. Vérification des catalogues, identités composées, contraintes sur sommets/relations et nettoyage, y compris les clés 0, 0.0 et false.

Résultats finaux
- FalkorDB 4.22.3 : 184 réussis, 21 performance ignorés, environ 3,4 s.
- FalkorDB 6.0.3 : 184 réussis, 21 performance ignorés, environ 81,6 s.
- Hors bases : 5 156 réussis, 13 ignorés, environ 24,8 s.
- Tous les hooks pre-commit passent (Ruff, formatage, ty et visualisation de l'ontologie).
- Un avertissement de dépréciation rdflib, hors de ce changement.

Les erreurs initiales de 6.0.3 sont enregistrées dans baseline-6.0.3.log/xml ; le code initial donnait 2 échecs, 163 réussites et 21 cas ignorés. Les sondes numeric-*.jsonl montrent les valeurs effectivement retournées ou refusées avant correction.

Limites observées
- Le cas existant de 50 000 sommets en un lot passe en environ 75 s sous Rust et 0,2 s sous C. Une sonde avec index préalable reste lente. Aucun correctif de performance n'est revendiqué.
- Les 21 cas de benchmark opt-in ont été exécutés le 29 octobre : 21 réussis par moteur ; voir le rapport complémentaire.
- Les contrôles portent sur des instances neuves, pas sur une migration en place ou une reprise après redémarrage.
- Les autres backends réels ne sont pas relancés ; leur code n'est pas modifié.

Préparation de publication
- Description : pr-body.txt ; titre : pr-title.txt ; patch : contribution.patch.
- Le hook local pre-push bloque avant le 30 octobre, avec core.hooksPath explicitement configuré ; push.default=nothing évite un push implicite.
- Remotes configurés : origin=growgraph/graflo (base), fork=JulienDbrt/graflo (destination future).
- Le commit local est non signé : la signature SSH configurée sur cette machine n'était pas disponible. Il peut être resigné avant publication.
- Avant publication le 30 : récupérer origin/main, vérifier l'écart avec la base ci-dessus, adapter si nécessaire puis publier sur le fork et ouvrir la PR avec le texte préparé.

Environnement exact et digests : validation.json.
Journaux : final-4.22.3.log/xml, final-6.0.3.log/xml, offline.log/xml, pre-commit.log.

Complément du 29 octobre : tous les 21 benchmarks opt-in passent sur chaque moteur. Le protocole et les mesures répétées sont dans /Users/julien/graflo/falkordb-benchmarks-20261029/rapport.html. Les limites ci-dessus concernant les benchmarks non exécutés sont donc levées. Le ralentissement des gros lots reste observé ; --batch-size 1000 est documenté.
Nouveau HEAD local (documentation uniquement) : a20d2459d360e70e3571f14c5353ef0edfb517ed

Campagne ETL complète du 29 octobre : ../falkordb-etl-benchmarks-20261029/rapport.html et protocol.json. Neuf essais (trois par moteur), 1,8 million de documents source CSV/JSONL, 41 383 lectures vérifiées, aucune erreur de requête. Toutes les propriétés et toutes les extrémités des relations sont vérifiées après chaque ingestion ; les empreintes sont identiques sur les neuf essais. Graphe final par essai : 150 000 items, 1 000 catégories, 150 000 relations. CPU et mémoire réels sont enregistrés. Aucun changement du connecteur et aucun push.
