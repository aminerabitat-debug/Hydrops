// Mise en donnees detaillee par type d'ouvrage (cdc §8, consigne utilisateur) — declarative plutot
// que code specifique par type dans NodeDialog : chaque type d'ouvrage reel (sauf Piquage, qui
// reutilise directement Node.injected_flow/withdrawn_flow, et Station de traitement, qui a une
// structure a deux niveaux type -> filieres) liste ses champs ici. Stocke tel quel dans
// Node.data (JSON libre cote backend, cf. hydropack.models.Node), sans validation par champ.

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
  | { key: string; label: string; kind: 'number'; unit?: string; showIf?: (data: Record<string, unknown>) => boolean }
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
  { key: 'flow', label: 'Débit', kind: 'number', unit: 'm³/h' },
  { key: 'suction_pressure', label: "Pression à l'aspiration", kind: 'number', unit: 'm' },
  { key: 'head_losses', label: 'Pertes de charge dans la station', kind: 'number', unit: 'm' },
]

const RESERVOIR_FIELDS: OuvrageFieldSpec[] = [
  {
    key: 'reservoir_type',
    label: 'Type',
    kind: 'select',
    options: ['Semi-enterré couvert', 'Semi-enterré non couvert', 'Surélevé'],
  },
  { key: 'capacity', label: 'Capacité', kind: 'number', unit: 'm³' },
  { key: 'fluid', label: 'Fluide', kind: 'select', options: FLUIDE_OPTIONS },
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
  reservoir: RESERVOIR_FIELDS,
  pressure_break: PRESSURE_BREAK_FIELDS,
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
