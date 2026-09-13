// Mise en donnees detaillee par type d'ouvrage (cdc §8, consigne utilisateur) — declarative plutot
// que code specifique par type dans NodeDialog : chaque type d'ouvrage reel (sauf Piquage, qui
// reutilise directement Node.injected_flow/withdrawn_flow, et Station de traitement, qui a une
// structure a deux niveaux type -> filieres) liste ses champs ici. Stocke tel quel dans
// Node.data (JSON libre cote backend, cf. hydropack.models.Node), sans validation par champ.

import { isPlaceholderNode } from './nodeLabels'
import type { CreatableNodeType, Node } from './types'

export const FLUIDE_OPTIONS = [
  'Eau potable',
  'Eau brute',
  'Eau de mer',
  'Eau déminéralisée',
  'Eau usée brute',
  'Eau usée traitée',
]

export type OuvrageFieldSpec =
  | { key: string; label: string; kind: 'select'; options: string[]; showIf?: (data: Record<string, unknown>) => boolean }
  | {
      key: string
      label: string
      kind: 'number'
      unit?: string
      // Valeur proposee a la creation quand rien n'est herite de l'ouvrage precedent (consigne
      // utilisateur : "maintenir des valeurs par defaut" pour la pression a l'aspiration et les
      // pertes de charge station) — cf. applyFieldDefaults, jamais imposee si deja saisie/heritee.
      defaultValue?: number
      showIf?: (data: Record<string, unknown>) => boolean
    }
  | { key: string; label: string; kind: 'checkbox-group'; options: string[]; showIf?: (data: Record<string, unknown>) => boolean }

const PUMPING_STATION_FIELDS: OuvrageFieldSpec[] = [
  {
    key: 'installation_type',
    label: "Type d'installation",
    kind: 'select',
    options: ['En cale sèche', 'Submersible', 'Immergée', "À ligne d'arbre"],
  },
  {
    key: 'suction_type',
    label: "Type d'aspiration",
    kind: 'select',
    options: ['Sur conduite', 'Sur bâche/réservoir'],
    showIf: (d) => d.installation_type === 'En cale sèche',
  },
  { key: 'fluid', label: 'Fluide', kind: 'select', options: FLUIDE_OPTIONS },
  { key: 'suction_pressure', label: "Pression à l'aspiration", kind: 'number', unit: 'm', defaultValue: 3 },
  { key: 'head_losses', label: 'Pertes de charge dans la station', kind: 'number', unit: 'm', defaultValue: 1 },
]

// Débit + autonomie plutôt qu'une capacité saisie directement (consigne utilisateur) — la
// capacité s'en déduit (NodeDialog affiche la valeur calculée, en lecture seule). L'unité de
// l'autonomie n'est plus un choix de l'utilisateur (consigne utilisateur) : heures pour un
// réservoir de stockage, minutes pour un réservoir de mise en charge — fixée par le TYPE
// d'ouvrage, cf. computeReservoirCapacity qui en tient lieu plutôt que de la stocker dans `data`.
const STORAGE_RESERVOIR_FIELDS: OuvrageFieldSpec[] = [
  {
    key: 'reservoir_type',
    label: 'Type',
    kind: 'select',
    options: ['Semi-enterré couvert', 'Semi-enterré non couvert', 'Surélevé'],
  },
  { key: 'fluid', label: 'Fluide', kind: 'select', options: FLUIDE_OPTIONS },
  { key: 'flow', label: 'Débit', kind: 'number', unit: 'm³/h' },
  { key: 'autonomy', label: 'Autonomie (heures)', kind: 'number' },
]

const SURGE_RESERVOIR_FIELDS: OuvrageFieldSpec[] = [
  {
    key: 'reservoir_type',
    label: 'Type',
    kind: 'select',
    options: ['Semi-enterré couvert', 'Semi-enterré non couvert', 'Surélevé'],
  },
  { key: 'fluid', label: 'Fluide', kind: 'select', options: FLUIDE_OPTIONS },
  { key: 'flow', label: 'Débit', kind: 'number', unit: 'm³/h' },
  { key: 'autonomy', label: 'Autonomie (minutes)', kind: 'number' },
]

const PRESSURE_BREAK_FIELDS: OuvrageFieldSpec[] = [
  { key: 'selection_mode', label: 'Sélection', kind: 'select', options: ['Manuelle', 'Auto'] },
  {
    key: 'obturateur_type',
    label: "Type d'obturateur",
    kind: 'select',
    options: ['Obturateur à disque noyé', 'Obturateur à disque sous capot'],
    showIf: (d) => d.selection_mode === 'Manuelle',
  },
  { key: 'fluid', label: 'Fluide', kind: 'select', options: FLUIDE_OPTIONS },
]

