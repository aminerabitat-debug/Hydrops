// Store applicatif (Lot 1) — cf. docs/architecture/01-architecture-systeme.md §1.3.
// Un seul store "projet ouvert" + un bus de selection partage par Carte/Profil/Table (V1-02).
// La synchro carte/profil/table est entierement cote client : aucun etat serveur n'est necessaire
// pour un survol ou une selection.

import { create } from 'zustand'

import type { LayoutMode } from '../app/Workspace'
import { api } from '../shared/apiClient'
import type { Node, Project, ProjectStateResponse, Segment, TraceGeometry, TronconGroup, Variant } from '../shared/types'

// Portee de la table (point 5, feedback utilisateur) : un Trace selectionne montre tous les
// piquets avec les colonnes topo uniquement ; un Troncon selectionne filtre sur sa plage de PK et
// ajoute les colonnes conduite (materiau/DN/classe/DI/rugosite, futures colonnes hydrauliques).
// `traceId`/`startNodeId` (consigne utilisateur : "Calculer" ne cible que le tronçon sélectionné,
// s'il est déjà validé, sans exiger les autres) identifient sans ambiguïté LE tronçon visé pour un
// calcul scopé — cf. apps/api routers/network.py:run_calculation (scope_trace_id/scope_start_node_id).
export type TableScope =
  | { kind: 'trace' }
  | { kind: 'troncon'; pkStart: number; pkEnd: number; label: string; traceId: string; startNodeId: string }

// Type du message de statut (consigne utilisateur : icones par type dans la barre d'etat) —
// 'info' est le defaut implicite de tout appel existant qui ne precise rien.
export type StatusMessageType = 'info' | 'success' | 'warning' | 'error'

// Fenetre log (consigne utilisateur : "les messages d'erreur doivent se répartir entre la barre
// d'état et le log, avec plus de détails dans le log") — alimentee automatiquement par
// setStatusMessage pour les types 'warning'/'error' (jamais pour 'info'/'success', qui restent
// des statuts ephemeres sans interet a conserver). `detail`, quand fourni, porte l'information plus
// complete (ex. la liste entiere des alertes d'un calcul) que le resume affiche dans la barre
// d'etat — sinon `detail` vaut le meme texte que `summary`.
export interface LogEntry {
  id: string
  timestamp: number
  type: StatusMessageType
  summary: string
  detail: string
}

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

