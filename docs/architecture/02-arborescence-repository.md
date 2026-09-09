# 2. Arborescence du repository

Monorepo. Choix justifié par le fait que `hydrops-engine` (calcul) et `hydropack` (format `.hydrops`) doivent rester des dépendances internes partagées, versionnées et testées indépendamment de l'API — pas des dossiers noyés dans un projet FastAPI monolithique.

```
Adduction/
├── apps/
│   ├── web/                                # Frontend React + TypeScript (SPA)
│   │   ├── src/
│   │   │   ├── app/                        # Shell applicatif : layout, menus, routing, barre d'état
│   │   │   ├── features/                   # Un dossier par fonctionnalité UI, aligné sur le cahier des charges
│   │   │   │   ├── project-tree/           #   arborescence projet (§4)
│   │   │   │   ├── map/                    #   carte SIG (MapLibre)
│   │   │   │   ├── profile/                #   profil en long
│   │   │   │   ├── table/                  #   table principale unique (§7)
│   │   │   │   ├── results/                #   vue résultats
│   │   │   │   ├── variants/               #   gestion des variantes
│   │   │   │   ├── structures/             #   ouvrages (§8)
│   │   │   │   ├── catalog/                #   écrans "Base de données" (§4)
│   │   │   │   └── reports/                #   export PDF/XLSX/DOCX
│   │   │   ├── entities/                   # Types + logique domaine côté client (Project, Variant, Trace...)
│   │   │   ├── shared/                     # UI kit, hooks, client API généré, utilitaires
│   │   │   ├── state/                      # Store Zustand + bus de sélection carte/profil/table
│   │   │   └── i18n/                       # fr.json / en.json, clés = codes internes stables
│   │   ├── public/
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   └── tsconfig.json
│   │
│   └── api/                                # Backend FastAPI
│       ├── hydrops_api/
│       │   ├── main.py                     # Point d'entrée ASGI
│       │   ├── routers/                    # projects, network, structures, catalog,
│       │   │                               # calculations, optimization, reports, dem, sessions
│       │   ├── services/                   # Orchestration : hydropack (de)serialize, kml_import,
│       │   │                               # dem_sampler, report_builder — pas de logique de calcul ici
│       │   ├── db/
│       │   │   ├── catalog/                # Modèles SQLAlchemy + migrations Alembic (durable)
│       │   │   └── session/                # Modèles du schéma éphémère (TTL)
│       │   ├── workers/                    # Tâches arq : calcul, optimisation, rapport, purge sessions
│       │   ├── schemas/                    # DTO Pydantic (I/O API), dérivés du JSON Schema hydropack
│       │   └── core/                       # config, sécurité/session, middlewares
│       ├── alembic/                        # Migrations du schéma `catalog` uniquement
│       └── pyproject.toml
│
├── packages/
│   ├── hydrops-engine/                     # Moteur de calcul — package Python PUR (aucune dépendance DB/HTTP)
│   │   ├── hydrops_engine/
│   │   │   ├── topology/                   # Graphe orienté arborescent, PK cumulé, ordre topologique
│   │   │   ├── hydraulics/                 # Darcy-Weisbach/Colebrook, Hazen-Williams, Swamee-Jain
│   │   │   ├── optimization/                # Gravitaire (min DN) puis pompé (CAPEX/OPEX/VAN)
│   │   │   ├── economics/                  # CAPEX, OPEX, réinvestissement, valeur résiduelle, VAN
│   │   │   ├── trench/                     # Tranchée type et métrés (§11)
│   │   │   └── validation/                 # Alertes Information / Avertissement / Bloquant (§17)
│   │   ├── tests/                          # Suite déterministe (voir 09-strategie-tests.md)
│   │   └── pyproject.toml
│   │
│   ├── hydropack/                          # Format .hydrops — schéma unique partagé front/back
│   │   ├── schema/                         # JSON Schema (source de vérité, voir 04-format-hydrops.md)
│   │   ├── python/                         # (Dé)sérialiseur Python (utilisé par apps/api)
│   │   └── package.json / pyproject.toml
│   │
│   └── shared-types/                       # Types TypeScript générés (OpenAPI + JSON Schema hydropack)
│
├── docs/
│   ├── architecture/                       # Ce dossier (Phase 0)
│   ├── functional-spec/                    # Cahier des charges versionné + matrice de traçabilité V1-xx
│   └── testing/                            # Plans de test détaillés par module (référence croisée avec 09)
│
├── infra/
│   ├── docker/                             # Dockerfiles + docker-compose.yml (web, api, worker, redis, postgis)
│   └── ci/                                 # Pipelines (lint, tests unitaires engine, build)
│
├── scripts/                                # Scripts de dev (seed du catalog, génération de types, etc.)
└── README.md
```

## Règles de dépendance (à faire respecter dès le Lot 1)

- `hydrops-engine` ne doit **jamais** importer quoi que ce soit de `apps/api` ou d'une lib DB/HTTP. Il ne connaît que des structures de données en mémoire.
- `apps/api` dépend de `hydrops-engine` et `hydropack`, jamais l'inverse.
- `apps/web` ne contient aucune logique de calcul métier ; elle affiche des `Results` produits par l'API.
- `packages/hydropack/schema` est éditée en premier lors de toute évolution du modèle de données ; les types Python (`hydropack/python`) et TypeScript (`shared-types`) en sont **générés**, jamais réécrits à la main en parallèle.
