# 1. Architecture technique du système

## 1.1 Contraintes qui pilotent la conception

Avant de décrire les composants, il faut nommer les contraintes du cahier des charges qui contredisent une architecture web "par défaut" (base de données durable côté serveur) :

- **Confidentialité forte** : "Données projet non conservées durablement côté serveur" ([cdc §1](../functional-spec/cahier-des-charges-v1.md#1-objet-et-vision)), avec purge à la déconnexion / expiration / nettoyage des orphelins (V1-10). Le fichier `.hydrops` local est explicitement désigné comme le format projet ([cdc §3](../functional-spec/cahier-des-charges-v1.md#3-confidentialité-et-fichier-projet)).
- **Déterminisme et traçabilité des calculs d'ingénierie** : mêmes entrées ⇒ mêmes résultats, et chaque résultat exporté doit rester traçable jusqu'aux hypothèses et versions de bases utilisées (§17, V1-11).
- **Synchronisation UI temps réel** entre carte, profil et table (V1-02) — un problème d'état client, pas de débit serveur.
- **Calculs potentiellement longs** : l'optimisation pompée explore un compromis CAPEX/OPEX sur diamètres commerciaux (§10) — ce n'est pas instantané sur un grand réseau.
- **Compatibilité SaaS future** sans réécriture ([cdc §1](../functional-spec/cahier-des-charges-v1.md#1-objet-et-vision)) : la frontière session/tenant doit être propre dès la V1, même si l'auth V1 reste simple.

Ces contraintes éliminent d'emblée un design "CRUD classique sur une base de données de projets" et imposent un design **fichier-centrique**, où le serveur est un exécuteur de calcul et de conversion, pas un système d'enregistrement.

## 1.2 Vue d'ensemble

```
┌───────────────────────────────────────────────────────────────────────────┐
│  CLIENT (navigateur)                                                       │
│  React + TypeScript SPA                                                    │
│  ┌───────────┐ ┌────────────┐ ┌───────────┐ ┌───────────┐ ┌─────────────┐ │
│  │ Carte     │ │ Profil     │ │ Table     │ │ Résultats │ │ Arborescence│ │
│  │ MapLibre  │ │ (canvas/D3)│ │ TanStack  │ │           │ │ projet      │ │
│  └─────┬─────┘ └─────┬──────┘ └─────┬─────┘ └─────┬─────┘ └──────┬──────┘ │
│        └─────────────┴──────┬───────┴─────────────┴──────────────┘        │
│                    Bus de sélection (Zustand) : nodeId / PK / segmentId    │
│                    Fichier .hydrops chargé en mémoire (client)             │
└───────────────────────────────────┬───────────────────────────────────────┘
                                     │ HTTPS (REST + upload/download binaire)
                                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  API (FastAPI, ASGI)                                                       │
│  routers: projects · network · structures · catalog · calculations ·      │
│           optimization · reports · dem · sessions                         │
│  ┌─────────────────────┐   ┌───────────────────────┐                      │
│  │ hydropack (dé)sér.  │   │ session manager (TTL) │                      │
│  └─────────────────────┘   └───────────────────────┘                      │
└───────┬───────────────┬───────────────┬────────────────┬──────────────────┘
        │               │               │                │
        ▼               ▼               ▼                ▼
┌───────────────┐ ┌───────────┐ ┌───────────────┐ ┌──────────────────────┐
│ hydrops-engine│ │ DEM cache │ │ Report gen.   │ │ Redis (queue + jobs) │
│ (pkg Python   │ │ (tuiles   │ │ PDF/XLSX/DOCX │ │ arq workers          │
│  pur, déter-  │ │ publiques,│ │               │ │  - calcul hydraulique│
│  ministe)     │ │ cache     │ │               │ │  - optimisation      │
└───────────────┘ │ durable)  │ └───────────────┘ │  - génération rapport│
                   └───────────┘                   └──────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  PostgreSQL / PostGIS                                                      │
│  ┌────────────────────────────┐   ┌──────────────────────────────────┐   │
│  │ schéma `catalog` (durable) │   │ schéma `session` (éphémère, TTL)  │   │
│  │ diamètres, matériaux,      │   │ copie de travail du .hydrops      │   │
│  │ coûts, classes, réservoirs │   │ ouvert, état des jobs de calcul   │   │
│  │ standards, réglages i18n   │   │ purgée à déconnexion/expiration/  │   │
│  └────────────────────────────┘   │ balayage des sessions orphelines  │   │
│                                    └──────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────────┘
```

## 1.3 Composants côté client

| Composant | Choix | Pourquoi |
|---|---|---|
| Framework | React 18 + TypeScript, build Vite | Écosystème mature, typage bout-en-bout avec l'API |
| Cartographie | MapLibre GL JS (+ tuiles vectorielles OSM ou fond neutre) | Open-source, pas de clé commerciale bloquante, style personnalisable pour tracés/nœuds/segments/ouvrages |
| Profil en long | Rendu Canvas/SVG maison (ou visx) au-dessus d'un moteur d'échelle partagé avec la table | Besoin très spécifique (terrain, HGL, hydrostatique, bandes DN/matériau/classe, multi-feuilles à l'export) — une lib de charting générique ne le couvre pas bien |
| Table unique | TanStack Table (headless) + sélecteur de colonnes par checkbox | Colonnes dynamiques avant/après calcul (§7), tri/virtualisation pour grands réseaux |
| État applicatif | Zustand : un store "projet ouvert" + un **bus de sélection** (nodeId/segmentId/PK survolé ou sélectionné) | La synchro carte/profil/table (V1-02) est un problème purement client ; aucun round-trip serveur nécessaire |
| i18n | react-i18next, clés = codes internes stables (§18) | "Preliminary Design" reste le concept interne, "APS" un libellé régional |
| Client API | Générés depuis le schéma OpenAPI de FastAPI (`openapi-typescript-codegen`) | Élimine la dérive de types front/back |

Le fichier `.hydrops` est chargé et manipulé principalement **en mémoire côté client** après ouverture ; le serveur n'en reçoit qu'une copie de travail temporaire au moment d'un calcul ou d'un export (voir §1.5 et [08-sessions-confidentialite.md](08-sessions-confidentialite.md)).

## 1.4 Composants côté serveur

### API (FastAPI)

Rôle : point d'entrée HTTP, orchestration, validation, sérialisation `.hydrops`, pas de logique métier hydraulique/économique (déléguée à `hydrops-engine`).

Routers par domaine (détail dans [05-api.md](05-api.md)) : `projects`, `network` (traces/nœuds/segments), `structures`, `catalog`, `calculations`, `optimization`, `reports`, `dem`, `sessions`.

### `hydrops-engine` — moteur de calcul

Package Python **pur** (pas d'accès DB, pas d'I/O réseau), publié comme dépendance interne versionnée (SemVer). Sous-modules : `topology` (graphe, PK, ordre topologique), `hydraulics` (Darcy-Weisbach/Colebrook, Hazen-Williams, Swamee-Jain), `optimization` (gravitaire puis pompé), `economics` (CAPEX/OPEX/VAN), `trench` (métrés), `validation` (alertes Information/Avertissement/Bloquant).

Contrat : `calculate(network_snapshot, catalog_snapshot, economic_params, options) -> Results`, une fonction pure. C'est ce qui rend le calcul **testable unitairement sans base de données ni serveur** ([09-strategie-tests.md](09-strategie-tests.md)) et **traçable** : chaque `Results` embarque la version du package et un hash des entrées (V1-11).

### Files d'attente et jobs asynchrones

`arq` (asyncio-natif, cohérent avec FastAPI, plus léger que Celery/RabbitMQ pour du V1 mono-tenant) + Redis comme broker et cache de statut de job. Jobs : calcul hydraulique, optimisation (potentiellement itérative/longue), génération de rapport PDF/XLSX/DOCX, pré-chargement de tuiles DEM. Le client interroge le statut par polling léger (ou SSE si besoin d'UX plus réactive) — pas de WebSocket nécessaire pour la V1, la synchro UI étant purement client.

### Service DEM

Couche d'accès à un fournisseur de modèle numérique de terrain global, avec cache de tuiles. Détaillé dans [06-sig-dem.md](06-sig-dem.md). Point important : les tuiles DEM sont des **données publiques de terrain**, pas des données projet — leur cache peut être durable sans contredire V1-10.

### Génération de livrables

PDF (WeasyPrint pour rapports/notes de calcul ; rendu HTML→PDF pour les planches de profil multi-feuilles), XLSX (openpyxl), DOCX (python-docx). Exécutée en job asynchrone, le résultat est streamé au client puis **supprimé côté serveur** (pas de bucket de rapports persistant en V1).

### PostgreSQL/PostGIS — deux schémas, deux régimes de rétention

C'est la clarification centrale de cette Phase 0, car le cahier des charges dit "PostgreSQL/PostGIS uniquement comme espace de travail temporaire de session" (§3) tout en demandant une "Base de données" de diamètres/coûts/matériaux/classes/bibliothèques éditable et traçable (§4, §15). Ces deux besoins ne portent pas sur la même donnée :

- **`catalog` (durable)** : diamètres standards, DI/DE par matériau et classe, rugosités, prix unitaires, courbes de coût d'ouvrages, capacités standards de réservoirs, coefficients régionaux, année de référence. Ce sont des **données de référence de l'application**, pas des données projet d'un client. Elles sont versionnées (Alembic), administrables via l'écran "Base de données" du menu (§4), et référencées par leur version dans chaque `Results` pour la traçabilité (V1-11).
- **`session` (éphémère, TTL)** : copie de travail du `.hydrops` actuellement ouvert (le temps d'une édition ou d'un calcul), état des jobs en cours. Purgée à la déconnexion, à l'expiration de session, et par un balayage périodique des sessions orphelines (V1-10). PostGIS y est utile pour les requêtes spatiales pendant l'édition (snap sur trace, calcul de PK, projection d'ouvrages) — voir [06-sig-dem.md](06-sig-dem.md).

Aucune ligne de `session` ne doit survivre à la fermeture/l'expiration de la session ; aucune ligne de `catalog` ne doit contenir de donnée spécifique à un projet client.

## 1.5 Flux type d'une session utilisateur

1. Ouverture de l'application → session éphémère créée côté serveur (UUID + TTL), pas d'authentification lourde requise en V1 (usage professionnel/interne).
2. L'utilisateur ouvre un `.hydrops` local (sélecteur de fichier navigateur) → upload vers l'API → dépaquetage dans le schéma `session` (traces, nœuds, segments, structures, résultats existants s'ils sont encore valides).
3. Édition (ajout de nœud, forçage de DN, ajout d'ouvrage...) → mise à jour du store client + appel API qui met à jour la copie de travail `session`. Les résultats dépendants sont marqués `stale` (V1-03) sans être recalculés automatiquement.
4. "Lancer calcul" → job asynchrone (`hydrops-engine`) → écriture des `Results` dans `session` → notification au client (polling/SSE) → mise à jour de la table/profil/résultats.
5. "Enregistrer" / "Exporter" → l'API repackage l'état `session` courant (+ résultats) en flux binaire `.hydrops` → le navigateur déclenche l'enregistrement local. Le serveur ne conserve pas de copie.
6. Déconnexion, expiration de session ou balayage périodique → suppression des lignes `session` associées (voir [08-sessions-confidentialite.md](08-sessions-confidentialite.md) pour les détails et délais).

## 1.6 Déploiement

**V1 (usage interne)** : `docker-compose` avec 5 services — `web` (SPA servie en statique ou via un petit serveur Vite preview/nginx), `api` (uvicorn), `worker` (arq), `redis`, `postgres` (image PostGIS). Un seul tenant, pas de load balancer nécessaire.

**Évolution SaaS (hors V1, anticipée)** : les mêmes conteneurs se répliquent horizontalement (plusieurs `worker`, `api` derrière une passerelle) ; ajout d'une couche d'authentification multi-tenant (OIDC) en amont des routers sans toucher `hydrops-engine` ni le modèle `session`/`catalog` (le `catalog` gagnerait une dimension "organisation" pour des bibliothèques de coûts propres à chaque client). C'est précisément pour absorber ce changement sans réécriture que la séparation moteur de calcul / API / stockage est stricte dès la V1.

## 1.7 Pourquoi pas d'autres options

- **Pas de base de données de projets côté serveur** (approche SaaS classique) : contredit directement §3 et V1-10.
- **Pas de Celery+RabbitMQ** pour la V1 : complexité opérationnelle non justifiée pour un seul tenant interne ; `arq`/Redis suffit et est plus simple à exploiter. À réévaluer si le SaaS multi-tenant impose un ordonnancement plus riche.
- **Pas de Mapbox GL propriétaire** : licence et coût incompatibles avec "SaaS international" à terme ; MapLibre est un fork open-source API-compatible.
- **Pas de solveur de réseau maillé** en V1 : hors périmètre explicite (§2) — le graphe reste arborescent, ce qui simplifie fortement `topology` et `hydraulics`.
