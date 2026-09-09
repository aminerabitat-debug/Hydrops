# 4. Format de fichier `.hydrops`

## 4.1 Principe

`.hydrops` est un conteneur **ZIP** (extension renommée), au même principe que `.docx`/`.xlsx`. C'est le seul format de persistance projet ([cdc §3](../functional-spec/cahier-des-charges-v1.md#3-confidentialité-et-fichier-projet)) : le serveur ne fait que le dépaqueter dans le schéma `session` éphémère pour travailler, et le repaqueter pour l'enregistrement/export ([08-sessions-confidentialite.md](08-sessions-confidentialite.md)).

Chaque fichier interne est validé contre un **JSON Schema** versionné, source unique de vérité, publié dans `packages/hydropack/schema/`. Les modèles Pydantic (backend) et les types TypeScript (frontend) sont **générés** depuis ces schémas — jamais maintenus à la main en double.

## 4.2 Arborescence du conteneur

```
mon_projet.hydrops  (ZIP)
├── metadata.json
├── project.json
├── techno_economic.json
├── traces/
│   ├── <trace_id>.source.kml            # KML/KMZ d'origine, conservé tel quel (auditabilité)
│   └── <trace_id>.geometry.json         # géométrie post-traitement : PK, profil brut+lissé, ordre topo
├── variants/
│   └── <variant_id>/
│       ├── variant.json                 # métadonnées variante, forçages, mode d'optimisation
│       ├── nodes.json
│       ├── segments.json
│       └── structures.json
├── results/
│   └── <variant_id>/
│       └── <calculation_id>/
│           ├── calculation.json         # métadonnées d'exécution (version moteur, hash, alertes)
│           └── results.json             # résultats hydrauliques + économiques + métrés
└── assets/
    └── ...                              # logo entreprise, notes, pièces jointes légères
```

Points de conception :

- **`traces/<id>.source.kml` est conservé sans transformation** : c'est la preuve d'origine de l'import (V1-01), indépendante de tout retraitement algorithmique ultérieur (changement de méthode de lissage, etc.).
- **`results/` est organisé par `variant_id` puis `calculation_id`**, pas un seul `results.json` par variante : ça permet de garder l'historique des calculs (chaque calcul est immuable, §3.8) sans jamais écraser un résultat précédent. La dernière `calculation_id` valide (non `stale`) par variante est celle référencée par l'UI et les exports.
- **Aucun fichier n'est un résumé dénormalisé d'un autre** : la table, le profil et la carte sont tous dérivés côté client de `nodes.json` + `segments.json` + `results.json`, jamais stockés sous une forme redondante dans le paquet.

## 4.3 `metadata.json`

```json
{
  "format_version": "1.0.0",
  "software_version": "0.1.0",
  "created_at": "2026-09-07T10:00:00Z",
  "modified_at": "2026-09-07T14:32:00Z",
  "units_system": "SI",
  "generator": "HydroPS Web"
}
```

`format_version` suit SemVer et gouverne la compatibilité ascendante/descendante de lecture (une version mineure de logiciel plus récente doit pouvoir lire un `format_version` majeur inchangé ; un changement de version majeure déclenche une migration explicite au chargement, jamais une lecture silencieusement dégradée).

## 4.4 Invalidation des résultats

Règle V1-03 : "ses résultats sont invalidés si les entrées changent". Mécanisme retenu : `calculation.json.input_hash` est un hash (SHA-256) calculé sur la concaténation canonique de : `variant.json`, `nodes.json`, `segments.json`, `structures.json`, les `geometry.json` des traces référencées, `techno_economic.json`, et les versions de `catalog`/DEM utilisées. À l'ouverture du fichier, le client (ou l'API lors du dépaquetage) recalcule ce hash pour l'état courant et le compare à celui stocké dans chaque `calculation.json` : s'ils diffèrent, la variante passe en statut `stale` et l'UI l'indique — le `results.json` correspondant n'est **jamais supprimé automatiquement** (l'utilisateur peut vouloir comparer un ancien résultat à un nouveau), il est seulement marqué non fiable tant qu'un nouveau calcul n'a pas été lancé.

## 4.5 Schémas JSON

Les schémas complets (JSON Schema draft 2020-12) sont dans [`packages/hydropack/schema/`](../../packages/hydropack/schema/) :

| Fichier | Schéma |
|---|---|
| `metadata.schema.json` | [metadata.schema.json](../../packages/hydropack/schema/metadata.schema.json) |
| `project.schema.json` | [project.schema.json](../../packages/hydropack/schema/project.schema.json) |
| `techno_economic.schema.json` | [techno_economic.schema.json](../../packages/hydropack/schema/techno_economic.schema.json) |
| `trace_geometry.schema.json` | [trace_geometry.schema.json](../../packages/hydropack/schema/trace_geometry.schema.json) |
| `variant.schema.json` | [variant.schema.json](../../packages/hydropack/schema/variant.schema.json) |
| `node.schema.json` | [node.schema.json](../../packages/hydropack/schema/node.schema.json) |
| `segment.schema.json` | [segment.schema.json](../../packages/hydropack/schema/segment.schema.json) |
| `structure.schema.json` | [structure.schema.json](../../packages/hydropack/schema/structure.schema.json) |
| `calculation.schema.json` | [calculation.schema.json](../../packages/hydropack/schema/calculation.schema.json) |
| `results.schema.json` | [results.schema.json](../../packages/hydropack/schema/results.schema.json) |

Ces fichiers correspondent directement aux entités décrites dans [03-modele-donnees.md](03-modele-donnees.md) ; s'y référer pour la justification métier de chaque champ.

## 4.6 Compatibilité et migration

- Toute évolution de champ **additive et optionnelle** → incrément de version `patch`/`minor`, aucune migration nécessaire.
- Toute évolution structurante (renommage, suppression, changement de type, changement de règle d'invalidation) → incrément `major`, et un module de migration dédié (`packages/hydropack/python/migrations/`) doit être fourni **avant** que le format ne soit utilisé en production, pas après coup.
- Le logiciel refuse d'ouvrir un `.hydrops` dont le `format_version` majeur est supérieur à celui qu'il connaît (pas de lecture partielle silencieuse), et propose une migration automatique pour un `format_version` majeur antérieur connu.
