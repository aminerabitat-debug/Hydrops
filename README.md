# HydroPS

Application web de conception préliminaire (APS / Preliminary Design) des systèmes d'adduction et de transport d'eau — adductions gravitaires, par pompage et mixtes.

Ce dépôt est au stade **Phase 0 : architecture technique et modèle de données**. Aucune fonctionnalité métier n'est encore implémentée ; voir [`docs/architecture/`](docs/architecture/README.md) pour les décisions d'architecture et [`docs/functional-spec/cahier-des-charges-v1.md`](docs/functional-spec/cahier-des-charges-v1.md) pour la spécification fonctionnelle source (V1.0).

## Structure

- [`apps/web`](apps/web) — frontend React + TypeScript
- [`apps/api`](apps/api) — backend FastAPI
- [`packages/hydrops-engine`](packages/hydrops-engine) — moteur de calcul hydraulique/économique (package Python pur, déterministe)
- [`packages/hydropack`](packages/hydropack) — schéma et (dé)sérialiseur du format de fichier `.hydrops`
- [`packages/shared-types`](packages/shared-types) — types TypeScript générés (OpenAPI + JSON Schema)
- [`docs/architecture`](docs/architecture) — décisions d'architecture (Phase 0)
- [`docs/functional-spec`](docs/functional-spec) — cahier des charges fonctionnel versionné
- [`infra`](infra) — Docker Compose et CI

Voir [`docs/architecture/02-arborescence-repository.md`](docs/architecture/02-arborescence-repository.md) pour le détail et les règles de dépendance entre packages.

## Lot 1 — Terminé

Parcours validé de bout en bout, dans un vrai navigateur : créer projet → importer KML/KMZ → afficher sur carte → altitudes DEM → profil brut/lissé → synchronisation carte/profil/table → sauvegarder `.hydrops` → rouvrir `.hydrops`.

- **Backend** (`apps/api`, `packages/hydrops-engine`, `packages/hydropack`) : 53 tests pytest, validé aussi manuellement avec le fournisseur DEM réel (Open-Elevation).
- **Frontend** (`apps/web`) : React + TypeScript, `npm run typecheck` propre, testé dans le navigateur (carte MapLibre, profil canvas, table, synchro par survol, dialogue "Nouveau projet", export `.hydrops`).

```bash
cd apps/api && python -m pip install -r requirements.txt && python -m uvicorn hydrops_api.main:app --reload --port 8000
```

```bash
cd apps/web && npm install && npm run dev
```

Le frontend attend l'API sur `http://localhost:8000/api/v1` (voir `apps/web/src/shared/apiClient.ts`, surchargeable via `VITE_API_BASE_URL`).

Correctif notable en cours de validation navigateur : MapLibre ne redimensionnait pas son canvas quand son conteneur changeait de taille (bascule Carte/Profil-Table/Vue combinée) — corrigé par un `ResizeObserver` dans [`MapView.tsx`](apps/web/src/features/map/MapView.tsx). Le dialogue "Nouveau projet" utilise un formulaire React plutôt que `window.prompt` (bloqué dans plusieurs contextes embarqués).

### Interface redessinée + sources satellite/topo (sur demande utilisateur)

L'interface a été refondue sur le modèle d'une page de référence fournie par l'utilisateur : thème sombre "cockpit", barre de menus complète (Fichier/Variante/Calcul/Base de données/Affichage/Langue/Aide — Calcul/Base de données/Langue en stub explicite, fonctionnalité aux Lots 3/7), barre d'accès rapide, panneaux arrondis, séparateur vertical **réglable** entre carte (haut) et profil/table (bas) plutôt que la bascule par onglets initiale — plus fidèle à cdc §4 ("vue combinée avec séparateur réglable"). Le menu Variante (Nouvelle/Dupliquer/Supprimer) est maintenant câblé dans l'UI (les endpoints existaient déjà côté API depuis le Lot 1 mais n'étaient pas exposés).

Mêmes sources de données que la page de référence :
- **Carte** : fond satellite Esri World Imagery, avec repli automatique vers OpenStreetMap en cas d'échec répété des tuiles.
- **Altitudes** : cascade Open-Meteo Elevation → OpenTopoData ASTER30m → Open-Elevation (`apps/api/hydrops_api/services/dem.py::CascadingDemProvider`), au lieu du seul Open-Elevation — un fournisseur échoue pour le lot entier, le suivant prend le relais, jamais de repli silencieux vers une valeur inventée.

Deux bugs CSS réels trouvés et corrigés pendant la vérification navigateur (grille `.workspace-shell` sans hauteur de ligne explicite qui grandissait selon son contenu ; incohérence de casse entre les classes `layout-mapOnly`/`layout-profileOnly` générées en JS et les sélecteurs CSS `layout-map-only`/`layout-profile-only` hérités de la page de référence, qui empêchait les modes "Carte seule"/"Profil seul" de fonctionner).

Session ephémère : implémentée en mémoire process-local (`apps/api/hydrops_api/core/session_store.py`), pas encore sur PostgreSQL/PostGIS (absent de cet environnement) — l'interface est conçue pour ce remplacement sans impact sur le reste de l'API (voir [docs/architecture/08-sessions-confidentialite.md](docs/architecture/08-sessions-confidentialite.md)).

## Prochaine étape

Lot 2 — Topographie approfondie (Lot 1 en couvre déjà l'essentiel), puis Lot 3 — Métier hydraulique : Nœuds, segments, ouvrages, graphe, calcul hydraulique ([cdc §21](docs/functional-spec/cahier-des-charges-v1.md#21-ordre-de-développement-recommandé)).
