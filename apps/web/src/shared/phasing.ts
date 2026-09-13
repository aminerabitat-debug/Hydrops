// Aide partagee pour les listes deroulantes de phase (NodeDialog, StationPhasingTable,
// TronconDialog) — la Phase 1 est implicite cote backend (project.first_investment_year/
// commissioning_year, jamais un ProjectPhase a part entiere, cf. hydropack.models.Project), donc
// elle n'a pas d'id naturel : on lui attribue un id sentinelle stable, utilise partout ou l'UI a
// besoin de la referencer (Node.phase_id, Segment.phase_id, SegmentConstraint.phase_id).
import type { Project, ProjectPhase } from './types'

export const PHASE_1_ID = 'phase-1'

export interface PhaseOption {
  id: string
  index: number
}

// Phase 1 (implicite) + toutes les phases 2+ definies sur le projet, dans l'ordre — a utiliser pour
// peupler n'importe quelle liste deroulante "Phase de realisation".
export function listPhaseOptions(project: Project | null | undefined): PhaseOption[] {
  const rest: ProjectPhase[] = project?.phases ?? []
  return [{ id: PHASE_1_ID, index: 1 }, ...rest.slice().sort((a, b) => a.index - b.index)]
}
