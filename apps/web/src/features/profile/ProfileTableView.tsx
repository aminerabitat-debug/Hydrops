// "Profil et table de donnees occupent le meme panneau et sont alternes par onglet/bouton
// integre" (cdc §4) — bouton bascule Graphique/Data + cases a cocher des courbes, inspires de
// la page de reference fournie par l'utilisateur.

import { useMemo, useState } from 'react'

import { api } from '../../shared/apiClient'
import { useAppStore } from '../../state/store'
import { isStructuralEndpoint as isStructuralEndpointOf } from '../../shared/types'
import type { CreatableNodeType, Node } from '../../shared/types'
import { DataTable } from '../table/DataTable'
import { NodeDialog, type NodeSubmitPayload } from './NodeDialog'
import { ProfileChart } from './ProfileChart'

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
  const [addNodeMode, setAddNodeMode] = useState(false)

  const [pendingAdd, setPendingAdd] = useState<PendingAdd | null>(null)
  const [editingNode, setEditingNode] = useState<Node | null>(null)

  const sessionId = useAppStore((s) => s.sessionId)
  const selectedVariantId = useAppStore((s) => s.selection.selectedVariantId)
  const nodes = useAppStore((s) => s.nodes)
  const refreshNetwork = useAppStore((s) => s.refreshNetwork)
  const setStatusMessage = useAppStore((s) => s.setStatusMessage)
  const traces = useAppStore((s) => s.traces)
  const selectedTraceId = useAppStore((s) => s.selection.selectedTraceId)
  const trace = traces.find((t) => t.id === selectedTraceId) ?? traces[0]
  const profile = trace?.elevation_profile

  const handleSubmitPendingAdd = async (payload: NodeSubmitPayload) => {
    if (!sessionId || !selectedVariantId || !trace || pendingAdd == null) return
    const { type, name, data, injectedFlow, withdrawnFlow } = payload
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
      })
    } else {
      await api.addNode(sessionId, selectedVariantId, trace.id, pendingAdd.pk, {
        type,
        name,
        data,
        injected_flow: injectedFlow,
        withdrawn_flow: withdrawnFlow,
      })
    }
    await refreshNetwork()
    setStatusMessage(`Nœud ajouté au PK ${Math.round(pendingAdd.pk)} m`)
  }

  const handlePatchNode = async (payload: NodeSubmitPayload) => {
    if (!sessionId || !selectedVariantId || !editingNode) return
    await api.patchNode(sessionId, selectedVariantId, editingNode.id, {
      type: payload.type,
      name: payload.name,
      data: payload.data,
      injected_flow: payload.injectedFlow,
      withdrawn_flow: payload.withdrawnFlow,
    })
    await refreshNetwork()
    setStatusMessage('Nœud mis à jour')
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
      setStatusMessage('Ouvrage retiré (extrémité redevenue non affectée)')
    } else {
      await api.deleteNode(sessionId, selectedVariantId, node.id)
      setStatusMessage('Nœud supprimé')
    }
    await refreshNetwork()
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
        <h2>Profil en long</h2>
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
          <button type="button" className="btn-toggle" onClick={() => setMode((m) => (m === 'graph' ? 'data' : 'graph'))}>
            {mode === 'graph' ? 'Mode Data' : 'Mode Graphique'}
          </button>
          <label className="metric">
            <input type="checkbox" checked={showTerrain} onChange={(e) => setShowTerrain(e.target.checked)} />
            <span>Terrain</span>
          </label>
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
        </div>
      </div>
      <div className="profile-content">
        {mode === 'graph' ? (
          <ProfileChart
            showTerrain={showTerrain}
            addNodeMode={addNodeMode}
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
      {pendingAdd != null && (
        <NodeDialog
          mode="create"
          pk={pendingAdd.pk}
          existingNodes={nodes}
          excludeNodeId={pendingAdd.placeholderNodeId}
          onClose={() => setPendingAdd(null)}
          onSubmit={handleSubmitPendingAdd}
        />
      )}
      {editingNode && (
        <NodeDialog
          mode="edit"
          pk={editingNode.pk}
          existingNodes={nodes}
          initialType={editingNode.type as CreatableNodeType}
          initialName={editingNode.name}
          initialData={editingNode.data}
          initialInjectedFlow={editingNode.injected_flow}
          initialWithdrawnFlow={editingNode.withdrawn_flow}
          excludeNodeId={editingNode.id}
          onClose={() => setEditingNode(null)}
          onSubmit={handlePatchNode}
        />
      )}
    </>
  )
}
