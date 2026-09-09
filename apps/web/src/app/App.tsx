// Coquille applicative (cdc §4) : barre de menus + barre d'acces rapide, arborescence a gauche,
// espace central adaptable (Carte / Profil-Table / vue combinee avec separateur reglable),
// barre d'etat. Interface redessinee sur le modele de la page de reference fournie par
// l'utilisateur (theme sombre, panneaux arrondis, glissiere verticale).

import { useCallback, useEffect, useRef, useState } from 'react'

import { ConfirmDialog } from './ConfirmDialog'
import { MenuBar } from './MenuBar'
import { NewVariantDialog } from './NewVariantDialog'
import { ProjectDialog } from './ProjectDialog'
import { QuickBar } from './QuickBar'
import { Workspace, type LayoutMode } from './Workspace'
import { ProjectTree } from '../features/project-tree/ProjectTree'
import { api, type ProjectFormPayload } from '../shared/apiClient'
import { useAppStore } from '../state/store'
import './App.css'

const HEARTBEAT_INTERVAL_MS = 60_000

type DialogState = 'none' | 'newProject' | 'editProject' | 'newVariant' | 'confirmDeleteVariant'

export function App() {
  const sessionId = useAppStore((s) => s.sessionId)
  const setSessionId = useAppStore((s) => s.setSessionId)
  const project = useAppStore((s) => s.project)
  const variants = useAppStore((s) => s.variants)
  const selectedVariantId = useAppStore((s) => s.selection.selectedVariantId)
  const setProjectState = useAppStore((s) => s.setProjectState)
  const setSelectedVariant = useAppStore((s) => s.setSelectedVariant)
  const refreshNetwork = useAppStore((s) => s.refreshNetwork)
  const statusMessage = useAppStore((s) => s.statusMessage)
  const setStatusMessage = useAppStore((s) => s.setStatusMessage)

  const [layoutMode, setLayoutMode] = useState<LayoutMode>('both')
  const [dialog, setDialog] = useState<DialogState>('none')
  const [backendUnreachable, setBackendUnreachable] = useState(false)
  const [pendingDeleteVariantId, setPendingDeleteVariantId] = useState<string | null>(null)
  const openInputRef = useRef<HTMLInputElement>(null)

  // Cree une session a la demande si aucune n'existe encore (mount initial rate, ou serveur
  // relance apres coup) — sans ca, une session ratee au demarrage laissait sessionId a null pour
  // toujours et chaque action ultra-silencieusement un no-op (`if (!sessionId) return`),
  // ce qui se manifestait comme "je clique sur Nouveau et rien ne se passe".
  const ensureSession = useCallback(async (): Promise<string> => {
    const current = useAppStore.getState().sessionId
    if (current) return current
    try {
      const res = await api.createSession()
      setSessionId(res.session_id)
      setBackendUnreachable(false)
      return res.session_id
    } catch (error) {
      setBackendUnreachable(true)
      throw new Error(
        `Serveur inaccessible (${(error as Error).message}). Vérifiez que l'API tourne sur ${
          (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000/api/v1'
        }, puis réessayez.`,
      )
    }
  }, [setSessionId])

  useEffect(() => {
    ensureSession().catch(() => {
      // L'erreur est deja tracee via backendUnreachable ; ensureSession sera retentee au
      // prochain clic utilisateur (Nouveau, Ouvrir...), pas besoin de boucle de retry ici.
    })
  }, [ensureSession])

  useEffect(() => {
    refreshNetwork().catch((error) => setStatusMessage(`Erreur de chargement du réseau : ${(error as Error).message}`))
  }, [sessionId, selectedVariantId, refreshNetwork, setStatusMessage])

  useEffect(() => {
    if (!sessionId) return
    const interval = setInterval(() => {
      api.heartbeat(sessionId).catch(() => {
        // Le prochain appel utilisateur echouera avec un 404 explicite si la session a expire.
      })
    }, HEARTBEAT_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [sessionId])

  const handleCreateProject = async (payload: ProjectFormPayload) => {
    const sid = await ensureSession()
    const state = await api.newProject(sid, payload)
    setProjectState(state)
    await refreshNetwork()
    setStatusMessage(`Projet "${state.project.name}" créé`)
  }

  const handleEditProject = async (payload: ProjectFormPayload) => {
    const sid = await ensureSession()
    const state = await api.patchProject(sid, payload)
    setProjectState(state)
    setStatusMessage(`Paramètres du projet "${state.project.name}" mis à jour`)
  }

  const handleOpenFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      const sid = await ensureSession()
      const state = await api.importProject(sid, file)
      setProjectState(state)
      // setProjectState peut conserver le meme selectedVariantId qu'avant l'ouverture (memes ids
      // dans le fichier reouvert) — l'effet [sessionId, selectedVariantId] ne se redeclenche alors
      // pas tout seul, d'ou ce rechargement explicite des noeuds/segments du fichier reouvert.
      await refreshNetwork()
      setStatusMessage(`Projet "${state.project.name}" ouvert depuis ${file.name}`)
    } catch (error) {
      setStatusMessage(`Erreur d'ouverture : ${(error as Error).message}`)
    }
  }

  const handleSaveProject = async () => {
    try {
      const sid = await ensureSession()
      const blob = await api.exportProject(sid)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = 'projet.hydrops'
      link.click()
      URL.revokeObjectURL(url)
      setStatusMessage('Projet enregistré (.hydrops téléchargé)')
    } catch (error) {
      setStatusMessage(`Erreur d'enregistrement : ${(error as Error).message}`)
    }
  }

  const handleCreateVariant = async (name: string, description: string) => {
    const sid = await ensureSession()
    const variant = await api.newVariant(sid, { name, description: description || undefined })
    const state = await api.getProject(sid)
    setProjectState(state)
    setSelectedVariant(variant.id)
    setStatusMessage(`Variante créée : ${variant.name}`)
  }

  const handleDuplicateVariant = async (variantId: string | null) => {
    if (!variantId) return
    try {
      const sid = await ensureSession()
      const copy = await api.duplicateVariant(sid, variantId)
      const state = await api.getProject(sid)
      setProjectState(state)
      setSelectedVariant(copy.id)
      await refreshNetwork()
      setStatusMessage(`Variante dupliquée : ${copy.name}`)
    } catch (error) {
      setStatusMessage(`Erreur de duplication : ${(error as Error).message}`)
    }
  }

  const handleRequestDeleteVariant = (variantId: string | null) => {
    if (!variantId) return
    setPendingDeleteVariantId(variantId)
    setDialog('confirmDeleteVariant')
  }

  const handleDeleteVariant = async () => {
    if (!pendingDeleteVariantId) return
    const sid = await ensureSession()
    await api.deleteVariant(sid, pendingDeleteVariantId)
    const state = await api.getProject(sid)
    setProjectState(state)
    await refreshNetwork()
    setStatusMessage('Variante supprimée')
    setPendingDeleteVariantId(null)
  }

  const pendingDeleteVariantName = variants.find((v) => v.id === pendingDeleteVariantId)?.name

  return (
    <div className="app-shell">
      <MenuBar
        projectOpen={Boolean(project)}
        variantSelected={Boolean(selectedVariantId)}
        onNewProject={() => setDialog('newProject')}
        onOpenProject={() => openInputRef.current?.click()}
        onSaveProject={handleSaveProject}
        onNewVariant={() => setDialog('newVariant')}
        onDuplicateVariant={() => handleDuplicateVariant(selectedVariantId)}
        onDeleteVariant={() => handleRequestDeleteVariant(selectedVariantId)}
        layoutMode={layoutMode}
        onLayoutModeChange={setLayoutMode}
        onAbout={() => setStatusMessage('HydroPS v0.1.0 — Lot 1 (socle, SIG/DEM, carte/profil/table)')}
      />

      <QuickBar
        projectOpen={Boolean(project)}
        onNewProject={() => setDialog('newProject')}
        onOpenProject={() => openInputRef.current?.click()}
        onSaveProject={handleSaveProject}
      />
      <input ref={openInputRef} type="file" accept=".hydrops" hidden onChange={handleOpenFile} />

      <div className="workspace-shell">
        <aside className="tree-panel">
          <div className="tree-header">Arborescence du projet</div>
          <ProjectTree
            onOpenProjectSettings={() => setDialog('editProject')}
            onNewVariant={() => setDialog('newVariant')}
            onDuplicateVariant={handleDuplicateVariant}
            onRequestDeleteVariant={handleRequestDeleteVariant}
          />
        </aside>
        <Workspace layoutMode={layoutMode} />
      </div>

      <footer className="status-bar">
        {backendUnreachable && (
          <span className="status-bar-text warn">
            ⚠ Serveur API inaccessible — vérifiez qu'il tourne, puis réessayez l'action.
          </span>
        )}
        <span className="status-bar-text">{statusMessage}</span>
      </footer>

      {dialog === 'newProject' && (
        <ProjectDialog mode="create" onClose={() => setDialog('none')} onSubmit={handleCreateProject} />
      )}
      {dialog === 'editProject' && project && (
        <ProjectDialog mode="edit" initialProject={project} onClose={() => setDialog('none')} onSubmit={handleEditProject} />
      )}
      {dialog === 'newVariant' && <NewVariantDialog onClose={() => setDialog('none')} onCreate={handleCreateVariant} />}
      {dialog === 'confirmDeleteVariant' && (
        <ConfirmDialog
          title="Supprimer la variante"
          message={`Supprimer définitivement la variante "${pendingDeleteVariantName ?? ''}" et son réseau (nœuds/segments) ? Les tracés du projet resteront disponibles pour les autres variantes.`}
          confirmLabel="Supprimer"
          onClose={() => setDialog('none')}
          onConfirm={handleDeleteVariant}
        />
      )}
    </div>
  )
}
