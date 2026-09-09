// Types miroir des DTO backend (apps/api/hydrops_api) — cf. docs/architecture/03-modele-donnees.md.
// Lot 3 etape 1 ajoute Node/Segment (types "terminal"/"junction" seulement — pas d'ouvrages).
// Structure/Calculation/Results arrivent aux etapes suivantes du Lot 3.

export interface ProfilePoint {
  pk: number
  z: number
}

export interface ElevationProfile {
  dem_source?: string
  dem_version?: string
  raw: ProfilePoint[]
  smoothed: ProfilePoint[]
  candidate_high_points: ProfilePoint[]
  candidate_low_points: ProfilePoint[]
}

export interface LineStringGeometry {
  type: 'LineString'
  coordinates: [number, number][]
}

export interface TraceGeometry {
  id: string
  project_id: string
  source: 'kml_import' | 'kmz_import'
  source_file_ref?: string
  geometry: LineStringGeometry
  length: number
  pk_origin: number
  hydraulic_direction: 'as_drawn' | 'reversed'
  topological_order: number
  water_type: string
  parent_trace_id?: string | null
  parent_node_id?: string | null
  elevation_profile?: ElevationProfile
}

export interface Variant {
  id: string
  project_id: string
  name: string
  description?: string | null
  duplicated_from_variant_id?: string | null
  forcings: unknown[]
  optimization_mode: 'auto' | 'manual'
  status: 'draft' | 'calculated' | 'stale'
}

export interface AnnualVolumePoint {
  year: number
  value: number
}

export type AnnualVolume =
  | { mode: 'constant'; value: number }
  | { mode: 'table'; points: AnnualVolumePoint[] }

export interface Project {
  id: string
  name: string
  client?: string | null
  location?: string | null
  description?: string | null
  currency: string
  default_water_type: string
  study_horizon_years: number
  project_lifetime_years: number
  first_investment_year: number
  commissioning_year: number
  amortization_years: number
  discount_rate: number
  energy_price: number
  annual_volume: AnnualVolume
  language: 'fr' | 'en'
  units_system: 'SI' | 'US'
  page_format: 'A4' | 'Letter'
}

export interface Metadata {
  format_version: string
  software_version: string
  created_at: string
  modified_at: string
  units_system: 'SI' | 'US'
  generator: string
}

export interface ProjectStateResponse {
  metadata: Metadata
  project: Project
  variants: Variant[]
  traces: TraceGeometry[]
}

// Import de trace asynchrone (cf. docs — l'echantillonnage DEM peut prendre plus d'une minute
// sur une trace longue) : POST demarre un job, GET .../import-jobs/{id} le suit par polling.
export interface ImportJobStarted {
  job_id: string
  total_chunks: number
}

export interface ImportJobStatus {
  job_id: string
  status: 'running' | 'done' | 'failed'
  completed_chunks: number
  total_chunks: number
  trace: TraceGeometry | null
  error: string | null
}

// Noeuds/segments (cdc §5.2, §7) — "terminal"/Extremite n'est plus un type autorise du tout
// (consigne utilisateur) : une extremite de trace est protegee par son PK, pas par son type.
// "junction" (simple changement de DN/materiau) reste un type de semis par defaut pose
// automatiquement par le backend sur les extremites de trace pas encore affectees (traces.py:
// seed_terminal_nodes_and_default_segment), mais n'est plus proposable/editable depuis l'UI
// (consigne utilisateur, Lot 3 etape 1d — cf. CreatableNodeType/NodeDialog:TYPE_OPTIONS) : tout
// noeud touche via l'UI se voit forcement assigner un ouvrage reel. Les valeurs high_point/
// low_point/sectioning_valve/control_valve/intake existent cote schema/backend (ouvrages futurs)
// mais ne sont pas non plus encore creables/editables depuis l'UI.
export type NodeType =
  | 'junction' | 'high_point' | 'low_point' | 'sectioning_valve' | 'control_valve'
  | 'pressure_break' | 'reservoir' | 'pumping_station' | 'intake' | 'treatment_plant'
  | 'tie_in' | 'terminal'

