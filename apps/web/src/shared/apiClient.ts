// Client API minimal (Lot 1) — cf. docs/architecture/05-api.md.
// Un vrai client genere depuis l'OpenAPI de FastAPI remplacera ce fichier ecrit a la main des que
// l'API se stabilise (docs/architecture/02-arborescence-repository.md : packages/shared-types).

import type {
  CalcRunResult,
  CalculationPreferences,
  CatalogDiameter,
  CatalogMaterial,
  CreatableNodeType,
  ImportJobStarted,
  ImportJobStatus,
  NetworkViolation,
  Node,
  PipeCatalogRow,
  ProjectStateResponse,
  Segment,
  TraceGeometry,
  TronconGroup,
  Variant,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000/api/v1'

async function handleJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error((body as { detail?: string }).detail ?? `Erreur API ${response.status}`)
  }
  return (await response.json()) as T
}

// Formulaire complet "Parametres du projet" (creation ET edition, meme forme — cf.
// hydrops_api.schemas.ProjectFormFields). annual_volume_points, s'il est fourni, est deja resolu
// cote client (sans trous — voir interpolateAnnualVolumePoints) : une valeur par annee a partir de
// commissioning_year, sur amortization_years annees.
export interface ProjectFormPayload {
  name: string
  client?: string
  currency?: string
  default_water_type?: string
  study_horizon_years?: number
  project_lifetime_years?: number
  first_investment_year?: number
  commissioning_year?: number
  amortization_years?: number
  discount_rate?: number
  energy_price?: number
  annual_volume_value?: number
  annual_volume_points?: { year: number; value: number }[]
  lifetimes_pipes?: number
  lifetimes_civil_works?: number
  lifetimes_electromechanical?: number
  lifetimes_instrumentation_control?: number
  lifetimes_other?: number
}

