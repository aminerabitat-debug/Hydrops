# 5. API backend

FastAPI, REST + JSON pour le CRUD/config, upload/download binaire pour `.hydrops` et les livrables. Pas de WebSocket en V1 (la synchro carte/profil/table est client-only, §1.3) ; les calculs longs utilisent un pattern **job asynchrone + polling**.

Toutes les routes sont préfixées `/api/v1`. L'OpenAPI généré par FastAPI est la source à partir de laquelle `packages/shared-types` génère le client TypeScript ([02-arborescence-repository.md](02-arborescence-repository.md)).

## 5.1 `sessions` — cycle de vie de la session éphémère

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/sessions` | Crée une session éphémère (UUID + TTL), retourne un cookie/jeton de session |
| `POST` | `/sessions/{id}/heartbeat` | Prolonge le TTL tant que l'onglet reste actif |
| `DELETE` | `/sessions/{id}` | Purge explicite (déconnexion volontaire) — voir [08-sessions-confidentialite.md](08-sessions-confidentialite.md) |

## 5.2 `projects` — cycle de vie du fichier `.hydrops`

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/projects/import` | Upload d'un `.hydrops`, dépaquetage + validation JSON Schema → matérialise dans `session` |
| `GET` | `/projects/{session_id}/export` | Repackage l'état `session` courant en flux binaire `.hydrops` |
| `POST` | `/projects/new` | Initialise un projet vide en mémoire de session (équivalent menu Fichier > Nouveau) |
| `GET` | `/projects/{session_id}` | Métadonnées projet + techno-économiques courantes |
| `PATCH` | `/projects/{session_id}` | Met à jour `project.json`/`techno_economic.json` |

## 5.3 `traces` — import et géométrie

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/projects/{session_id}/traces/import` | Upload KML/KMZ → validation continuité géométrique, calcul PK, échantillonnage DEM (V1-01) |
| `GET` | `/projects/{session_id}/traces/{trace_id}` | Géométrie + profil brut/lissé + candidats points hauts/bas |
| `PATCH` | `/projects/{session_id}/traces/{trace_id}` | Inversion de sens hydraulique, lien parent (raccordement/piquage) |
| `DELETE` | `/projects/{session_id}/traces/{trace_id}` | |

## 5.4 `network` — nœuds et segments

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/variants/{variant_id}/nodes` | |
| `POST` | `/variants/{variant_id}/nodes` | Création (y compris validation d'un point haut/bas candidat, positionnement d'ouvrage avec snap sur trace) |
| `PATCH` | `/variants/{variant_id}/nodes/{node_id}` | |
| `DELETE` | `/variants/{variant_id}/nodes/{node_id}` | |
| `GET` | `/variants/{variant_id}/segments` | |
| `PATCH` | `/variants/{variant_id}/segments/{segment_id}` | Forçage DN/matériau/classe sur un segment (répercuté dans `variant.forcings`) |

## 5.5 `structures` — ouvrages

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/variants/{variant_id}/structures` | |
| `POST` | `/variants/{variant_id}/structures` | Création d'un ouvrage typé (§8), lié à un nœud |
| `PATCH` | `/variants/{variant_id}/structures/{structure_id}` | |
| `DELETE` | `/variants/{variant_id}/structures/{structure_id}` | |
| `POST` | `/variants/{variant_id}/structures/valves/reset-spacing` | Réapplique l'espacement automatique 5 km par défaut (V1-07) |

## 5.6 `variants`

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/projects/{session_id}/variants` | Nouvelle variante |
| `POST` | `/variants/{variant_id}/duplicate` | Duplication intégrale (V1-03) — copie profonde, jamais partagée |
| `DELETE` | `/variants/{variant_id}` | |
| `PATCH` | `/variants/{variant_id}` | Mode d'optimisation, forçages |

## 5.7 `calculations` et `optimization` — jobs asynchrones

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/variants/{variant_id}/calculations` | Enqueue un calcul hydraulique (+ optimisation si `optimization_mode: auto`) → retourne `job_id` |
| `GET` | `/calculations/{job_id}/status` | `pending \| running \| done \| failed`, utilisé en polling par le client |
| `GET` | `/calculations/{calculation_id}` | Métadonnées de calcul (méthode, versions, alertes) une fois `done` |
| `GET` | `/calculations/{calculation_id}/results` | `Results` complet |
| `POST` | `/calculations/{calculation_id}/cancel` | Annulation d'un job en cours |

Le choix polling plutôt que WebSocket est délibéré : un calcul V1 (réseau arborescent, pas de solveur de boucles) reste de l'ordre de la seconde à quelques dizaines de secondes pour l'optimisation pompée la plus complexe — un polling à intervalle court (1–2 s) est largement suffisant et évite la complexité opérationnelle d'un canal persistant pour la V1.

## 5.8 `catalog` — bases de données techniques (menu "Base de données", §4)

| Méthode | Route | Rôle |
|---|---|---|
| `GET`/`POST`/`PATCH` | `/catalog/diameters` | Diamètres standards, DI/DE par matériau/classe |
| `GET`/`POST`/`PATCH` | `/catalog/materials` | |
| `GET`/`POST`/`PATCH` | `/catalog/pressure-classes` | |
| `GET`/`POST`/`PATCH` | `/catalog/unit-costs` | Conduites, terrassement/remblai |
| `GET`/`POST`/`PATCH` | `/catalog/structure-cost-curves` | Points hauts/bas, vannes, réservoirs, pompage, traitement |
| `GET`/`POST`/`PATCH` | `/catalog/reservoir-standard-capacities` | |
| `GET` | `/catalog/versions` | Historique des versions de bibliothèque (pour la traçabilité V1-11) |

Ces routes touchent le schéma `catalog` **durable** — elles n'ont pas de notion de session ni de TTL, contrairement à toutes les routes ci-dessus.

## 5.9 `dem` — service DEM

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/dem/sample?lat&lon` | Échantillon ponctuel (usage interne, debug) |
| `GET` | `/dem/coverage` | Métadonnées de couverture/version de la source active |

Détails dans [06-sig-dem.md](06-sig-dem.md). Ce service n'est pas exposé comme une API "produit" en V1 (pas d'import GeoTIFF utilisateur, hors périmètre §2) — il est appelé en interne par `traces/import`.

## 5.10 `reports` — livrables

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/variants/{variant_id}/reports/{type}` | `type ∈ {aps_report, hydraulic_note, capex_opex_estimate, long_profile, variant_comparison}` → enqueue un job de génération, retourne `job_id` |
| `GET` | `/reports/{job_id}/status` | |
| `GET` | `/reports/{job_id}/download` | Stream du fichier généré (PDF/XLSX/DOCX selon `type`) ; supprimé côté serveur après téléchargement ou expiration TTL courte |

Un rapport ne peut être généré en statut "final" si la `Calculation` sous-jacente porte une alerte `blocking` active (§3.10) — la route retourne alors une erreur explicite (409) plutôt qu'un document silencieusement optimiste ; un mode "brouillon avec réserves" reste possible et est visuellement estampillé dans le document.

## 5.11 Gestion d'erreurs

Format d'erreur uniforme :

```json
{ "error_code": "FORCING_BLOCKS_OPTIMIZATION", "message_key": "errors.forcing_blocks_optimization", "level": "blocking", "context": { "...": "..." } }
```

Les codes d'erreur de validation métier reprennent le vocabulaire de `Alert.code` (§3.10) pour rester cohérents entre une erreur API immédiate (ex. requête invalide) et une alerte de calcul (produite de façon asynchrone).
