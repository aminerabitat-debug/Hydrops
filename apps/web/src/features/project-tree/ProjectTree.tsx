// Arborescence projet (cdc §4 : "a gauche sur toute la hauteur utile").
// Projet > Paramètres du projet > Tracés (partages entre toutes les variantes) puis
// Variantes > { Ouvrages, Tronçons } (structure demandee par l'utilisateur — les traces ne sont
// plus rattachees a une variante). Ouvrages/Tronçons ne sont affiches que pour la variante
// SELECTIONNEE (nodes/troncons ne sont charges cote client que pour elle, cf. store.refreshNetwork).

import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../../shared/apiClient'
import { nodeColor, nodeDisplayLabel, nodeInitials } from '../../shared/nodeLabels'
import { isOuvrageDataDefined } from '../../shared/ouvrageFields'
import { useAppStore } from '../../state/store'
import { REAL_OUVRAGE_TYPES, isStructuralEndpoint } from '../../shared/types'
import type {
  CalculationPreferences,
  CreatableNodeType,
  Node,
  PipeCatalogRow,
  TronconGroup,
  Variant,
} from '../../shared/types'
import { TRONCON_REGIME_COLOR, TRONCON_REGIME_GLYPH, tronconIsForced, tronconRegime } from '../../shared/troncons'
import { NodeDialog, type NodeSubmitPayload } from '../profile/NodeDialog'
import { TronconDialog, type TronconHydraulicValues } from './TronconDialog'

const POLL_INTERVAL_MS = 400
const VARIANT_PREFIX = 'Variante'

interface ImportProgress {
  completed: number
  total: number
}

