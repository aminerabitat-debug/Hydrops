// Store applicatif (Lot 1) — cf. docs/architecture/01-architecture-systeme.md §1.3.
// Un seul store "projet ouvert" + un bus de selection partage par Carte/Profil/Table (V1-02).
// La synchro carte/profil/table est entierement cote client : aucun etat serveur n'est necessaire
// pour un survol ou une selection.

import { create } from 'zustand'

import { api } from '../shared/apiClient'
import type { Node, Project, ProjectStateResponse, Segment, TraceGeometry, TronconGroup, Variant } from '../shared/types'

// Portee de la table (point 5, feedback utilisateur) : un Trace selectionne montre tous les
// piquets avec les colonnes topo uniquement ; un Troncon selectionne filtre sur sa plage de PK et
// ajoute les colonnes conduite (materiau/DN/classe/DI/rugosite, futures colonnes hydrauliques).
export type TableScope = { kind: 'trace' } | { kind: 'troncon'; pkStart: number; pkEnd: number; label: string }

interface SelectionState {
  hoveredPk: number | null
  selectedTraceId: string | null
  selectedVariantId: string | null
  selectedNodeId: string | null
  tableScope: TableScope
}

// Demande de recadrage carte emise par l'arborescence (cdc, consigne utilisateur : cliquer sur le
// projet/un trace/un ouvrage/un troncon doit zoomer la carte dessus). Un simple objet ne suffit pas
// a re-declencher l'effet de MapView si le MEME element est recliqué deux fois de suite (identite
// object stable au sens de Zustand) — d'ou le compteur `nonce`, incremente a chaque demande.
export type MapFocusTarget =
  | { kind: 'project' }
  | { kind: 'trace'; traceId: string }
  | { kind: 'node'; nodeId: string }
  | { kind: 'troncon'; traceId: string; pkStart: number; pkEnd: number }

interface MapFocusRequest {
  target: MapFocusTarget
  nonce: number
}

interface AppState {
  sessionId: string | null
  project: Project | null
  variants: Variant[]
  traces: TraceGeometry[]
  nodes: Node[]
  segments: Segment[]
  troncons: TronconGroup[]
  selection: SelectionState
  statusMessage: string
  mapFocusRequest: MapFocusRequest | null

  setSessionId: (sessionId: string) => void
  setProjectState: (state: ProjectStateResponse) => void
  clearProject: () => void
  setHoveredPk: (pk: number | null) => void
  setSelectedTrace: (traceId: string | null) => void
  setSelectedVariant: (variantId: string | null) => void
  setSelectedNode: (nodeId: string | null) => void
  setTableScope: (scope: TableScope) => void
  setNetwork: (nodes: Node[], segments: Segment[], troncons: TronconGroup[]) => void
  refreshNetwork: () => Promise<void>
  setStatusMessage: (message: string) => void
  requestMapFocus: (target: MapFocusTarget) => void
}

const DEFAULT_SELECTION: SelectionState = {
  hoveredPk: null,
  selectedTraceId: null,
  selectedVariantId: null,
  selectedNodeId: null,
  tableScope: { kind: 'trace' },
}

export const useAppStore = create<AppState>((set, get) => ({
  sessionId: null,
  project: null,
  variants: [],
  traces: [],
  nodes: [],
  segments: [],
  troncons: [],
  selection: DEFAULT_SELECTION,
  statusMessage: 'Pret',
  mapFocusRequest: null,

  setSessionId: (sessionId) => set({ sessionId }),

  setProjectState: (state) =>
    set((s) => ({
      project: state.project,
      variants: state.variants,
      traces: state.traces,
      selection: {
        ...s.selection,
        selectedTraceId:
          s.selection.selectedTraceId && state.traces.some((t) => t.id === s.selection.selectedTraceId)
            ? s.selection.selectedTraceId
            : (state.traces[0]?.id ?? null),
        selectedVariantId:
          s.selection.selectedVariantId && state.variants.some((v) => v.id === s.selection.selectedVariantId)
            ? s.selection.selectedVariantId
            : (state.variants[0]?.id ?? null),
      },
    })),

  clearProject: () =>
    set({
      project: null,
      variants: [],
      traces: [],
      nodes: [],
      segments: [],
      troncons: [],
      selection: DEFAULT_SELECTION,
    }),

  setHoveredPk: (pk) => set((s) => ({ selection: { ...s.selection, hoveredPk: pk } })),

  setSelectedTrace: (traceId) =>
    set((s) => ({
      selection: { ...s.selection, selectedTraceId: traceId, hoveredPk: null, tableScope: { kind: 'trace' } },
    })),

  setSelectedVariant: (variantId) => set((s) => ({ selection: { ...s.selection, selectedVariantId: variantId } })),

  setSelectedNode: (nodeId) => set((s) => ({ selection: { ...s.selection, selectedNodeId: nodeId } })),

  setTableScope: (scope) => set((s) => ({ selection: { ...s.selection, tableScope: scope } })),

  setNetwork: (nodes, segments, troncons) => set({ nodes, segments, troncons }),

  // Recharge noeuds/segments/troncons depuis le backend pour la variante selectionnee — a appeler
  // apres toute mutation (ajout/suppression de noeud, edition de segment) ou changement de
  // variante (rien de tout ca ne fait partie de ProjectStateResponse, cf. docs/architecture/05-api.md).
  refreshNetwork: async () => {
    const { sessionId, selection } = get()
    if (!sessionId || !selection.selectedVariantId) {
      set({ nodes: [], segments: [], troncons: [] })
      return
    }
    const [nodes, segments, troncons] = await Promise.all([
      api.listNodes(sessionId, selection.selectedVariantId),
      api.listSegments(sessionId, selection.selectedVariantId),
      api.listTroncons(sessionId, selection.selectedVariantId),
    ])
    set({ nodes, segments, troncons })
  },

  setStatusMessage: (message) => set({ statusMessage: message }),

  requestMapFocus: (target) => set((s) => ({ mapFocusRequest: { target, nonce: (s.mapFocusRequest?.nonce ?? 0) + 1 } })),
}))
