// Regime hydraulique visuel des troncons (demande utilisateur) : fleche inclinee montante
// (refoulement) ou descendante (gravitaire), trait horizontal tant que le noeud DE DEPART du
// troncon n'est pas encore un ouvrage "defini" (cf. isNodeDefined) — la direction n'aurait alors
// aucun sens a afficher. Le regime ne se base PAS sur la topographie (denivele) — consigne
// utilisateur : un troncon est en refoulement s'il demarre juste apres une station de pompage ou
// une station de traitement (qui integre elle-meme un pompage), gravitaire pour tout autre ouvrage
// de depart defini (reservoir, brise charge, piquage...). Seul le noeud de depart compte : celui
// d'arrivee peut rester une simple jonction sans que ca invalide le regime. Sert aussi
// d'indicateur "donnees renseignees ou pas" (dernier point de la demande) via tronconIsForced
// (DN/materiau explicitement choisis, cf. Segment.forced).

import { isNodeDefined } from './types'
import type { Node, NodeType, Segment, TronconGroup } from './types'

export type TronconRegime = 'gravitaire' | 'refoulement' | 'indetermine'

// Types d'ouvrage qui mettent le troncon aval en charge (refoulement) — une jonction simple
// (simple changement de DN/materiau) n'y figure jamais : ce n'est pas un ouvrage.
const PUMPING_TRIGGER_TYPES: NodeType[] = ['pumping_station', 'treatment_plant']

export const TRONCON_REGIME_GLYPH: Record<TronconRegime, string> = {
  gravitaire: '↘',
  refoulement: '↗',
  indetermine: '→',
}

export const TRONCON_REGIME_COLOR: Record<TronconRegime, string> = {
  gravitaire: '#3ea6ff',
  refoulement: '#ff9f43',
  indetermine: '#7d8cad',
}

export function tronconEndpointsDefined(
  troncon: TronconGroup,
  nodesById: Map<string, Node>,
): { start: Node | undefined; end: Node | undefined; defined: boolean } {
  const start = nodesById.get(troncon.start_node_id)
  const end = nodesById.get(troncon.end_node_id)
  const defined = Boolean(start && end && isNodeDefined(start) && isNodeDefined(end))
  return { start, end, defined }
}

export function tronconRegime(troncon: TronconGroup, nodesById: Map<string, Node>): TronconRegime {
  const start = nodesById.get(troncon.start_node_id)
  if (!start || !isNodeDefined(start)) return 'indetermine'
  return PUMPING_TRIGGER_TYPES.includes(start.type) ? 'refoulement' : 'gravitaire'
}

// "Donnees renseignees" pour un troncon = DN/materiau explicitement choisis sur TOUS ses segments
// (pas juste la valeur par defaut posee a l'import) — reflete Segment.forced.
export function tronconIsForced(troncon: TronconGroup, segmentsById: Map<string, Segment>): boolean {
  return troncon.segment_ids.length > 0 && troncon.segment_ids.every((id) => segmentsById.get(id)?.forced === true)
}