// Demande de recadrage PROFIL/TABLE emise par la carte (consigne utilisateur : "en Vue combinée,
// zoomer sur la carte doit centrer le profil/la table sur les piquets au centre de la carte") —
// direction inverse de MapFocusRequest ci-dessus, meme principe de `nonce` pour re-declencher
// l'effet meme si la MEME plage est redemandee (ex. deux zooms qui se terminent sur la meme vue).
export interface ProfileFocusRequest {
  pkStart: number
  pkEnd: number
  nonce: number
}

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
  // Type du dernier message de statut (consigne utilisateur : "utiliser des icones... pour
  // indiquer le type de message") — pilote l'icone/couleur dans la barre d'etat (App.tsx), pas de
  // logique metier associee. 'info' par defaut : la grande majorite des appels existants sont des
  // statuts neutres, jamais rétro-annotes un par un.
  statusMessageType: StatusMessageType
  // Journal des messages d'erreur/avertissement (consigne utilisateur : "fenêtre log à placer en
  // bas de la page... affichable à la demande") — alimente par setStatusMessage, jamais purge
  // automatiquement (seul un "Vider" explicite le fait), pour que l'utilisateur retrouve un
  // message meme apres qu'il ait defile hors de la barre d'etat.
  logEntries: LogEntry[]
  logWindowOpen: boolean
  mapFocusRequest: MapFocusRequest | null
  profileFocusRequest: ProfileFocusRequest | null
  // Disposition Carte/Profil-Table/Vue combinee — au store (pas local a App.tsx) pour que MapView
  // (enfant de Workspace, jamais traverse par cette prop) sache si on est en Vue combinee sans
  // prop-drilling a travers Workspace (consigne utilisateur : sync zoom carte -> profil, uniquement
  // en Vue combinee).
  layoutMode: LayoutMode
  // Affichage/masquage des traversees (consigne utilisateur) — partage entre le profil et la
  // carte, d'ou sa place ici plutot que localement dans ProfileTableView.
  showCrossings: boolean
  // Mode "selection de PK" (consigne utilisateur : bouton "…" a cote des champs PK debut/PK fin
  // du panneau Contraintes de la fenetre Tronçon) — non-null pendant que l'utilisateur doit
  // cliquer sur la carte, le profil graphique ou le profil Data pour choisir un piquet. Partage au
  // niveau du store (pas local a TronconDialog) car la carte/le profil/la table sont des freres,
  // pas des enfants de la fenetre Tronçon. La fenetre appelante se cache (garde son etat React,
  // juste masquee via CSS) plutot que de demonter — cf. TronconDialog.tsx.
  pkPickResolver: ((pk: number) => void) | null

  setSessionId: (sessionId: string) => void
  setProjectState: (state: ProjectStateResponse) => void
  clearProject: () => void
  setHoveredPk: (pk: number | null) => void
  setSelectedTrace: (traceId: string | null) => void
  setSelectedVariant: (variantId: string | null) => void
  setSelectedNode: (nodeId: string | null) => void
  setTableScope: (scope: TableScope) => void
  // Remplace une trace apres une mise a jour ponctuelle (ex. detection des traversees) — sans
  // recharger tout l'etat projet (setProjectState reinitialiserait aussi la selection).
  updateTrace: (trace: TraceGeometry) => void
  setNetwork: (nodes: Node[], segments: Segment[], troncons: TronconGroup[]) => void
  refreshNetwork: () => Promise<void>
  // `detail` optionnel (consigne utilisateur : "plus de détails dans le log") — sinon le log
  // reprend `message` tel quel. N'alimente le journal que pour 'warning'/'error'.
  setStatusMessage: (message: string, type?: StatusMessageType, detail?: string) => void
  toggleLogWindow: () => void
  clearLog: () => void
  requestMapFocus: (target: MapFocusTarget) => void
  requestProfileFocus: (range: { pkStart: number; pkEnd: number }) => void
  setLayoutMode: (mode: LayoutMode) => void
  setShowCrossings: (show: boolean) => void
  beginPkPick: (resolve: (pk: number) => void) => void
  resolvePkPick: (pk: number) => void
  cancelPkPick: () => void
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
  statusMessageType: 'info',
  logEntries: [],
  logWindowOpen: false,
  mapFocusRequest: null,
  profileFocusRequest: null,
  layoutMode: 'both',
  showCrossings: true,
  pkPickResolver: null,

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

  // Selectionner la variante (consigne utilisateur : "il faut la rendre sélectionnable") efface
  // aussi un tronçon eventuellement selectionne — meme logique que selectTrace ci-dessus : viser
  // a nouveau "toute la variante" doit etre un choix explicite, pas un residu d'une selection de
  // tronçon precedente (notamment pour "Calculer", qui se scope sur le dernier tableScope connu).
  setSelectedVariant: (variantId) =>
    set((s) => ({ selection: { ...s.selection, selectedVariantId: variantId, tableScope: { kind: 'trace' } } })),

  setSelectedNode: (nodeId) => set((s) => ({ selection: { ...s.selection, selectedNodeId: nodeId } })),

  setTableScope: (scope) => set((s) => ({ selection: { ...s.selection, tableScope: scope } })),

  updateTrace: (trace) =>
    set((s) => ({ traces: s.traces.map((t) => (t.id === trace.id ? trace : t)) })),

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

  setStatusMessage: (message, type = 'info', detail) =>
    set((s) => ({
      statusMessage: message,
      statusMessageType: type,
      logEntries:
        type === 'warning' || type === 'error'
          ? [...s.logEntries, { id: crypto.randomUUID(), timestamp: Date.now(), type, summary: message, detail: detail ?? message }]
          : s.logEntries,
    })),

  toggleLogWindow: () => set((s) => ({ logWindowOpen: !s.logWindowOpen })),

  clearLog: () => set({ logEntries: [] }),

  requestMapFocus: (target) => set((s) => ({ mapFocusRequest: { target, nonce: (s.mapFocusRequest?.nonce ?? 0) + 1 } })),

  requestProfileFocus: (range) =>
    set((s) => ({ profileFocusRequest: { ...range, nonce: (s.profileFocusRequest?.nonce ?? 0) + 1 } })),

  setLayoutMode: (mode) => set({ layoutMode: mode }),

  setShowCrossings: (show) => set({ showCrossings: show }),

  beginPkPick: (resolve) => set({ pkPickResolver: resolve }),
  resolvePkPick: (pk) => {
    const resolver = get().pkPickResolver
    set({ pkPickResolver: null })
    resolver?.(pk)
  },
  cancelPkPick: () => set({ pkPickResolver: null }),
}))
