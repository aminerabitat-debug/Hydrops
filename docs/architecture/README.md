# HydroPS — Phase 0 : Architecture technique et modèle de données

Ce dossier fixe les décisions d'architecture avant tout développement de fonctionnalité. Il répond point par point à la commande de Phase 0 et sert de référence pour tous les lots ultérieurs (`docs/functional-spec/cahier-des-charges-v1.md` §21).

Rien ici n'implémente une fonctionnalité métier (hydraulique, optimisation, CAPEX/OPEX...) : c'est la charpente sur laquelle les Lots 1 à 7 viendront s'accrocher.

## Sommaire

1. [Architecture technique du système](01-architecture-systeme.md)
2. [Arborescence du repository](02-arborescence-repository.md)
3. [Modèle de données](03-modele-donnees.md)
4. [Format de fichier `.hydrops`](04-format-hydrops.md)
5. [API backend](05-api.md)
6. [Stratégie SIG / DEM](06-sig-dem.md)
7. [Stratégie de calcul hydraulique et d'optimisation](07-calcul-hydraulique-optimisation.md)
8. [Sessions et confidentialité](08-sessions-confidentialite.md)
9. [Stratégie de tests pour les calculs d'ingénierie](09-strategie-tests.md)

## Décisions clés (résumé exécutif)

| Sujet | Décision Phase 0 | Justification |
|---|---|---|
| Persistance projet | Le fichier `.hydrops` (ZIP local) est la **seule** source de vérité. Rien côté serveur n'est durable pour les données projet. | [cdc §3](../functional-spec/cahier-des-charges-v1.md#3-confidentialité-et-fichier-projet), V1-10 |
| PostgreSQL/PostGIS | Deux schémas logiques distincts : `catalog` (durable, données de référence non confidentielles : diamètres, coûts, matériaux) et `session` (éphémère, TTL, copie de travail du projet ouvert). | Résout l'ambiguïté "PostGIS comme espace temporaire" sans perdre la traçabilité des bibliothèques (§15) |
| Moteur de calcul | Package Python pur (`hydrops-engine`), sans I/O, déterministe, versionné indépendamment de l'API. | Exigence de déterminisme et de traçabilité (§17, V1-11) |
| Jobs longs | File d'attente asynchrone (`arq` + Redis) pour calcul et optimisation ; polling/SSE pour la progression. | L'optimisation pompée est itérative et peut être longue sur de grands réseaux |
| Cartographie | MapLibre GL JS (open-source, pas de dépendance commerciale bloquante pour un futur SaaS international) | Compatible SaaS international, §1 |
| DEM | Copernicus GLO-30 comme source par défaut, service de cache de tuiles dédié, interface remplaçable | Point ouvert §20, tranché avec une recommandation réversible |
| Synchronisation carte/profil/table | Entièrement côté client (bus de sélection partagé), aucun aller-retour serveur nécessaire | V1-02 |
| Format d'échange interne | JSON Schema (`packages/hydropack/schema`) comme source unique de vérité, génère les types TypeScript et les modèles Pydantic | Évite la divergence front/back sur la structure `.hydrops` |