// Types reels proposables dans le <select> de NodeDialog qui ont une liste de champs FIXE
// (Station de traitement geree a part : sa liste de filieres depend du sous-type choisi, cf.
// TREATMENT_PLANT_SUBTYPES ci-dessous). Piquage n'y figure pas non plus : Debit/Prelevement-
// Injection reutilisent directement Node.injected_flow/withdrawn_flow.
export const OUVRAGE_FIELDS: Partial<Record<CreatableNodeType, OuvrageFieldSpec[]>> = {
  pumping_station: PUMPING_STATION_FIELDS,
  storage_reservoir: STORAGE_RESERVOIR_FIELDS,
  surge_reservoir: SURGE_RESERVOIR_FIELDS,
  pressure_break: PRESSURE_BREAK_FIELDS,
}

// Capacité déduite du débit + de l'autonomie (consigne utilisateur : "l'utilisateur va introduire
// un débit et une autonomie") — affichée en lecture seule dans NodeDialog, jamais stockée
// séparément (une seule source de vérité, pas de désynchronisation possible). L'unité de
// l'autonomie est fixée par le TYPE d'ouvrage (consigne utilisateur), pas par un choix stocké
// dans `data` : heures pour un réservoir de stockage, minutes pour un réservoir de mise en charge.
export function computeReservoirCapacity(
  data: Record<string, unknown> | null | undefined,
  type: CreatableNodeType,
): number | null {
  const flow = typeof data?.flow === 'number' ? data.flow : null
  const autonomy = typeof data?.autonomy === 'number' ? data.autonomy : null
  if (flow == null || autonomy == null || flow <= 0 || autonomy <= 0) return null
  const autonomyHours = type === 'surge_reservoir' ? autonomy / 60 : autonomy
  return flow * autonomyHours
}

// Un ouvrage est considere "donnees validees" (couleur du texte dans l'arborescence, consigne
// utilisateur) des lors qu'au moins un champ de sa mise en donnees specifique a ete rempli et
// enregistre — Piquage reutilise injected_flow/withdrawn_flow (pas `data`), les autres types
// passent par `data` (objet libre, cf. Node.data).
export function isOuvrageDataDefined(
  node: Pick<Node, 'type' | 'data' | 'injected_flow' | 'withdrawn_flow'>,
): boolean {
  if (node.type === 'tie_in') return (node.injected_flow ?? 0) > 0 || (node.withdrawn_flow ?? 0) > 0
  const data = node.data
  if (!data) return false
  return Object.values(data).some((v) => {
    if (v === undefined || v === null || v === '') return false
    if (Array.isArray(v)) return v.length > 0
    return true
  })
}

// Ouvrage reel le plus proche en amont (pk le plus grand strictement inferieur a `pk`) sur la
// meme trace, avec une mise en donnees definie — utilise pour preremplir le fluide/debit d'un
// nouvel ouvrage depuis celui qui le precede dans le profil, quand il existe (consigne utilisateur).
export function findPrecedingOuvrage(nodes: Node[], traceId: string, pk: number): Node | null {
  const candidates = nodes
    .filter((n) => n.trace_id === traceId && n.pk < pk && !isPlaceholderNode(n) && isOuvrageDataDefined(n))
    .sort((a, b) => b.pk - a.pk)
  return candidates[0] ?? null
}

// Intersection des cles de `precedingData` presentes dans `fieldSpecs` du nouveau type — utilise
// pour heriter fluide/debit (et tout autre champ partage) sans coder en dur une liste de cles
// (consigne utilisateur : "il doit prendre les infos relatives au fluide et débit").
export function inheritableOuvrageData(
  precedingData: Record<string, unknown> | null | undefined,
  fieldSpecs: OuvrageFieldSpec[] | undefined,
): Record<string, unknown> {
  if (!precedingData || !fieldSpecs) return {}
  const keys = new Set(fieldSpecs.map((f) => f.key))
  return Object.fromEntries(Object.entries(precedingData).filter(([k]) => keys.has(k)))
}