interface ProjectTreeProps {
  onOpenProjectSettings: () => void
  onNewVariant: () => void
  onDuplicateVariant: (variantId: string | null) => void | Promise<void>
  onRequestDeleteVariant: (variantId: string | null) => void
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// "Le terme variante doit rester" (consigne utilisateur) : seule la partie qui suit "Variante" est
// editable. On evite la redondance ("Variante Variante 2") si l'utilisateur retape le prefixe lui-meme.
function stripVariantPrefix(name: string): string {
  const trimmed = name.trim()
  const match = trimmed.match(/^variante\s*(.*)$/i)
  return match ? match[1].trim() : trimmed
}

function formatVariantName(suffix: string): string {
  const trimmed = suffix.trim()
  if (/^variante\b/i.test(trimmed)) return trimmed
  return trimmed ? `${VARIANT_PREFIX} ${trimmed}` : VARIANT_PREFIX
}

function NodeBadge({ node }: { node: Pick<Node, 'type'> }) {
  return (
    <span className="node-badge" style={{ backgroundColor: nodeColor(node) }}>
      {nodeInitials(node)}
    </span>
  )
}

export function ProjectTree({ onOpenProjectSettings, onNewVariant, onDuplicateVariant, onRequestDeleteVariant }: ProjectTreeProps) {
  const sessionId = useAppStore((s) => s.sessionId)
  const project = useAppStore((s) => s.project)
  const variants = useAppStore((s) => s.variants)
  const traces = useAppStore((s) => s.traces)
  const nodes = useAppStore((s) => s.nodes)
  const segments = useAppStore((s) => s.segments)
  const troncons = useAppStore((s) => s.troncons)
  const selectedTraceId = useAppStore((s) => s.selection.selectedTraceId)
  const selectedVariantId = useAppStore((s) => s.selection.selectedVariantId)
  const selectedNodeId = useAppStore((s) => s.selection.selectedNodeId)
  const tableScope = useAppStore((s) => s.selection.tableScope)
  const setSelectedTrace = useAppStore((s) => s.setSelectedTrace)
  const setSelectedVariant = useAppStore((s) => s.setSelectedVariant)
  const setSelectedNode = useAppStore((s) => s.setSelectedNode)
  const setTableScope = useAppStore((s) => s.setTableScope)
  const setProjectState = useAppStore((s) => s.setProjectState)
  const refreshNetwork = useAppStore((s) => s.refreshNetwork)
  const setStatusMessage = useAppStore((s) => s.setStatusMessage)
  const requestMapFocus = useAppStore((s) => s.requestMapFocus)
  const importInputRef = useRef<HTMLInputElement>(null)
  // Un import peut prendre plusieurs dizaines de secondes sur une trace tres longue (les
  // altitudes sont recuperees aupres de services publics geres par leurs propres limites de
  // debit, hors de notre controle) — la progression (lots DEM traites / total) vient du backend
  // via polling, pas d'une simple estimation cote client.
  const [isImporting, setIsImporting] = useState(false)
  const [importProgress, setImportProgress] = useState<ImportProgress | null>(null)
  // Afficher/masquer le contenu (Ouvrages/Tronçons) de la variante SELECTIONNEE, independamment de
  // la selection elle-meme (demande utilisateur) — reinitialise a "affiche" a chaque changement de
  // selection, puisque seule la variante selectionnee a son reseau charge cote client.
  const [contentHidden, setContentHidden] = useState(false)
  useEffect(() => setContentHidden(false), [selectedVariantId])

  const [renamingVariantId, setRenamingVariantId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')

  // Modification/suppression d'un ouvrage ou d'un troncon directement depuis l'arborescence,
  // au meme titre que les variantes (consigne utilisateur) — dialogues et appels API self-contenus
  // ici plutot que remontes a App.tsx, sur le meme principe que l'import KML deja gere localement.
  const [editingOuvrage, setEditingOuvrage] = useState<Node | null>(null)
  const [editingTroncon, setEditingTroncon] = useState<{ troncon: TronconGroup; label: string } | null>(null)

  // Valeurs par defaut des Preferences (Pression min/résiduelle/Vitesse Max), pour preremplir
  // "Modifier le tronçon" quand il n'a pas encore sa propre valeur (consigne utilisateur) — chargees
  // une fois par projet ouvert, meme pattern que le catalogue de conduites dans ProfileTableView.
  // `sessionId` est un jeton de SESSION stable (une seule fois par onglet, cf. App.tsx:ensureSession)
  // — un nouveau projet cree/ouvert dans le MEME onglet ne le change jamais, donc `[sessionId]` seul
  // ne redeclencherait cette recuperation qu'une fois pour toute la session : si ce premier appel
  // tombe avant qu'un projet existe (413/409, aucun projet actif), les Préférences resteraient
  // vides pour tous les projets ouverts ensuite. On depend donc aussi de `project?.id`, et on
  // n'appelle meme pas l'API tant qu'aucun projet n'est ouvert.
  const [preferences, setPreferences] = useState<CalculationPreferences | null>(null)
  useEffect(() => {
    if (!sessionId || !project) return
    api.getPreferences(sessionId).then(setPreferences).catch(() => setPreferences(null))
  }, [sessionId, project?.id])

  // Catalogue "Conduites" — sert a peupler les listes Materiau/DN forces de TronconDialog
  // (consigne utilisateur), meme pattern que pipeCatalog dans ProfileTableView.
  const [pipeCatalog, setPipeCatalog] = useState<PipeCatalogRow[]>([])
  useEffect(() => {
    api.listConduites().then(setPipeCatalog).catch(() => setPipeCatalog([]))
  }, [])

  const nodesById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const segmentsById = useMemo(() => new Map(segments.map((s) => [s.id, s])), [segments])
  const tracesById = useMemo(() => new Map(traces.map((t) => [t.id, t])), [traces])
  const ouvrageNodes = useMemo(() => nodes.filter((n) => REAL_OUVRAGE_TYPES.includes(n.type)), [nodes])

  if (!project) {
    return <p className="empty-hint">Aucun projet ouvert.<br />Utilisez Fichier &gt; Nouveau ou Ouvrir.</p>
  }

  const handleSelectOuvrage = (nodeId: string, traceId: string) => {
    setSelectedTrace(traceId)
    setSelectedNode(nodeId)
    requestMapFocus({ kind: 'node', nodeId })
  }

  const handleSelectTroncon = (traceId: string, startNodeId: string, pkStart: number, pkEnd: number, label: string) => {
    setSelectedTrace(traceId)
    setTableScope({ kind: 'troncon', pkStart, pkEnd, label, traceId, startNodeId })
    requestMapFocus({ kind: 'troncon', traceId, pkStart, pkEnd })
  }

  const startRenameVariant = (variant: Variant) => {
    setRenamingVariantId(variant.id)
    setRenameDraft(stripVariantPrefix(variant.name))
  }

  const handleConfirmRename = async (variantId: string) => {
    if (renamingVariantId !== variantId) return // deja confirme/annule entre-temps (Enter puis blur)
    setRenamingVariantId(null)
    const variant = variants.find((v) => v.id === variantId)
    if (!variant || !sessionId) return
    const newName = formatVariantName(renameDraft)
    if (!newName || newName === variant.name) return
    try {
      await api.patchVariant(sessionId, variantId, { name: newName })
      const state = await api.getProject(sessionId)
      setProjectState(state)
      setStatusMessage(`Variante renommée : ${newName}`)
    } catch (error) {
      setStatusMessage(`Erreur de renommage : ${(error as Error).message}`)
    }
  }

  const handlePatchOuvrage = async (payload: NodeSubmitPayload) => {
    if (!sessionId || !selectedVariantId || !editingOuvrage) return
    try {
      await api.patchNode(sessionId, selectedVariantId, editingOuvrage.id, {
        type: payload.type,
        name: payload.name,
        data: payload.data,
        injected_flow: payload.injectedFlow,
        withdrawn_flow: payload.withdrawnFlow,
      })
      await refreshNetwork()
      setStatusMessage('Ouvrage mis à jour')
    } catch (error) {
      setStatusMessage(`Erreur de modification : ${(error as Error).message}`)
    }
  }

  // "Supprimer" un ouvrage porte par une extremite structurelle ne peut pas retirer le noeud
  // lui-meme (il doit toujours ancrer le/les segments de la trace) : on le fait plutot revenir a
  // l'etat "non affecte" (placeholder invisible, cf. shared/nodeLabels.ts:isPlaceholderNode) —
  // consigne utilisateur : l'icone de suppression doit rester disponible meme sur le 1er ouvrage.
  const handleDeleteOuvrage = async (node: Node) => {
    if (!sessionId || !selectedVariantId) return
    try {
      if (isStructuralEndpoint(node, tracesById.get(node.trace_id))) {
        await api.patchNode(sessionId, selectedVariantId, node.id, { type: 'junction', name: '' })
        setStatusMessage('Ouvrage retiré (extrémité redevenue non affectée)')
      } else {
        await api.deleteNode(sessionId, selectedVariantId, node.id)
        setStatusMessage('Ouvrage supprimé')
      }
      await refreshNetwork()
    } catch (error) {
      setStatusMessage(`Erreur de suppression : ${(error as Error).message}`)
    }
  }

  // "Modifier" un troncon applique les MEMES parametres de calcul a TOUS ses segments (un troncon
  // peut en regrouper plusieurs si des jonctions/piquages transparents s'y trouvent). Materiau/DN/
  // Classe CALCULES ne sont pas saisis ici (payload sans material/dn/pressure_class, ils viennent
  // du calcul) — seule la contrainte forced_material/forced_dn (consigne utilisateur) l'est,
  // "" sur forced_material revenant au dimensionnement automatique (cf. TronconDialog).
  const handleSaveTroncon = async (hydraulics: TronconHydraulicValues) => {
    if (!sessionId || !selectedVariantId || !editingTroncon) return
    await Promise.all(
      editingTroncon.troncon.segment_ids.map((id) =>
        api.patchSegment(sessionId, selectedVariantId, id, {
          head_flow: hydraulics.headFlow,
          upstream_water_level_max: hydraulics.upstreamWaterLevelMax,
          upstream_water_level_min: hydraulics.upstreamWaterLevelMin,
          upstream_water_level_max_offset: hydraulics.upstreamWaterLevelMaxOffset,
          upstream_water_level_min_offset: hydraulics.upstreamWaterLevelMinOffset,
          min_pressure: hydraulics.minPressure,
          downstream_residual_pressure: hydraulics.downstreamResidualPressure,
          min_pressure_exclusion_m: hydraulics.minPressureExclusionM,
          max_velocity: hydraulics.maxVelocity,
          min_velocity: hydraulics.minVelocity,
          forced_material: hydraulics.forcedMaterial ?? '',
          forced_dn: hydraulics.forcedDn,
        }),
      ),
    )
    await refreshNetwork()
    setStatusMessage('Tronçon mis à jour')
  }

  // "Supprimer" un troncon = reinitialiser sa mise en donnees (Materiau/DN/Classe) aux valeurs
  // catalogue par defaut, sans toucher a la topologie (noeuds/segments restent en place) — un
  // troncon n'est pas une entite stockee independamment, seule sa mise en donnees est "supprimable".
  const handleResetTroncon = async (t: TronconGroup) => {
    if (!sessionId || !selectedVariantId) return
    try {
      await Promise.all(t.segment_ids.map((id) => api.resetSegment(sessionId, selectedVariantId, id)))
      await refreshNetwork()
      setStatusMessage('Tronçon réinitialisé (données par défaut)')
    } catch (error) {
      setStatusMessage(`Erreur de réinitialisation : ${(error as Error).message}`)
    }
  }

  const handleImportFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !sessionId) return

    setIsImporting(true)
    setImportProgress({ completed: 0, total: 0 })
    setStatusMessage(`Import de ${file.name} en cours : lecture du tracé...`)

    try {
      const started = await api.startTraceImport(sessionId, file)
      setImportProgress({ completed: 0, total: started.total_chunks })

      let job = await api.getImportJobStatus(sessionId, started.job_id)
      while (job.status === 'running') {
        setImportProgress({ completed: job.completed_chunks, total: job.total_chunks })
        setStatusMessage(
          `Import de ${file.name} en cours : altitudes ${job.completed_chunks} / ${job.total_chunks} lots...`,
        )
        await sleep(POLL_INTERVAL_MS)
        job = await api.getImportJobStatus(sessionId, started.job_id)
      }

      if (job.status === 'failed' || !job.trace) {
        throw new Error(job.error ?? "Échec de l'import")
      }

      const state = await api.getProject(sessionId)
      setProjectState(state)
      setSelectedTrace(job.trace.id)
      // Le trace est partage au niveau projet : chaque variante existante recoit son propre reseau
      // (routers/traces.py), mais ca ne fait pas partie de ProjectStateResponse — a recharger
      // explicitement pour que la table de la variante courante l'affiche.
      await refreshNetwork()
      setStatusMessage(`Trace importée : ${file.name} (${Math.round(job.trace.length)} m)`)
    } catch (error) {
      setStatusMessage(`Import KML/KMZ échoué : ${(error as Error).message}`)
    } finally {
      setIsImporting(false)
      setImportProgress(null)
    }
  }