// Types reellement proposables dans le <select> de NodeDialog (Lot 3 etape 1d) : uniquement des
// ouvrages reels, "junction" en est deliberement exclu (ce n'est pas un ouvrage — consigne
// utilisateur) au meme titre que "terminal". "junction" reste ici dans l'union TypeScript
// uniquement pour rester compatible avec les noeuds existants seedes par le backend (cf.
// NodeDialog:resolveInitialType, qui retombe sur le premier ouvrage reel de la liste le cas
// echeant) — jamais choisissable depuis le formulaire.
export type CreatableNodeType = 'junction' | 'tie_in' | 'reservoir' | 'pumping_station' | 'pressure_break' | 'treatment_plant'

// Ouvrages affiches dans l'arborescence Variante (cdc §8) — Piquage y figure desormais (consigne
// utilisateur) mais reste exclu du regroupement en troncons (BOUNDARY_NODE_TYPES cote moteur,
// hydrops_engine.topology.network, inchange). Jonction simple reste exclue de cette liste : ce
// n'est pas un ouvrage, juste un point de changement de DN.
export const REAL_OUVRAGE_TYPES: NodeType[] = ['reservoir', 'pumping_station', 'pressure_break', 'treatment_plant', 'tie_in']

// Un ouvrage est considere "defini" une fois qu'il porte un type reel (pas juste terminal/junction
// generique) — utilise pour les indicateurs visuels de completion (arborescence, troncons).
export function isNodeDefined(node: Pick<Node, 'type'>): boolean {
  return REAL_OUVRAGE_TYPES.includes(node.type)
}

export interface Node {
  id: string
  trace_id: string
  variant_id: string
  type: NodeType
  name?: string | null
  pk: number
  x: number
  y: number
  z: number
  z_source: 'dem' | 'manual' | 'surveyed'
  injected_flow: number
  withdrawn_flow: number
  validated: boolean
  structure_id?: string | null
  // Mise en donnees detaillee specifique au type d'ouvrage (cdc §8) — cf. shared/ouvrageFields.ts
  // pour les champs attendus par type. Cle absente/valeur null tant que rien n'a ete saisi.
  data?: Record<string, unknown> | null
}

const ENDPOINT_PK_TOLERANCE_M = 1e-6

// Une extremite structurelle de trace (PK 0 ou longueur) ne peut jamais etre supprimee — protection
// basee sur le PK, pas sur le type du noeud qui s'y trouve (celui-ci peut et doit finir par porter
// un ouvrage reel, consigne utilisateur). Extrait ici (partage ProfileTableView/ProjectTree) pour
// eviter de dupliquer la tolerance a plusieurs endroits — miroir exact de
// apps/api/hydrops_api/routers/network.py:_is_structural_endpoint.
export function isStructuralEndpoint(node: Pick<Node, 'pk'>, trace: Pick<TraceGeometry, 'length'> | undefined): boolean {
  if (!trace) return false
  return node.pk <= ENDPOINT_PK_TOLERANCE_M || node.pk >= trace.length - ENDPOINT_PK_TOLERANCE_M
}

export interface Segment {
  id: string
  upstream_node_id: string
  downstream_node_id: string
  pk_start: number
  pk_end: number
  length: number
  material: string
  dn: number
  di: number
  de?: number
  pressure_class: string
  roughness: number
  flow: number
  forced: boolean
  // Parametres hydrauliques du troncon (cdc §8), saisis depuis "Modifier le troncon" — le
  // sous-ensemble pertinent depend du regime (cf. shared/troncons.ts:tronconRegime).
  upstream_water_level_max?: number | null
  upstream_water_level_min?: number | null
  min_pressure?: number | null
  downstream_residual_pressure?: number | null
  max_velocity?: number | null
}

// Regroupement de segments consecutifs entre deux limites "dures" (ouvrage reel ou extremite de
// trace) — Piquage/Jonction sont transparents (decision utilisateur, cf. hydrops_engine.topology.
// group_into_troncons). Sert a l'arborescence "Tronçons" et au filtrage de la table par troncon.
export interface TronconGroup {
  trace_id: string
  start_node_id: string
  end_node_id: string
  segment_ids: string[]
  pk_start: number
  pk_end: number
}

export interface NetworkViolation {
  code: string
  message: string
  node_id?: string | null
  segment_id?: string | null
}

export interface CatalogMaterial {
  material: string
  label: string
  pressure_classes: string[]
}

export interface CatalogDiameter {
  dn: number
  di: number
  de: number
}
