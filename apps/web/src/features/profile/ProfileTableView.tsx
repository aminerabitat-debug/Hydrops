// "Profil et table de donnees occupent le meme panneau et sont alternes par onglet/bouton
// integre" (cdc §4) — bouton bascule Graphique/Data + cases a cocher des courbes, inspires de
// la page de reference fournie par l'utilisateur.

import { useEffect, useMemo, useState } from 'react'

import { api } from '../../shared/apiClient'
import { findPrecedingOuvrage } from '../../shared/ouvrageFields'
import { runCalculationJob } from '../../shared/pollCalcJob'
import { useAppStore } from '../../state/store'
import { isStructuralEndpoint as isStructuralEndpointOf } from '../../shared/types'
import type { CreatableNodeType, Node, PipeCatalogRow } from '../../shared/types'
import { useCalcConfirmDialog } from '../../app/CalcConfirmDialog'
import { ProgressBar } from '../../app/ProgressBar'
import { DataTable } from '../table/DataTable'
import { NodeDialog, type NodeSubmitPayload } from './NodeDialog'
import { CURVE_COLORS, ProfileChart, type SelectedPipeSpan } from './ProfileChart'

// Un ajout au PK visé (pas de noeud reel a ce PK) declenche POST .../nodes ; l'affectation d'un
// placeholder d'extremite (noeud "junction" deja present, plus jamais montre a l'utilisateur comme
// tel — consigne utilisateur, cf. shared/nodeLabels.ts:isPlaceholderNode) declenche PATCH sur ce
// noeud existant a la place — les deux se presentent comme un dialogue de CREATION identique.
interface PendingAdd {
  pk: number
  placeholderNodeId?: string
}

