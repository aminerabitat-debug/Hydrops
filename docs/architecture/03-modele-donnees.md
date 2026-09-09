# 3. Modèle de données

Ce modèle est la traduction directe de [cdc §5](../functional-spec/cahier-des-charges-v1.md#5-modèle-métier) (Projet, Variante, Trace, Nœud, Segment), étendu avec `Structure`, `Calculation` et `Results` pour couvrir §8 à §17. C'est le modèle **logique** : sa forme physique côté client est TypeScript, côté serveur des modèles Pydantic générés depuis le JSON Schema `hydropack` ([04-format-hydrops.md](04-format-hydrops.md)), et sa forme persistée éphémère est le schéma Postgres `session` ([08-sessions-confidentialite.md](08-sessions-confidentialite.md)).

## 3.1 Diagramme entité-association

```mermaid
erDiagram
    PROJECT ||--o{ VARIANT : contient
    VARIANT ||--o{ TRACE : contient
    VARIANT ||--o{ CALCULATION : declenche
    TRACE ||--o{ NODE : porte
    TRACE }o--o| TRACE : "se raccorde sur (lien nodal)"
    NODE ||--o{ SEGMENT : "amont de"
    NODE ||--o| STRUCTURE : "héberge (0..1)"
    SEGMENT }o--|| NODE : "amont"
    SEGMENT }o--|| NODE : "aval"
    CALCULATION ||--|| RESULTS : produit
    CALCULATION }o--|| VARIANT : porte_sur

    PROJECT {
        uuid id
        string name
        string client
        string currency
        int study_horizon_years
        int project_lifetime_years
        float discount_rate
    }
    VARIANT {
        uuid id
        uuid project_id
        string name
        uuid duplicated_from_variant_id
        string status
    }
    TRACE {
        uuid id
        uuid variant_id
        string water_type
        string hydraulic_direction
        int topological_order
        uuid parent_trace_id
        uuid parent_node_id
    }
    NODE {
        uuid id
        uuid trace_id
        string type
        float pk
        float x
        float y
        float z
        string z_source
        float injected_flow
        float withdrawn_flow
        bool validated
    }
    SEGMENT {
        uuid id
        uuid upstream_node_id
        uuid downstream_node_id
        float length
        string material
        int dn
        float di
        string pressure_class
        float roughness
        bool forced
    }
    STRUCTURE {
        uuid id
        uuid node_id
        string type
        json attributes
        uuid cost_rule_ref
    }
    CALCULATION {
        uuid id
        uuid variant_id
        string engine_version
        string input_hash
        string status
        string friction_method
    }
    RESULTS {
        uuid id
        uuid calculation_id
        json per_node
        json per_segment
        json economics
        json traceability
    }
```

## 3.2 Project

Racine du fichier `.hydrops`. Un seul `Project` par fichier ; correspond à `project.json` + `techno_economic.json`.

| Champ | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `name`, `client`, `description`, `location` | string | `location` : libellé libre en V1 (pas de géocodage requis) |
| `currency` | code ISO 4217 | affichage uniquement, pas de conversion de change |
| `default_water_type` | enum | surchargeable par trace (§5.2) |
| `study_horizon_years` | int | horizon d'étude |
| `project_lifetime_years` | int | durée de vie globale du projet |
| `first_investment_year` | int | |
| `discount_rate` | float (0–1) | taux d'actualisation, utilisé par `economics` |
| `energy_price` | float | prix de l'énergie, unité monnaie/kWh |
| `annual_volume` | `{ mode: "constant", value } \| { mode: "table", points: [{year, value}] }` | table jusqu'à l'horizon puis maintien constant (§5.1) |
| `lifetimes_by_category` | `{ pipes, civil_works, electromechanical, instrumentation_control, other } → years` | pilote le réinvestissement (§14) |
| `options.include_reinvestment` | bool | activable indépendamment (V1-09) |
| `options.include_residual_value` | bool | activable indépendamment (V1-09) |
| `language`, `units_system`, `number_format`, `page_format` | enum | i18n/config (§18) |
| `branding` | `{ logo_asset_ref, doc_number, revision, issue_date, prepared_by, checked_by, approved_by }` | personnalisation entreprise (§18) |

## 3.3 Variant

| Champ | Type | Notes |
|---|---|---|
| `id`, `project_id` | uuid | |
| `name`, `description` | string | |
| `duplicated_from_variant_id` | uuid \| null | traçabilité de duplication (V1-03) ; la duplication est une copie intégrale profonde, jamais une référence partagée |
| `trace_ids` | uuid[] | une ou plusieurs traces continues (§5.2) |
| `forcings` | `Forcing[]` | voir ci-dessous |
| `optimization_mode` | `"auto" \| "manual"` | §10 |
| `status` | `"draft" \| "calculated" \| "stale"` | `stale` dès qu'une entrée dépendante change (V1-03) ; jamais recalculé implicitement |

**Forcing** (forçage utilisateur, §10) :

| Champ | Type | Notes |
|---|---|---|
| `scope` | `{ type: "trace", trace_id } \| { type: "node_range", from_node_id, to_node_id }` | trace entière ou entre deux nœuds |
| `dn`, `material`, `pressure_class` | optionnels, un ou plusieurs forcés | un forçage qui empêche toute solution valide doit lever une alerte **Bloquante** (§17), pas un échec silencieux |

## 3.4 Trace

| Champ | Type | Notes |
|---|---|---|
| `id`, `variant_id` | uuid | |
| `source` | `"kml_import" \| "kmz_import"` | pas de dessin libre en V1 (hors périmètre §2) |
| `geometry` | LineString (WGS84) | issue du KML/KMZ, une ligne continue par trace (V1-01) |
| `length` | float (m) | dérivé de la géométrie |
| `pk_origin` | float | offset de PK cumulé si la trace n'est pas la racine du réseau |
| `hydraulic_direction` | `"as_drawn" \| "reversed"` | inversion possible (§6) |
| `topological_order` | int | calculé, ordre dans le graphe orienté arborescent |
| `water_type` | enum | surchargeable par trace |
| `parent_trace_id`, `parent_node_id` | uuid \| null | lien nodal explicite de raccordement/piquage (§5.2) ; `null` = trace racine du réseau |

Contrainte structurante : le réseau (toutes traces d'une variante confondues) forme **un graphe orienté arborescent sans boucle** (§5.2). Toute tentative de créer un cycle via `parent_trace_id`/`parent_node_id` est rejetée à la validation (alerte Bloquante).

## 3.5 Node

| Champ | Type | Notes |
|---|---|---|
| `id`, `trace_id` | uuid | |
| `type` | enum : `junction`, `high_point`, `low_point`, `sectioning_valve`, `control_valve`, `pressure_break`, `reservoir`, `pumping_station`, `intake`, `treatment_plant`, `tie_in`, `terminal` | correspond aux ouvrages de §8 + nœuds topologiques simples |
| `pk` | float | position cumulée le long de la trace |
| `x`, `y`, `z` | float | coordonnées ; `z` peut venir du DEM ou d'une saisie manuelle |
| `z_source` | `"dem" \| "manual" \| "surveyed"` | traçabilité de l'altimétrie |
| `injected_flow`, `withdrawn_flow` | float (m³/s ou l/s selon `units_system`) | débit injecté/prélevé au nœud |
| `parent_link` | `{ trace_id, node_id } \| null` | pour un nœud de type `tie_in` référençant une autre trace |
| `validated` | bool | pertinent pour `high_point`/`low_point` : `false` tant que l'utilisateur n'a pas confirmé la candidature détectée automatiquement (§6) |
| `structure_id` | uuid \| null | si ce nœud héberge un ouvrage à attributs riches (voir §3.7) |

## 3.6 Segment

Porté par le nœud amont : "les champs linéaires d'une ligne appartiennent au segment associé au nœud amont" (§7).

| Champ | Type | Notes |
|---|---|---|
| `id` | uuid | |
| `upstream_node_id`, `downstream_node_id` | uuid | |
| `pk_start`, `pk_end`, `length` | float | |
| `material` | enum (référence `catalog`) | |
| `dn` | int | diamètre nominal, commercial standard uniquement (§10) |
| `di`, `de` | float | diamètre intérieur/extérieur, dérivés de `catalog` pour (matériau, DN, classe) |
| `pressure_class` | enum (référence `catalog`) | |
| `roughness` | float | rugosité, dérivée du matériau ou surchargée |
| `flow` | float | débit de dimensionnement |
| `forced` | bool | vrai si un `Forcing` de la variante s'applique à ce segment |
| **Résultats (post-calcul, voir §3.9)** | | remplis uniquement après `Calculation`, jamais recalculés à la volée dans le modèle du segment lui-même |

Contrainte structurante de l'optimisation (§10) : les diamètres intérieurs sont **non croissants vers l'aval** sur un même chemin du graphe. C'est une contrainte de validation sur `Segment.di` le long de la topologie, pas seulement une heuristique d'optimisation.

## 3.7 Structure (ouvrage)

Modèle polymorphe : un cœur commun + des attributs spécifiques par type, en JSON typé côté `hydrops-engine`/`hydropack` (pas de table par type côté persistance — un seul type `Structure` avec un champ `attributes` discriminé par `type`, plus simple à faire évoluer que de l'héritage de tables).

| Champ commun | Type | Notes |
|---|---|---|
| `id`, `node_id` | uuid | 1 `Structure` ↔ 0..1 `Node` |
| `type` | enum : `high_point`, `low_point`, `sectioning_valve`, `control_valve`, `pressure_break`, `reservoir`, `pumping_station`, `intake`, `treatment_plant` | |
| `cost_rule_ref` | référence `catalog` | courbe/table de coût en fonction du DN ou autres paramètres (§12) |
| `attributes` | objet discriminé par `type`, voir ci-dessous | |

Attributs par type (§8) :

- **`reservoir`** : `volume`, `geometry: "circular" | "rectangular"`, `burial: "semi_buried" | "elevated"`, `height_if_elevated`, `standard_capacity_ref` (optionnel, référence `catalog`, sinon saisie libre).
- **`pumping_station`** : `configuration: "on_network" | "on_reservoir" | "with_regulation_tank" | "borehole" | "submersible" | "well_booster"`, `hmt_margin` (valeur et/ou % — point ouvert §20, voir décision ci-dessous), `pump_efficiency`, `motor_efficiency`.
- **`intake`** : `source_type: "sea" | "dam" | "river" | "canal" | "pipe_tie_in" | "reservoir"`.
- **`treatment_plant`** : `process_type: "surface_water" | "desalination" | "brackish_demineralization" | "wastewater" | "chlorination" | "fe_mn_removal"`, `design_flow` (niveau APS uniquement, §9 du plan Lot — pas de dimensionnement process détaillé, hors périmètre §2).
- **`sectioning_valve`** : `spacing_rule: "auto_5km" | "manual"`, `spacing_override_m` (si `auto`, modifiable, V1-07), position individuellement déplaçable.
- **`control_valve`**, **`pressure_break`** : objets fonctionnels APS, attributs minimaux en V1 (statut fonctionnel, pas de courbe de régulation détaillée — cohérent avec le positionnement APS §1).
- **`high_point`**, **`low_point`** : `detection_source: "auto_candidate" | "user_added"`, `validated` (miroir du champ sur `Node`, redondant intentionnellement pour permettre un ouvrage ajouté manuellement sans candidat détecté).

> **Décision Phase 0 sur le point ouvert §20 "format de la marge HMT"** : le champ `hmt_margin` est modélisé comme `{ value_mce?: number, value_pct?: number }` — les deux formes coexistent dans le modèle (au moins une renseignée), et `hydrops-engine` documente explicitement l'ordre d'application (ex. % d'abord puis marge fixe, ou l'inverse) au moment du Lot 3. Ce n'est pas tranché plus finement ici pour ne pas anticiper une règle métier qui appartient au Lot métier hydraulique.

## 3.8 Calculation

Représente une exécution du moteur pour une variante donnée — jamais un résultat modifiable directement.

| Champ | Type | Notes |
|---|---|---|
| `id`, `variant_id` | uuid | |
| `engine_version` | semver | version exacte de `hydrops-engine` utilisée (V1-11) |
| `input_hash` | string | hash stable de toutes les entrées dépendantes (géométrie, échantillons DEM, snapshot `catalog`, forçages, paramètres économiques) — sert à détecter l'obsolescence (V1-03) |
| `friction_method` | `"darcy_weisbach_colebrook" \| "darcy_weisbach_swamee_jain" \| "hazen_williams"` | §9 |
| `catalog_version` | string | version du schéma `catalog` utilisée |
| `dem_source_version` | string | source + version DEM utilisée (traçabilité §17) |
| `status` | `"pending" \| "running" \| "done" \| "failed" \| "stale"` | `stale` si `input_hash` ne correspond plus à l'état courant de la variante |
| `triggered_at`, `duration_ms` | | |
| `alerts` | `Alert[]` | voir §3.10 |

## 3.9 Results

| Champ | Type | Notes |
|---|---|---|
| `id`, `calculation_id`, `variant_id` | uuid | |
| `per_node` | `{ node_id: { hgl_min, hgl_max, hydrostatic_min, hydrostatic_max, ground_pressure_min, ground_pressure_max, pressure_envelope_max } }` | §7, §9 |
| `per_segment` | `{ segment_id: { head_loss_linear, head_loss_total, velocity, flow } }` | |
| `pumping` | `{ structure_id: { hmt, power, energy_annual } }` | §9 |
| `economics` | `{ capex_by_item, opex_by_item, reinvestment_schedule, residual_value, npv_costs, levelized_cost_per_m3 }` | §12–§14 |
| `trench_metrics` | `{ segment_id: { b_width, h_total, v_bedding, v_pipe, v_primary_backfill, v_secondary_backfill } }` | formules exactes §11, voir [09-strategie-tests.md](09-strategie-tests.md) pour les tests de non-régression sur ces formules |
| `traceability` | `{ engine_version, catalog_version, dem_source_version, economic_assumptions_snapshot }` | dupliqué depuis `Calculation` pour que `Results` reste auto-suffisant si exporté isolément (V1-11) |

Un `Results` n'est jamais muté après création : une nouvelle `Calculation` produit un nouveau `Results`. L'historique des calculs par variante est conservé dans le `.hydrops` tant que l'utilisateur ne le purge pas explicitement.

## 3.10 Alert (transverse)

Pas une entité de premier niveau mais une structure réutilisée par `Calculation`, `Node`, `Trace`, `Structure` :

```
Alert { level: "info" | "warning" | "blocking", code, message_key, context }
```

`code` est un identifiant interne stable (ex. `PRESSURE_BELOW_MIN`, `PRESSURE_CLASS_EXCEEDED`, `VELOCITY_EXCEEDED`, `MISSING_COST_DATA`, `MISSING_ELEVATION_DATA`, `FORCING_BLOCKS_OPTIMIZATION` — repris de §17) ; `message_key` alimente l'i18n (§18). Une alerte `blocking` sur une `Calculation` doit être reflétée dans tout livrable généré à partir de ses `Results` (V1-11, §17 : "une erreur bloquante ne doit pas conduire silencieusement à un livrable présenté comme valide") — le générateur de rapport ([05-api.md](05-api.md) §`reports`) refuse d'émettre un rapport marqué "final" tant qu'une alerte bloquante est active, et doit visiblement estampiller tout export "brouillon/avec réserves" sinon.

## 3.11 Catalog (référence, hors `.hydrops`)

Ces entités vivent dans le schéma Postgres `catalog` (durable) et sont **référencées par id/version** depuis les entités ci-dessus, jamais dupliquées intégralement dans un projet — seule la valeur numérique utilisée au moment du calcul est capturée dans `Results.traceability` pour la reproductibilité même si le `catalog` évolue ensuite :

- `Diameter` (DN standard, par matériau/classe → DI/DE)
- `Material`, `PressureClass`, `Roughness`
- `UnitCost` (conduites, terrassement/remblai)
- `StructureCostCurve` (points hauts/bas, vannes, réservoirs, pompage, traitement — §12)
- `ReservoirStandardCapacity`
- `RegionalCostCoefficient`, `ReferenceYear`

Détail du schéma dans [04-format-hydrops.md](04-format-hydrops.md) (section catalogue) et [05-api.md](05-api.md) (`/catalog`).