  const percent =
    isImporting && importProgress && importProgress.total > 0
      ? Math.round((importProgress.completed / importProgress.total) * 100)
      : 0

  return (
    <div className="tree-body">
      <div
        className="tree-node--project"
        onClick={() => requestMapFocus({ kind: 'project' })}
        title="Zoomer la carte sur l'ensemble des tracés"
      >
        📁 {project.name}
      </div>

      <div className="tree-node--settings" onClick={onOpenProjectSettings}>
        ⚙️ Paramètres du projet
      </div>

      <div className="tree-group-header">
        <span className="tree-group-label">Tracés</span>
        <button
          type="button"
          className="tree-add-btn"
          disabled={isImporting}
          onClick={() => importInputRef.current?.click()}
          title="Importer une trace KML/KMZ (partagée entre toutes les variantes)"
          aria-label="Importer une trace KML/KMZ"
        >
          {isImporting ? '⏳ Import...' : '+ Ajouter'}
        </button>
        <input ref={importInputRef} type="file" accept=".kml,.kmz" hidden onChange={handleImportFile} />
      </div>

      {isImporting && (
        <div className="import-progress">
          <div className="progress-bar" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
            <div className="progress-bar-fill" style={{ width: `${percent}%` }} />
          </div>
          <span className="progress-bar-label">
            {importProgress && importProgress.total > 0
              ? `${importProgress.completed} / ${importProgress.total} lots (${percent}%)`
              : 'Démarrage...'}
          </span>
        </div>
      )}

      <ul className="tree-traces">
        {traces.map((trace) => (
          <li
            key={trace.id}
            className={trace.id === selectedTraceId && tableScope.kind === 'trace' ? 'selected' : ''}
            onClick={() => {
              setSelectedTrace(trace.id)
              requestMapFocus({ kind: 'trace', traceId: trace.id })
            }}
          >
            <span style={{ flex: 1 }}>{`Trace (${Math.round(trace.length)} m)`}</span>
            {trace.crossings != null && (
              <span className="trace-crossings-count" title="Traversées détectées (bouton sous PK, sur la carte)">
                {trace.crossings.length}
              </span>
            )}
          </li>
        ))}
        {!isImporting && traces.length === 0 && <li className="empty-hint">Aucune trace</li>}
      </ul>

      <div className="tree-group-header">
        <span className="tree-group-label">Variantes</span>
        <button
          type="button"
          className="tree-add-btn"
          onClick={onNewVariant}
          title="Ajouter une nouvelle variante (vierge, sans duplication)"
          aria-label="Ajouter une nouvelle variante"
        >
          + Ajouter
        </button>
      </div>
      {variants.map((variant) => {
        const isSelected = variant.id === selectedVariantId
        const showContent = isSelected && !contentHidden
        return (
          <div key={variant.id} className={`tree-variant ${isSelected ? 'selected' : ''}`}>
            <div className="tree-variant-header" onClick={() => setSelectedVariant(variant.id)}>
              {isSelected && (
                <button
                  type="button"
                  className="tree-chevron-btn"
                  title={contentHidden ? 'Afficher le contenu' : 'Masquer le contenu'}
                  aria-label={contentHidden ? 'Afficher le contenu' : 'Masquer le contenu'}
                  onClick={(e) => {
                    e.stopPropagation()
                    setContentHidden((v) => !v)
                  }}
                >
                  {contentHidden ? '▸' : '▾'}
                </button>
              )}
              {renamingVariantId === variant.id ? (
                <span className="tree-variant-title tree-rename-field" onClick={(e) => e.stopPropagation()}>
                  <span className="tree-rename-prefix">{VARIANT_PREFIX}</span>
                  <input
                    autoFocus
                    className="tree-rename-input"
                    value={renameDraft}
                    onChange={(e) => setRenameDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleConfirmRename(variant.id)
                      if (e.key === 'Escape') setRenamingVariantId(null)
                    }}
                    onBlur={() => handleConfirmRename(variant.id)}
                  />
                </span>
              ) : (
                <span
                  className="tree-variant-title"
                  onDoubleClick={(e) => {
                    e.stopPropagation()
                    startRenameVariant(variant)
                  }}
                >
                  {variant.name}
                </span>
              )}
              <button
                type="button"
                className="tree-row-btn"
                title="Renommer la variante"
                aria-label="Renommer la variante"
                onClick={(e) => {
                  e.stopPropagation()
                  startRenameVariant(variant)
                }}
              >
                ✎
              </button>
              <button
                type="button"
                className="tree-row-btn"
                title="Dupliquer la variante"
                aria-label="Dupliquer la variante"
                onClick={(e) => {
                  e.stopPropagation()
                  onDuplicateVariant(variant.id)
                }}
              >
                ⧉
              </button>
              <button
                type="button"
                className="tree-row-btn tree-row-btn--danger"
                title="Supprimer la variante"
                aria-label="Supprimer la variante"
                onClick={(e) => {
                  e.stopPropagation()
                  onRequestDeleteVariant(variant.id)
                }}
              >
                ✕
              </button>
            </div>

            {showContent && (
              <>
                <div className="tree-group-label">Ouvrages</div>
                <ul className="tree-traces">
                  {ouvrageNodes.map((node) => (
                    <li key={node.id} className={node.id === selectedNodeId ? 'selected' : ''}>
                      <span
                        className={`tree-item-main ${isOuvrageDataDefined(node) ? 'tree-item-defined' : ''}`}
                        onClick={() => handleSelectOuvrage(node.id, node.trace_id)}
                        title={
                          isOuvrageDataDefined(node)
                            ? 'Mise en données renseignée'
                            : 'Mise en données pas encore renseignée'
                        }
                      >
                        <NodeBadge node={node} />
                        {nodeDisplayLabel(node)}
                      </span>
                      <span className="tree-item-actions">
                        <button
                          type="button"
                          className="tree-row-btn"
                          title="Modifier l'ouvrage"
                          aria-label="Modifier l'ouvrage"
                          onClick={(e) => {
                            e.stopPropagation()
                            setEditingOuvrage(node)
                          }}
                        >
                          ✎
                        </button>
                        <button
                          type="button"
                          className="tree-row-btn tree-row-btn--danger"
                          title="Supprimer l'ouvrage"
                          aria-label="Supprimer l'ouvrage"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDeleteOuvrage(node)
                          }}
                        >
                          ✕
                        </button>
                      </span>
                    </li>
                  ))}
                  {ouvrageNodes.length === 0 && <li className="empty-hint">Aucun ouvrage</li>}
                </ul>

                <div className="tree-group-label">Tronçons</div>
                <ul className="tree-traces">
                  {troncons.map((t, i) => {
                    const startNode = nodesById.get(t.start_node_id)
                    const endNode = nodesById.get(t.end_node_id)
                    const label = `Tr${i + 1} ${startNode ? nodeDisplayLabel(startNode) : '?'} => ${endNode ? nodeDisplayLabel(endNode) : '?'}`
                    const isTronconSelected =
                      tableScope.kind === 'troncon' && tableScope.pkStart === t.pk_start && tableScope.pkEnd === t.pk_end
                    const regime = tronconRegime(t, nodesById)
                    const forced = tronconIsForced(t, segmentsById)
                    return (
                      <li key={`${t.start_node_id}-${t.end_node_id}`} className={isTronconSelected ? 'selected' : ''}>
                        <span
                          className={`tree-item-main ${forced ? 'tree-item-defined' : ''}`}
                          onClick={() => handleSelectTroncon(t.trace_id, t.start_node_id, t.pk_start, t.pk_end, label)}
                        >
                          <span
                            className="troncon-regime-glyph"
                            style={{ color: TRONCON_REGIME_COLOR[regime] }}
                            title={
                              regime === 'gravitaire'
                                ? 'Gravitaire'
                                : regime === 'refoulement'
                                  ? 'Refoulement'
                                  : 'Régime indéterminé (ouvrages non définis ou dénivelé négligeable)'
                            }
                          >
                            {TRONCON_REGIME_GLYPH[regime]}
                          </span>
                          {label}
                          <span
                            className={`troncon-data-dot ${forced ? 'defined' : ''}`}
                            title={forced ? 'Matériau/DN renseignés' : 'Matériau/DN par défaut (non renseignés)'}
                          />
                        </span>
                        <span className="tree-item-actions">
                          <button
                            type="button"
                            className="tree-row-btn"
                            title="Modifier les paramètres de calcul du tronçon"
                            aria-label="Modifier le tronçon"
                            onClick={(e) => {
                              e.stopPropagation()
                              setEditingTroncon({ troncon: t, label })
                            }}
                          >
                            ✎
                          </button>
                          <button
                            type="button"
                            className="tree-row-btn tree-row-btn--danger"
                            title="Réinitialiser le tronçon (données par défaut)"
                            aria-label="Réinitialiser le tronçon"
                            disabled={!forced}
                            onClick={(e) => {
                              e.stopPropagation()
                              handleResetTroncon(t)
                            }}
                          >
                            ✕
                          </button>
                        </span>
                      </li>
                    )
                  })}
                  {troncons.length === 0 && <li className="empty-hint">Aucun tronçon</li>}
                </ul>
              </>
            )}
          </div>
        )
      })}

      {editingOuvrage && (
        <NodeDialog
          mode="edit"
          pk={editingOuvrage.pk}
          existingNodes={nodes}
          initialType={editingOuvrage.type as CreatableNodeType}
          initialName={editingOuvrage.name}
          initialData={editingOuvrage.data}
          initialInjectedFlow={editingOuvrage.injected_flow}
          initialWithdrawnFlow={editingOuvrage.withdrawn_flow}
          excludeNodeId={editingOuvrage.id}
          onClose={() => setEditingOuvrage(null)}
          onSubmit={handlePatchOuvrage}
        />
      )}

      {editingTroncon &&
        (() => {
          const firstSegmentId = editingTroncon.troncon.segment_ids[0]
          const firstSegment = firstSegmentId ? segmentsById.get(firstSegmentId) : undefined
          // Tronçon precedent (le plus proche en amont, meme trace) — sert a heriter le debit de
          // tete quand celui-ci n'est pas encore saisi (consigne utilisateur : "de même pour les
          // tronçons"). Les autres defauts (pression min/résiduelle/vitesse max) viennent des
          // Préférences plutôt que du tronçon precedent (valeurs plus "normes" que "propagees").
          const precedingTroncon = troncons
            .filter((t) => t.trace_id === editingTroncon.troncon.trace_id && t.pk_end <= editingTroncon.troncon.pk_start + 1e-6)
            .sort((a, b) => b.pk_end - a.pk_end)[0]
          const precedingHeadFlow = precedingTroncon
            ? segmentsById.get(precedingTroncon.segment_ids[0])?.head_flow ?? undefined
            : undefined
          // Débit de L'OUVRAGE AMONT lui-même (consigne utilisateur) — seuls les réservoirs (stockage/
          // mise en charge) portent un champ Débit propre (cf. ouvrageFields.ts) ; priorité sur le
          // débit du tronçon précédent (moins directement lié à ce tronçon-ci).
          const upstreamOuvrageFlow = (() => {
            const upstreamNode = nodesById.get(editingTroncon.troncon.start_node_id)
            const flow = upstreamNode?.data?.flow
            return typeof flow === 'number' ? flow : undefined
          })()
          // Valeur par defaut de la zone d'exclusion (consigne utilisateur : "estimée à partir de
          // celle dans préférences"), tant que ce tronçon n'a pas encore la sienne propre —
          // pourcentage des Preferences converti en metres sur la longueur REELLE de ce tronçon.
          const defaultExclusionM =
            preferences?.min_pressure_exclusion_pct != null
              ? Math.round(
                  (preferences.min_pressure_exclusion_pct / 100) *
                    (editingTroncon.troncon.pk_end - editingTroncon.troncon.pk_start),
                )
              : undefined
          return (
            <TronconDialog
              label={editingTroncon.label}
              regime={tronconRegime(editingTroncon.troncon, nodesById)}
              startNodeGroundZ={nodesById.get(editingTroncon.troncon.start_node_id)?.z}
              initialHydraulics={{
                headFlow: firstSegment?.head_flow ?? upstreamOuvrageFlow ?? precedingHeadFlow ?? undefined,
                upstreamWaterLevelMax: firstSegment?.upstream_water_level_max ?? undefined,
                upstreamWaterLevelMin: firstSegment?.upstream_water_level_min ?? undefined,
                upstreamWaterLevelMaxOffset: firstSegment?.upstream_water_level_max_offset ?? undefined,
                upstreamWaterLevelMinOffset: firstSegment?.upstream_water_level_min_offset ?? undefined,
                minPressure: firstSegment?.min_pressure ?? preferences?.default_min_pressure ?? undefined,
                downstreamResidualPressure:
                  firstSegment?.downstream_residual_pressure ?? preferences?.default_downstream_residual_pressure ?? undefined,
                minPressureExclusionM: firstSegment?.min_pressure_exclusion_m ?? defaultExclusionM,
                maxVelocity: firstSegment?.max_velocity ?? preferences?.default_max_velocity ?? undefined,
                minVelocity: firstSegment?.min_velocity ?? preferences?.default_min_velocity ?? undefined,
                forcedMaterial: firstSegment?.forced_material ?? undefined,
                forcedDn: firstSegment?.forced_dn ?? undefined,
              }}
              pipeCatalog={pipeCatalog}
              sessionId={sessionId ?? ''}
              variantId={selectedVariantId ?? ''}
              segmentIds={editingTroncon.troncon.segment_ids}
              initialConstraints={firstSegment?.constraints ?? []}
              onConstraintsSaved={refreshNetwork}
              onClose={() => setEditingTroncon(null)}
              onSubmit={handleSaveTroncon}
            />
          )
        })()}
    </div>
  )
}