// Complete `data` (deja herite d'un eventuel ouvrage precedent, cf. inheritableOuvrageData) avec les
// `defaultValue` des champs numeriques qui n'ont encore aucune valeur — consigne utilisateur :
// "maintenir des valeurs par defaut" (pression a l'aspiration, pertes de charge station...),
// jamais imposees si deja saisies/heritees.
export function applyFieldDefaults(
  data: Record<string, unknown>,
  fieldSpecs: OuvrageFieldSpec[] | undefined,
): Record<string, unknown> {
  if (!fieldSpecs) return data
  const withDefaults = { ...data }
  for (const spec of fieldSpecs) {
    if (spec.kind === 'number' && spec.defaultValue != null && withDefaults[spec.key] === undefined) {
      withDefaults[spec.key] = spec.defaultValue
    }
  }
  return withDefaults
}

// Phasage des stations (pumping_station/treatment_plant) — consigne utilisateur : "un tableau
// Génie Civil et Equipement dans les lignes et Phases dans les colonnes". Stocke dans
// Node.data.station_phasing (donnee libre cote backend, aucun schema dedie necessaire). Chaque
// cellule est soit "existant" (case cochee), soit un debit en m3/h pour l'investissement de cette
// phase, soit vide (aucun investissement prevu dans cette phase pour cette ligne).
export interface StationPhaseCell {
  existing: boolean
  flow_m3h?: number
}

export interface StationPhasingData {
  civil: Record<string, StationPhaseCell>
  equipment: Record<string, StationPhaseCell>
}

export const STATION_PHASING_ROWS: { key: 'civil' | 'equipment'; label: string }[] = [
  { key: 'civil', label: 'Génie civil' },
  { key: 'equipment', label: 'Équipement' },
]

export function getStationPhasing(data: Record<string, unknown> | null | undefined): StationPhasingData {
  const raw = data?.station_phasing as Partial<StationPhasingData> | undefined
  return { civil: raw?.civil ?? {}, equipment: raw?.equipment ?? {} }
}

const COMMON_UTILITY_FILIERES = [
  "Bâtiment d'exploitation",
  'Atelier',
  'Magasin',
  'Loge gardien',
  'Poste de livraison',
  'Poste de transformation',
  'Groupe électrogène',
]

export interface TreatmentPlantSubtype {
  value: string
  label: string
  filieres: string[]
}

// Liste des filieres inspiree de l'exemple detaille fourni par l'utilisateur pour la
// potabilisation des eaux de surface — les autres sous-types suivent la meme logique (etapes
// techniques propres au procede + memes locaux/equipements d'exploitation communs en fin de liste).
export const TREATMENT_PLANT_SUBTYPES: TreatmentPlantSubtype[] = [
  {
    value: 'surface_potabilisation',
    label: 'Station de potabilisation des eaux de surface',
    filieres: [
      'Préchloration',
      "Ouvrage d'arrivée",
      'Débourbage',
      'Coagulation/Floculation/Décantation',
      'Filtration sur sable',
      'Désinfection (chloration)',
      'Stockage',
      'Pompage',
      'Épaississement (statique ou mécanique)',
      'Déshydratation (mécanique ou sur lits de séchage)',
      'Traitement des eaux de lavage des filtres',
      ...COMMON_UTILITY_FILIERES,
    ],
  },
  {
    value: 'desalination',
    label: 'Station de dessalement',
    filieres: [
      "Prise d'eau de mer",
      'Dégrillage/Tamisage',
      'Pompage eau brute',
      'Filtration (sable/cartouche)',
      'Osmose inverse',
      'Post-traitement/Reminéralisation',
      'Désinfection',
      'Stockage',
      'Pompage de refoulement',
      'Gestion de la saumure de rejet',
      ...COMMON_UTILITY_FILIERES,
    ],
  },
  {
    value: 'wastewater',
    label: "Station d'épuration des eaux usées",
    filieres: [
      'Dégrillage',
      'Dessablage/Déshuilage',
      'Décantation primaire',
      'Traitement biologique (boues activées)',
      'Clarification secondaire',
      'Désinfection (UV/chloration)',
      'Épaississement des boues',
      'Déshydratation des boues',
      'Stockage',
      'Pompage',
      ...COMMON_UTILITY_FILIERES,
    ],
  },
  {
    value: 'demineralization',
    label: 'Station de déminéralisation',
    filieres: [
      'Filtration',
      'Adoucissement',
      'Osmose inverse',
      "Résines échangeuses d'ions",
      'Dégazage',
      'Stockage',
      'Pompage',
      ...COMMON_UTILITY_FILIERES,
    ],
  },
  {
    value: 'iron_manganese_removal',
    label: 'Station de déferrisation et démanganésation',
    filieres: [
      'Aération',
      'Oxydation (chloration/permanganate)',
      'Filtration (sable/pyrolusite)',
      'Décantation',
      'Stockage',
      'Pompage',
      ...COMMON_UTILITY_FILIERES,
    ],
  },
]
