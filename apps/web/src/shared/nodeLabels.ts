// Libelles + identite visuelle (couleur/initiales) des types de noeud — partages entre
// l'arborescence (Ouvrages), le profil (marqueurs canvas) et la carte (symboles MapLibre), pour
// rester coherents (cdc §8, demande utilisateur : "icones differents... avec eventuellement des
// initiales").

import type { Node, NodeType } from './types'

export const NODE_TYPE_LABELS: Record<NodeType, string> = {
  terminal: 'Extrémité',
  // "junction" n'est plus jamais assignable depuis l'UI (Lot 3 etape 1d/1e) : il ne subsiste que
  // comme placeholder pose par le backend sur une extremite de trace pas encore affectee a un
  // ouvrage reel (consigne utilisateur : "ne pas mettre de jonction par defaut aux extremites").
  // Ce libelle n'apparait donc plus que dans de rares contextes de secours (cf. isPlaceholderNode
  // ci-dessous, utilise partout ailleurs pour masquer entierement ce noeud tant qu'il n'est pas
  // affecte).
  junction: 'Extrémité (à définir)',
  tie_in: 'Piquage',
  reservoir: 'Réservoir',
  pumping_station: 'Station de pompage',
  pressure_break: 'Brise charge',
  treatment_plant: 'Station de traitement',
  high_point: 'Point haut',
  low_point: 'Point bas',
  sectioning_valve: 'Vanne de sectionnement',
  control_valve: 'Vanne de régulation',
  intake: "Prise d'eau",
}

// Initiales courtes affichees dans le badge (arborescence/profil/carte).
export const NODE_TYPE_INITIALS: Record<NodeType, string> = {
  terminal: 'E',
  junction: 'J',
  tie_in: 'P',
  reservoir: 'R',
  pumping_station: 'SP',
  pressure_break: 'BC',
  treatment_plant: 'ST',
  high_point: 'PH',
  low_point: 'PB',
  sectioning_valve: 'VS',
  control_valve: 'VR',
  intake: 'PE',
}

// Une couleur distincte par type — reutilisee pour le badge d'arborescence, le marqueur canvas du
// profil et le cercle de symbole MapLibre.
export const NODE_TYPE_COLORS: Record<NodeType, string> = {
  terminal: '#7d8cad',
  junction: '#9fb0d1',
  tie_in: '#2dd4bf',
  reservoir: '#3ea6ff',
  pumping_station: '#ff9f43',
  pressure_break: '#c084fc',
  treatment_plant: '#4ade80',
  high_point: '#ff7a7a',
  low_point: '#7bd389',
  sectioning_valve: '#ffd166',
  control_valve: '#ffd166',
  intake: '#60a5fa',
}

// Un noeud "junction" est desormais TOUJOURS un placeholder d'extremite non affectee (plus jamais
// creable par l'utilisateur, cf. CreatableNodeType) — utilise pour le masquer partout ou un noeud
// "reel" est attendu (badge carte/profil, colonne Type de la table, icone crayon vs +), afin qu'une
// extremite non affectee se comporte exactement comme un piquet vide (consigne utilisateur).
export function isPlaceholderNode(node: Pick<Node, 'type'>): boolean {
  return node.type === 'junction'
}

export function nodeDisplayLabel(node: Pick<Node, 'type' | 'name'>): string {
  const typeLabel = NODE_TYPE_LABELS[node.type] ?? node.type
  return node.name ? `${typeLabel} ${node.name}` : typeLabel
}

export function nodeInitials(node: Pick<Node, 'type' | 'name'>): string {
  return NODE_TYPE_INITIALS[node.type] ?? '?'
}

export function nodeColor(node: Pick<Node, 'type'>): string {
  return NODE_TYPE_COLORS[node.type] ?? '#7d8cad'
}