export const api = {
  async createSession(): Promise<{ session_id: string; expires_at: number }> {
    const response = await fetch(`${API_BASE}/sessions`, { method: 'POST' })
    return handleJson(response)
  },

  async heartbeat(sessionId: string): Promise<void> {
    await fetch(`${API_BASE}/sessions/${sessionId}/heartbeat`, { method: 'POST' })
  },

  async newProject(sessionId: string, payload: ProjectFormPayload): Promise<ProjectStateResponse> {
    const response = await fetch(`${API_BASE}/projects/new?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return handleJson(response)
  },

  async patchProject(sessionId: string, payload: ProjectFormPayload): Promise<ProjectStateResponse> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return handleJson(response)
  },

  async getProject(sessionId: string): Promise<ProjectStateResponse> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}`)
    return handleJson(response)
  },

  async exportProject(sessionId: string): Promise<Blob> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/export`)
    if (!response.ok) {
      throw new Error(`Export impossible (${response.status})`)
    }
    return response.blob()
  },

  async importProject(sessionId: string, file: File): Promise<ProjectStateResponse> {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch(`${API_BASE}/projects/import?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'POST',
      body: form,
    })
    return handleJson(response)
  },

  async startTraceImport(sessionId: string, file: File): Promise<ImportJobStarted> {
    const form = new FormData()
    form.append('file', file)
    const response = await fetch(`${API_BASE}/projects/${sessionId}/traces/import`, { method: 'POST', body: form })
    return handleJson(response)
  },

  async listTraces(sessionId: string): Promise<TraceGeometry[]> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/traces`)
    return handleJson(response)
  },

  async getImportJobStatus(sessionId: string, jobId: string): Promise<ImportJobStatus> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/traces/import-jobs/${jobId}`)
    return handleJson(response)
  },

  async newVariant(sessionId: string, payload: { name: string; description?: string }): Promise<Variant> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return handleJson(response)
  },

  async patchVariant(
    sessionId: string,
    variantId: string,
    payload: { name?: string; description?: string },
  ): Promise<Variant> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return handleJson(response)
  },

  async duplicateVariant(sessionId: string, variantId: string): Promise<Variant> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/duplicate`, {
      method: 'POST',
    })
    return handleJson(response)
  },

  async deleteVariant(sessionId: string, variantId: string): Promise<void> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}`, {
      method: 'DELETE',
    })
    if (!response.ok && response.status !== 204) {
      const body = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error((body as { detail?: string }).detail ?? `Erreur API ${response.status}`)
    }
  },

  async patchTrace(
    sessionId: string,
    traceId: string,
    payload: { hydraulic_direction?: 'as_drawn' | 'reversed' },
  ): Promise<TraceGeometry> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/traces/${traceId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return handleJson(response)
  },

  async listNodes(sessionId: string, variantId: string): Promise<Node[]> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/nodes`)
    return handleJson(response)
  },

  async listSegments(sessionId: string, variantId: string): Promise<Segment[]> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/segments`)
    return handleJson(response)
  },

  async getNetworkViolations(sessionId: string, variantId: string): Promise<NetworkViolation[]> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/network/violations`)
    return handleJson(response)
  },

  async addNode(
    sessionId: string,
    variantId: string,
    traceId: string,
    pk: number,
    payload: {
      type: CreatableNodeType
      name?: string
      data?: Record<string, unknown>
      injected_flow?: number
      withdrawn_flow?: number
    },
  ): Promise<Node> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/nodes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trace_id: traceId, pk, ...payload, name: payload.name || undefined }),
    })
    return handleJson(response)
  },

  async patchNode(
    sessionId: string,
    variantId: string,
    nodeId: string,
    payload: {
      type?: CreatableNodeType
      name?: string
      data?: Record<string, unknown>
      injected_flow?: number
      withdrawn_flow?: number
    },
  ): Promise<Node> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/nodes/${nodeId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return handleJson(response)
  },

  async patchNodePosition(
    sessionId: string,
    variantId: string,
    nodeId: string,
    pk: number,
  ): Promise<{ node: Node; needs_level_confirmation: boolean }> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/nodes/${nodeId}/position`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pk }),
    })
    return handleJson(response)
  },

  async listTroncons(sessionId: string, variantId: string): Promise<TronconGroup[]> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/network/troncons`)
    return handleJson(response)
  },

  async deleteNode(sessionId: string, variantId: string, nodeId: string): Promise<void> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/nodes/${nodeId}`, {
      method: 'DELETE',
    })
    if (!response.ok && response.status !== 204) {
      const body = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error((body as { detail?: string }).detail ?? `Erreur API ${response.status}`)
    }
  },

  async patchSegment(
    sessionId: string,
    variantId: string,
    segmentId: string,
    payload: {
      material?: string
      dn?: number
      pressure_class?: string
      head_flow?: number
      upstream_water_level_max?: number
      upstream_water_level_min?: number
      upstream_water_level_max_offset?: number
      upstream_water_level_min_offset?: number
      min_pressure?: number
      downstream_residual_pressure?: number
      max_velocity?: number
      min_velocity?: number
      forced_material?: string
      forced_dn?: number
    },
  ): Promise<Segment> {
    const response = await fetch(
      `${API_BASE}/projects/${sessionId}/variants/${variantId}/segments/${segmentId}`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    )
    return handleJson(response)
  },

  async resetSegment(sessionId: string, variantId: string, segmentId: string): Promise<Segment> {
    const response = await fetch(
      `${API_BASE}/projects/${sessionId}/variants/${variantId}/segments/${segmentId}/reset`,
      { method: 'POST' },
    )
    return handleJson(response)
  },

  async listCatalogMaterials(): Promise<CatalogMaterial[]> {
    const response = await fetch(`${API_BASE}/catalog/materials`)
    return handleJson(response)
  },

  async listCatalogDiameters(material: string, pressureClass: string): Promise<CatalogDiameter[]> {
    const response = await fetch(
      `${API_BASE}/catalog/diameters?material=${encodeURIComponent(material)}&pressure_class=${encodeURIComponent(pressureClass)}`,
    )
    return handleJson(response)
  },

  async listConduites(): Promise<PipeCatalogRow[]> {
    const response = await fetch(`${API_BASE}/catalog/conduites`)
    return handleJson(response)
  },

  async patchConduite(rowId: number, active: boolean): Promise<PipeCatalogRow> {
    const response = await fetch(`${API_BASE}/catalog/conduites/${rowId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active }),
    })
    return handleJson(response)
  },

  async getPreferences(sessionId: string): Promise<CalculationPreferences> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/preferences`)
    return handleJson(response)
  },

  async putPreferences(sessionId: string, payload: CalculationPreferences): Promise<CalculationPreferences> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/preferences`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return handleJson(response)
  },

  async runCalculation(sessionId: string, variantId: string): Promise<CalcRunResult> {
    const response = await fetch(`${API_BASE}/projects/${sessionId}/variants/${variantId}/calcul`, { method: 'POST' })
    return handleJson(response)
  },
}