function formatDistance(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toFixed(2)} km` : `${Math.round(meters)} m`
}

function formatSignedElevation(meters: number): string {
  const rounded = Math.round(meters)
  return rounded > 0 ? `+${rounded} m` : `${rounded} m`
}

export function ProfileTableView() {
  const [mode, setMode] = useState<'graph' | 'data'>('graph')
  const [showTerrain, setShowTerrain] = useState(true)
  // Ligne piezometrique (consigne utilisateur) : affichee des qu'un troncon est calcule, case a
  // cocher pour la masquer/l'afficher, positionnee entre Terrain et le bouton + Nœud.
  const [showPiezo, setShowPiezo] = useState(true)
  // Enveloppe PMS (consigne utilisateur) : altitude terrain + PMS (mCE) de la conduite en place a
  // chaque point — necessite le catalogue (PMS par materiau/DN/classe), charge une fois ici (meme
  // pattern que ConduitesWindow.tsx), pas besoin de le tenir a jour en temps reel (catalogue rarement
  // modifie en cours de session).
  const [showPms, setShowPms] = useState(true)
  // Lignes hydrostatiques min et max (consigne utilisateur : deux cases separees) — cotes
  // constantes du reservoir amont des tronçons gravitaires (Segment.upstream_water_level_max/min).
  const [showHydrostaticMax, setShowHydrostaticMax] = useState(true)
  const [showHydrostaticMin, setShowHydrostaticMin] = useState(true)
  const [pipeCatalog, setPipeCatalog] = useState<PipeCatalogRow[]>([])
  const [addNodeMode, setAddNodeMode] = useState(false)
  // Bouton d'info (consigne utilisateur) : affiche l'ID/PK/altitude du piquet survolé — deplace
  // dans cette barre d'outils (a droite de "+ Nœud") pour ne plus chevaucher la bande de
  // caracteristiques de conduite, desormais au-dessus du graphique.
  const [infoMode, setInfoMode] = useState(false)
  // Zoom du profil graphique (consigne utilisateur : "prevoir la possibilite de zoomer... et un
  // bouton de reinitialisation du zoom"), pilote a la molette dans ProfileChart mais l'etat vit
  // ici pour exposer le bouton de reinitialisation a cote du bouton d'info. `null` = pas de zoom
  // manuel, la plage affichee reste celle deduite de tableScope (trace entiere ou troncon
  // selectionne, cf. ProfileChart).
  const [zoomRange, setZoomRange] = useState<{ min: number; max: number } | null>(null)
  // Selection des bandes "guitare" en vue d'une homogeneisation de classe (consigne utilisateur) —
  // controlee ici (comme zoomRange) pour exposer le bouton "Homogénéisation des classes" a cote de
  // "Réinitialiser le zoom", alors que la selection elle-meme se pilote depuis ProfileChart (clics).
  const [selectedSpans, setSelectedSpans] = useState<SelectedPipeSpan[]>([])
  const [homogenizing, setHomogenizing] = useState(false)
  const [calculating, setCalculating] = useState(false)
  const [calcProgress, setCalcProgress] = useState<{ completed: number; total: number } | null>(null)
  const { dialog: calcConfirmDialog, onNeedsConfirmation } = useCalcConfirmDialog()

  useEffect(() => {
    api.listConduites().then(setPipeCatalog).catch(() => setPipeCatalog([]))
  }, [])

  const [pendingAdd, setPendingAdd] = useState<PendingAdd | null>(null)
  const [editingNode, setEditingNode] = useState<Node | null>(null)

  const sessionId = useAppStore((s) => s.sessionId)
  const project = useAppStore((s) => s.project)
  const selectedVariantId = useAppStore((s) => s.selection.selectedVariantId)
  const nodes = useAppStore((s) => s.nodes)
  const segments = useAppStore((s) => s.segments)
  const refreshNetwork = useAppStore((s) => s.refreshNetwork)
  const setStatusMessage = useAppStore((s) => s.setStatusMessage)
  const traces = useAppStore((s) => s.traces)
  const troncons = useAppStore((s) => s.troncons)
  const showCrossings = useAppStore((s) => s.showCrossings)
  const setShowCrossings = useAppStore((s) => s.setShowCrossings)
  const selectedTraceId = useAppStore((s) => s.selection.selectedTraceId)
  const tableScope = useAppStore((s) => s.selection.tableScope)
  const profileFocusRequest = useAppStore((s) => s.profileFocusRequest)
  const requestProfileFocus = useAppStore((s) => s.requestProfileFocus)
  const trace = traces.find((t) => t.id === selectedTraceId) ?? traces[0]
  const profile = trace?.elevation_profile

  // Synchronisation zoom carte -> profil (consigne utilisateur, cf. MapView.tsx qui emet cette
  // demande en Vue combinée) — reutilise le meme setter que le zoom manuel a la molette.
  useEffect(() => {
    if (!profileFocusRequest) return
    setZoomRange({ min: profileFocusRequest.pkStart, max: profileFocusRequest.pkEnd })
  }, [profileFocusRequest])

  // Synchronisation zoom graphique -> table (consigne utilisateur : "quand je zoome sur le
  // graphique, je veux qu'en basculant sur le tableau ce dernier se positionne autour des piquets
  // du zoom") — reutilise le mecanisme de defilement de DataTable deja construit pour la synchro
  // carte -> table (meme store field, cf. MapView.tsx). Ne se declenche qu'au BASCULEMENT vers le
  // mode Data (pas a chaque changement de zoomRange en cours de Mode Graphique), avec la plage
  // actuellement zoomee — rien a faire si aucun zoom manuel n'est en cours.
  useEffect(() => {
    if (mode === 'data' && zoomRange) {
      requestProfileFocus({ pkStart: zoomRange.min, pkEnd: zoomRange.max })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

  // Changer de trace ou de troncon selectionne (arborescence) invalide un zoom manuel en cours —
  // la plage n'a plus forcement de sens sur le nouveau profil affiche. Idem pour une selection de
  // bandes "guitare" en cours (homogeneisation).
  useEffect(() => {
    setZoomRange(null)
    setSelectedSpans([])
  }, [selectedTraceId, tableScope])

  // Les courbes derivees du calcul (piezo/PMS/hydrostatiques) et la bande de caracteristiques ne
  // doivent apparaitre qu'une fois un calcul reussi pour cette trace, et redisparaitre des qu'une
  // modification (ouvrage ou tronçon) les invalide (consigne utilisateur) — `Segment.velocity !=
  // null` est le meme signal fiable que celui utilise par DataTable/ProfileChart.
  const hasCalculatedData = useMemo(() => {
    if (!trace) return false
    const traceNodeIds = new Set(nodes.filter((n) => n.trace_id === trace.id).map((n) => n.id))
    return segments.some((s) => traceNodeIds.has(s.upstream_node_id) && s.velocity != null)
  }, [segments, nodes, trace])

  const handleSubmitPendingAdd = async (payload: NodeSubmitPayload) => {
    if (!sessionId || !selectedVariantId || !trace || pendingAdd == null) return
    const { type, name, data, injectedFlow, withdrawnFlow, existing, phaseId } = payload
    if (pendingAdd.placeholderNodeId) {
      // Le PK visé porte deja un placeholder d'extremite (jamais montre comme tel a
      // l'utilisateur) : on l'affecte au lieu d'en creer un second au meme PK (rejete par le
      // backend), sans jamais afficher de "Jonction" par defaut (consigne utilisateur).
      await api.patchNode(sessionId, selectedVariantId, pendingAdd.placeholderNodeId, {
        type,
        name,
        data,
        injected_flow: injectedFlow,
        withdrawn_flow: withdrawnFlow,
        existing,
        phase_id: phaseId ?? '',
      })
    } else {
      await api.addNode(sessionId, selectedVariantId, trace.id, pendingAdd.pk, {
        type,
        name,
        data,
        injected_flow: injectedFlow,
        withdrawn_flow: withdrawnFlow,
        existing,
        phase_id: phaseId ?? undefined,
      })
    }
    await refreshNetwork()
    setStatusMessage(`Nœud ajouté au PK ${Math.round(pendingAdd.pk)} m`, 'success')
  }

  const handlePatchNode = async (payload: NodeSubmitPayload) => {
    if (!sessionId || !selectedVariantId || !editingNode) return
    await api.patchNode(sessionId, selectedVariantId, editingNode.id, {
      type: payload.type,
      name: payload.name,
      data: payload.data,
      injected_flow: payload.injectedFlow,
      withdrawn_flow: payload.withdrawnFlow,
      existing: payload.existing,
      phase_id: payload.phaseId ?? '',
    })
    // Deplacement (consigne utilisateur) : endpoint dedie, deja invalidant le calcul des tronçons
    // voisins cote backend (PATCH .../position) — l'utilisateur doit relancer "Calculer".
    if (payload.newPk != null) {
      const moveResult = await api.patchNodePosition(sessionId, selectedVariantId, editingNode.id, payload.newPk)
      if (moveResult.needs_level_confirmation) {
        setStatusMessage(
          "Ouvrage déplacé — sa cote (saisie en valeur absolue) n'a pas été ajustée automatiquement : " +
            "vérifiez-la dans \"Modifier le tronçon\".",
          'warning',
        )
        await refreshNetwork()
        return
      }
    }
    await refreshNetwork()
    setStatusMessage('Nœud mis à jour', 'success')
  }

  // Une extremite structurelle de trace (PK 0 ou longueur) ne peut pas etre supprimee — cf.
  // apps/api/hydrops_api/routers/network.py:_is_structural_endpoint (meme tolerance).
  const isStructuralEndpoint = (node: Node): boolean => isStructuralEndpointOf(node, trace)

  // "Supprimer" un ouvrage porte par une extremite structurelle ne peut pas retirer le noeud
  // lui-meme (il doit toujours ancrer le/les segments de la trace) : on le fait plutot revenir a
  // l'etat "non affecte" (placeholder invisible, cf. shared/nodeLabels.ts:isPlaceholderNode) —
  // consigne utilisateur : l'icone de suppression doit rester disponible meme sur le 1er ouvrage.
  const handleDeleteNode = async (node: Node) => {
    if (!sessionId || !selectedVariantId) return
    if (isStructuralEndpoint(node)) {
      await api.patchNode(sessionId, selectedVariantId, node.id, { type: 'junction', name: '' })
      setStatusMessage('Ouvrage retiré (extrémité redevenue non affectée)', 'success')
    } else {
      await api.deleteNode(sessionId, selectedVariantId, node.id)
      setStatusMessage('Nœud supprimé', 'success')
    }
    await refreshNetwork()
  }

  // Contrainte d'homogeneisation active correspondant EXACTEMENT a la selection courante (memes
  // bornes PK, meme segment reel) — determine si le bouton doit proposer "Annuler" plutot que
  // "Homogénéiser" (consigne utilisateur : le bouton bascule tant que la selection n'a pas changé).
  const activeHomogenization = useMemo(() => {
    if (selectedSpans.length < 2) return null
    const segmentId = selectedSpans[0].segmentId
    if (selectedSpans.some((s) => s.segmentId !== segmentId)) return null
    const segment = segments.find((s) => s.id === segmentId)
    if (!segment) return null
    const pkStart = Math.min(...selectedSpans.map((s) => s.pkStart))
    const pkEnd = Math.max(...selectedSpans.map((s) => s.pkEnd))
    const constraint = (segment.constraints ?? []).find(
      (c) =>
        c.source === 'homogenization' &&
        Math.abs((c.pk_start ?? segment.pk_start) - pkStart) < 1e-6 &&
        Math.abs((c.pk_end ?? segment.pk_end) - pkEnd) < 1e-6,
    )
    return constraint ? { segment, pkStart, pkEnd, constraintId: constraint.id } : null
  }, [selectedSpans, segments])

  // `explicitScope`, quand fourni, prime sur `tableScope` (consigne utilisateur : l'homogénéisation
  // ne doit recalculer QUE le tronçon qu'elle modifie, jamais tout le reseau juste parce que la vue
  // affichee au moment du clic n'etait pas scopee a un tronçon — cf. handleHomogenize).
  const runScopedCalcul = async (explicitScope?: { traceId: string; startNodeId: string }) => {
    if (!sessionId || !selectedVariantId) return
    const scope = explicitScope ?? (tableScope.kind === 'troncon' ? { traceId: tableScope.traceId, startNodeId: tableScope.startNodeId } : undefined)
    setCalculating(true)
    setCalcProgress(null)
    try {
      const result = await runCalculationJob(sessionId, selectedVariantId, scope, {
        onProgress: (completed, total) => setCalcProgress({ completed, total }),
        onNeedsConfirmation,
      })
      if (result === null) {
        setStatusMessage('Calcul annulé', 'info')
        return
      }
      await refreshNetwork()
      setStatusMessage(
        result.alerts.length > 0 ? `Calcul terminé avec ${result.alerts.length} alerte(s)` : 'Calcul terminé sans alerte',
        result.alerts.length > 0 ? 'warning' : 'success',
        result.alerts.length > 0
          ? `Calcul terminé avec ${result.alerts.length} alerte(s) :\n${result.alerts.map((a) => `• ${a}`).join('\n')}`
          : undefined,
      )
    } catch (error) {
      setStatusMessage(`Calcul impossible : ${(error as Error).message}`, 'error')
    } finally {
      setCalculating(false)
      setCalcProgress(null)
    }
  }

  // "Homogénéisation des classes" (consigne utilisateur) : generalise la classe de pression la
  // plus elevee parmi la selection sur toute son etendue (union des PK), sous forme d'une
  // contrainte dediee (source="homogenization", cf. panneau "Contraintes" de la fenetre Tronçon) —
  // rejouable/annulable en revenant sur EXACTEMENT la meme selection (cf. activeHomogenization).
  // Le tronçon REELLEMENT concerne par ce segment (consigne utilisateur : l'homogénéisation ne
  // doit jamais recalculer un tronçon qui n'y a pas participe) — independant de ce que la vue
  // affiche au moment du clic (`tableScope`), qui peut etre "trace entiere"/"tout" et declencherait
  // sinon un recalcul complet du reseau via `runScopedCalcul`'s repli sur `tableScope`.
  const tronconScopeForSegment = (segmentId: string) => {
    const troncon = troncons.find((t) => t.segment_ids.includes(segmentId))
    return troncon ? { traceId: troncon.trace_id, startNodeId: troncon.start_node_id } : undefined
  }

  const handleHomogenize = async () => {
    if (!sessionId || !selectedVariantId) return
    setHomogenizing(true)
    try {
      if (activeHomogenization) {
        const remaining = (activeHomogenization.segment.constraints ?? []).filter(
          (c) => c.id !== activeHomogenization.constraintId,
        )
        await api.putSegmentConstraints(sessionId, selectedVariantId, activeHomogenization.segment.id, remaining)
        await runScopedCalcul(tronconScopeForSegment(activeHomogenization.segment.id))
        return
      }
      if (selectedSpans.length < 2) return
      const segmentId = selectedSpans[0].segmentId
      if (selectedSpans.some((s) => s.segmentId !== segmentId)) {
        setStatusMessage("Sélectionnez des bandes du même tronçon pour l'homogénéisation.", 'error')
        return
      }
      // Consigne utilisateur : l'homogénéisation ne généralise QUE la classe de pression — une
      // sélection dont le matériau ou le DN diffère d'une bande à l'autre serait incohérente
      // (quel matériau/DN garder ?), donc rejetée avant tout appel API.
      const { material, dn } = selectedSpans[0]
      if (selectedSpans.some((s) => s.material !== material || s.dn !== dn)) {
        setStatusMessage(
          "Homogénéisation impossible : la sélection contient des matériaux ou des DN différents (seule la classe de pression peut être généralisée).",
          'error',
        )
        return
      }
      // Consigne utilisateur : "les segments de tronçons qui n'ont pas subi l'homogénéisation"
      // changeaient quand meme — la contrainte posee couvre l'UNION [min(pkStart), max(pkEnd)] de
      // la selection ; avec un Ctrl+clic sur deux bandes NON adjacentes, cette union "pontait" une
      // bande intermediaire jamais selectionnee (ex. une zone materiau different posee
      // manuellement, ou simplement un choix auto-dimensionne different) et l'ecrasait quand meme.
      // On exige donc une selection CONTIGUE (triee par PK, chaque bande enchainant exactement sur
      // la suivante) — l'union coincide alors exactement avec les bandes reellement selectionnees,
      // rien d'autre ne peut se trouver "a l'interieur" par surprise.
      const sortedSpans = [...selectedSpans].sort((a, b) => a.pkStart - b.pkStart)
      const hasGap = sortedSpans.some((s, i) => i > 0 && Math.abs(s.pkStart - sortedSpans[i - 1].pkEnd) > 1e-6)
      if (hasGap) {
        setStatusMessage(
          "Homogénéisation impossible : la sélection doit être une plage continue (pas de bande non sélectionnée entre deux bandes choisies).",
          'error',
        )
        return
      }
      const segment = segments.find((s) => s.id === segmentId)
      if (!segment) return
      const pkStart = Math.min(...selectedSpans.map((s) => s.pkStart))
      const pkEnd = Math.max(...selectedSpans.map((s) => s.pkEnd))
      const highest = selectedSpans.reduce((a, b) => ((b.pms ?? -Infinity) > (a.pms ?? -Infinity) ? b : a))
      // Les contraintes existantes qui ont produit les bandes selectionnees (typiquement les
      // contraintes manuelles de classe sur ces plages) chevauchent forcement [pkStart, pkEnd] —
      // les laisser en place ferait perdre a la resolution "plage la plus etroite gagne"
      // (routers/network.py:_resolve_constraints_at_pk) : une contrainte plus etroite que la
      // nouvelle contrainte d'homogeneisation continuerait de s'appliquer sur sa propre sous-plage,
      // laissant la classe NON uniforme a l'interieur meme de la zone qu'on vient d'homogeneiser.
      // On retire donc toute contrainte dont la plage chevauche [pkStart, pkEnd] avant d'ajouter la
      // nouvelle — seule la contrainte d'homogeneisation gouverne alors toute cette etendue.
      const remainingConstraints = (segment.constraints ?? []).filter((c) => {
        const cStart = c.pk_start ?? segment.pk_start
        const cEnd = c.pk_end ?? segment.pk_end
        return cEnd <= pkStart || cStart >= pkEnd
      })
      // Consigne utilisateur : "le seul cas où le DN peut changer... est quand on utilise un
      // matériau où le DI dépend de la classe" — donc forcer EXPLICITEMENT material+dn (deja
      // valides identiques sur toute la selection, cf. verification ci-dessus) EN PLUS de la
      // classe, pas seulement la classe seule. Laisser material/dn a null delegue au moteur une
      // resolution "partiellement forcee" (auto-dimensionnement + telescopage), qui peut alors
      // faire varier le DN — y compris HORS de la zone homogeneisee, le telescopage appliquant une
      // contrainte de monotonie sur tout le tronçon, pas seulement sur la plage forcee. En forçant
      // aussi material+dn ici, la resolution passe par le lookup catalogue EXACT (materiau+DN+
      // classe, cf. hydrops_engine._resolve_forced_pipe) : le DN ne bouge plus du tout, seul le DI
      // peut varier avec la classe si le catalogue le prevoit pour ce materiau.
      await api.putSegmentConstraints(sessionId, selectedVariantId, segmentId, [
        ...remainingConstraints,
        {
          material, dn, pressure_class: highest.pressureClass, pk_start: pkStart, pk_end: pkEnd,
          is_existing: false, phase_id: null, source: 'homogenization',
        },
      ])
      await runScopedCalcul(tronconScopeForSegment(segmentId))
    } catch (error) {
      setStatusMessage(`Homogénéisation impossible : ${(error as Error).message}`, 'error')
    } finally {
      setHomogenizing(false)
    }
  }

  const metrics = useMemo(() => {
    if (!trace || !profile || profile.raw.length === 0) return null
    const rawElevations = profile.raw.map((p) => p.z)
    // Denivele = difference d'altitude nette entre le depart et l'arrivee (Z_arrivee - Z_depart),
    // pas un cumul de montees façon randonnee : c'est la charge statique disponible qui compte
    // pour un dimensionnement gravitaire, pas la somme des ondulations du terrain. On utilise le
    // brut (mesure directe aux deux extremites, pas affectee par le choix de fenetre de lissage).
    const netElevationChange = rawElevations[rawElevations.length - 1] - rawElevations[0]
    return {
      distance: formatDistance(trace.length),
      min: Math.round(Math.min(...rawElevations)),
      max: Math.round(Math.max(...rawElevations)),
      netChange: netElevationChange,
    }
  }, [trace, profile])

  return (
    <>
      <div className="profile-header">
        <div className="profile-title-group">
          <h2>Profil en long</h2>
          <button
            type="button"
            className="btn-toggle"
            onClick={() => setMode((m) => (m === 'graph' ? 'data' : 'graph'))}
          >
            {mode === 'graph' ? 'Mode Data' : 'Mode Graphique'}
          </button>
        </div>
        <div className="metrics">
          <div className="metric">Distance : {metrics ? metrics.distance : '—'}</div>
          <div className="metric">Altitude min : {metrics ? `${metrics.min} m` : '—'}</div>
          <div className="metric">Altitude max : {metrics ? `${metrics.max} m` : '—'}</div>
          <div className="metric" title="Altitude arrivée − altitude départ (charge statique gravitaire disponible)">
            Dénivelé (départ→arrivée) : {metrics ? formatSignedElevation(metrics.netChange) : '—'}
          </div>
        </div>
      </div>
      <div className="profile-subheader">
        <div className="metrics curve-controls">
          <button
            type="button"
            className={`metric btn-toggle-node ${addNodeMode ? 'active' : ''}`}
            onClick={() => setAddNodeMode((v) => !v)}
            title={
              mode === 'graph'
                ? "Cliquer sur le profil pour ajouter un nœud au PK visé ; cliquer sur un nœud existant l'édite (type/nom, y compris une extrémité)"
                : "Cliquer sur une ligne du tableau (sans nœud) pour lui ajouter un nœud, y compris un piquet d'extrémité"
            }
          >
            {addNodeMode
              ? mode === 'graph'
                ? '✓ + Nœud (cliquer sur le profil)'
                : '✓ + Nœud (cliquer sur une ligne)'
              : '+ Nœud'}
          </button>
          {mode === 'graph' && (
            <button
              type="button"
              className={`metric btn-toggle-node ${infoMode ? 'active' : ''}`}
              onClick={() => setInfoMode((v) => !v)}
              title="Afficher l'ID et le PK du piquet survolé"
              aria-label="Afficher l'ID et le PK du piquet survolé"
            >
              ℹ
            </button>
          )}
          {mode === 'graph' && (
            <button
              type="button"
              className="metric btn-toggle-node"
              onClick={() => setZoomRange(null)}
              disabled={zoomRange == null}
              title="Réinitialiser le zoom du profil (molette pour zoomer/dézoomer)"
              aria-label="Réinitialiser le zoom du profil"
            >
              ⤢ Réinitialiser le zoom
            </button>
          )}
          {mode === 'graph' && (
            <button
              type="button"
              className="metric btn-toggle-node"
              onClick={handleHomogenize}
              disabled={homogenizing || (activeHomogenization == null && selectedSpans.length < 2)}
              title={
                activeHomogenization
                  ? "Annuler cette homogénéisation de classe"
                  : "Sélectionner au moins 2 bandes (Ctrl/Shift+clic) puis cliquer pour généraliser la classe de pression la plus élevée sur toute la sélection"
              }
            >
              {activeHomogenization ? "Annulation de l'homogénéisation" : 'Homogénéisation des classes'}
            </button>
          )}
          {calculating && (
            <ProgressBar
              label="Calcul en cours"
              percent={calcProgress && calcProgress.total > 0 ? Math.round((calcProgress.completed / calcProgress.total) * 100) : 0}
            />
          )}
        </div>
      </div>
      <div className="profile-content">
        {mode === 'graph' ? (
          <ProfileChart
            showTerrain={showTerrain}
            showPiezo={showPiezo}
            showPms={showPms}
            showHydrostaticMax={showHydrostaticMax}
            showHydrostaticMin={showHydrostaticMin}
            showCrossings={showCrossings}
            pipeCatalog={pipeCatalog}
            addNodeMode={addNodeMode}
            infoMode={infoMode}
            zoomRange={zoomRange}
            onZoomChange={setZoomRange}
            selectedSpans={selectedSpans}
            onSelectedSpansChange={setSelectedSpans}
            onAddNode={(pk) => setPendingAdd({ pk })}
            onEditNode={(node) => setEditingNode(node)}
            onAssignNode={(node) => setPendingAdd({ pk: node.pk, placeholderNodeId: node.id })}
          />
        ) : (
          <DataTable
            onAddNode={(pk) => setPendingAdd({ pk })}
            onEditNode={(node) => setEditingNode(node)}
            onAssignNode={(node) => setPendingAdd({ pk: node.pk, placeholderNodeId: node.id })}
            onDeleteNode={handleDeleteNode}
            addNodeMode={addNodeMode}
          />
        )}
      </div>
      <div className="profile-legend-footer">
        <label className="metric">
          <input type="checkbox" checked={showTerrain} onChange={(e) => setShowTerrain(e.target.checked)} />
          <span className="curve-color-swatch" style={{ background: CURVE_COLORS.terrain }} />
          <span>Terrain</span>
        </label>
        {hasCalculatedData && (
          <>
            <label className="metric" title="Cote piézométrique calculée (bouton Calcul > Calculer), par tronçon">
              <input type="checkbox" checked={showPiezo} onChange={(e) => setShowPiezo(e.target.checked)} />
              <span className="curve-color-swatch" style={{ background: CURVE_COLORS.piezo }} />
              <span>Ligne piézométrique</span>
            </label>
            <label className="metric" title="Altitude du terrain + PMS (pression maximale de service) de la conduite en place — tracée en pointillés">
              <input type="checkbox" checked={showPms} onChange={(e) => setShowPms(e.target.checked)} />
              <span className="curve-color-swatch curve-color-swatch--dashed" style={{ borderColor: CURVE_COLORS.pms }} />
              <span>Enveloppe PMS</span>
            </label>
            <label className="metric" title="Niveau (constant) du plan d'eau amont max des tronçons gravitaires">
              <input type="checkbox" checked={showHydrostaticMax} onChange={(e) => setShowHydrostaticMax(e.target.checked)} />
              <span className="curve-color-swatch" style={{ background: CURVE_COLORS.hydrostaticMax }} />
              <span>Ligne hydrostatique Max</span>
            </label>
            <label className="metric" title="Niveau (constant) du plan d'eau amont min des tronçons gravitaires">
              <input type="checkbox" checked={showHydrostaticMin} onChange={(e) => setShowHydrostaticMin(e.target.checked)} />
              <span className="curve-color-swatch" style={{ background: CURVE_COLORS.hydrostaticMin }} />
              <span>Ligne hydrostatique Min</span>
            </label>
          </>
        )}
        {trace?.crossings != null && (
          <label className="metric" title="Traversées détectées (routes, voies ferrées, cours d'eau, bâtiments) — base OpenStreetMap, indicative">
            <input type="checkbox" checked={showCrossings} onChange={(e) => setShowCrossings(e.target.checked)} />
            <span className="curve-color-swatch" style={{ background: CURVE_COLORS.crossing }} />
            <span>Traversées ({trace.crossings.length})</span>
          </label>
        )}
      </div>
      {pendingAdd != null && trace && (
        <NodeDialog
          mode="create"
          pk={pendingAdd.pk}
          existingNodes={nodes}
          project={project}
          excludeNodeId={pendingAdd.placeholderNodeId}
          precedingOuvrage={findPrecedingOuvrage(nodes, trace.id, pendingAdd.pk)}
          onClose={() => setPendingAdd(null)}
          onSubmit={handleSubmitPendingAdd}
        />
      )}
      {editingNode && (
        <NodeDialog
          mode="edit"
          pk={editingNode.pk}
          existingNodes={nodes}
          project={project}
          initialType={editingNode.type as CreatableNodeType}
          initialName={editingNode.name}
          initialData={editingNode.data}
          initialInjectedFlow={editingNode.injected_flow}
          initialWithdrawnFlow={editingNode.withdrawn_flow}
          initialExisting={editingNode.existing}
          initialPhaseId={editingNode.phase_id}
          excludeNodeId={editingNode.id}
          onClose={() => setEditingNode(null)}
          onSubmit={handlePatchNode}
        />
      )}
      {calcConfirmDialog}
    </>
  )
}
