// Palette et libelles des traversees (consigne utilisateur : "couleurs differentes... mais avec
// une palette adaptee, par ex des nuances de gris pour les routes de differentes classes et des
// nuances de bleu pour les cours d'eau"). Source de verite UNIQUE, importee par MapView.tsx,
// ProfileChart.tsx et DataTable.tsx — jamais dupliquee (contrairement a l'ancien CROSSING_LABELS/
// CROSSING_KIND_LABELS, cf. historique).

import type { Crossing, CrossingKind } from './types'

// Gris par classe de route (`highway=*` OSM) — la plus circulee (motorway/trunk) la plus foncee,
// jusqu'a la plus modeste (piste/sentier) la plus claire. Defaut = gris moyen pour une classe non
// listee ici (le catalogue OSM en compte des dizaines de rares).
const HIGHWAY_RAMP: Record<string, string> = {
  motorway: '#1f2530', motorway_link: '#1f2530',
  trunk: '#2a3140', trunk_link: '#2a3140',
  primary: '#3c4457', primary_link: '#3c4457',
  secondary: '#525c72', secondary_link: '#525c72',
  tertiary: '#6b7488', tertiary_link: '#6b7488',
  residential: '#848da0', unclassified: '#848da0', living_street: '#848da0', service: '#848da0',
  track: '#a4acb9', path: '#a4acb9', footway: '#a4acb9', cycleway: '#a4acb9', bridleway: '#a4acb9', steps: '#a4acb9',
}
const HIGHWAY_DEFAULT = '#6b7488'

// Bleu par classe de cours d'eau (`waterway=*` OSM) — le plus important (riviere) le plus soutenu,
// jusqu'au plus modeste (fosse/drain) le plus clair.
const WATERWAY_RAMP: Record<string, string> = {
  river: '#155e8f', canal: '#1f77a8',
  stream: '#3f97c9', tidal_channel: '#3f97c9',
  drain: '#7cc0e0', ditch: '#7cc0e0',
}
const WATERWAY_DEFAULT = '#2f87b8'

const RAILWAY_COLOR = '#b3541e'
const BUILDING_COLOR = '#8b8577'

// Couleurs de zone (urbain/forestier) — reutilisees telles quelles pour les reperes ET pour le
// halo le long de la trace (cf. crossingZoneFillColor), consigne utilisateur : meme palette pour
// les deux, sur la carte ET le profil graphique.
const ZONE_COLORS: Record<'urban' | 'forest', string> = { urban: '#e0863f', forest: '#3fa34d' }

export function crossingColor(kind: CrossingKind, subtype?: string | null): string {
  switch (kind) {
    case 'highway':
      return (subtype && HIGHWAY_RAMP[subtype]) ?? HIGHWAY_DEFAULT
    case 'waterway':
      return (subtype && WATERWAY_RAMP[subtype]) ?? WATERWAY_DEFAULT
    case 'railway':
      return RAILWAY_COLOR
    case 'building':
      return BUILDING_COLOR
    case 'urban':
    case 'forest':
      return ZONE_COLORS[kind]
  }
}

export function isZoneKind(kind: CrossingKind): kind is 'urban' | 'forest' {
  return kind === 'urban' || kind === 'forest'
}

function hexToRgb(hex: string): [number, number, number] {
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)]
}

// Couleur de REMPLISSAGE du halo de zone (consigne utilisateur : "une sorte de shadow autour du
// tracé dans cette zone") — translucide, pour rester lisible sous la trace/le terrain.
export function crossingZoneFillColor(kind: 'urban' | 'forest', alpha = 0.22): string {
  const [r, g, b] = hexToRgb(ZONE_COLORS[kind])
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// Lettre compacte affichee sur le profil graphique (espace tres contraint, cf. ProfileChart.tsx) —
// seule la couleur y change desormais (palette ci-dessus), la lettre reste pour la compacite.
export function crossingKindGlyph(kind: CrossingKind): string {
  return { highway: 'R', railway: 'F', waterway: 'E', building: 'B', urban: 'U', forest: 'V' }[kind]
}

// Terme lisible (consigne utilisateur : "des termes plus compréhensibles comme ceux que je t'avais
// donné initialement") — profil Data et info-bulles carte, PAS le profil graphique (glyphe ci-dessus).
export function crossingKindLabel(kind: CrossingKind): string {
  return {
    highway: 'Route/piste',
    railway: 'Voie ferrée',
    waterway: "Cours d'eau",
    building: 'Bâtiment',
    urban: 'Zone urbaine',
    forest: 'Zone forestière',
  }[kind]
}

// Longueur d'une traversee de ZONE (urbain/forestier, consigne utilisateur : "colonne Longueur de
// la traversée") — n'a de sens QUE pour une entree de zone : le backend modelise une traversee de
// zone comme deux Crossing distincts de meme `kind`, "Entrée zone ..."/"Sortie zone ..." (jamais
// une paire dediee, cf. hydrops_api.services.crossings:_compute_zone_crossings), donc calculee ici
// a l'affichage plutot que stockee. `null` pour une traversee ponctuelle (route/voie ferree/cours
// d'eau/bâtiment — un point n'a pas de "longueur") et pour une ligne "Sortie" elle-meme (affichee
// une seule fois, sur son "Entrée" correspondante, pour eviter la redondance).
export function crossingLength(crossing: Pick<Crossing, 'kind' | 'label' | 'pk'>, all: Crossing[]): number | null {
  if (!isZoneKind(crossing.kind) || !crossing.label?.startsWith('Entrée')) return null
  const exit = all
    .filter((c) => c.kind === crossing.kind && c.label?.startsWith('Sortie') && c.pk > crossing.pk)
    .sort((a, b) => a.pk - b.pk)[0]
  return exit ? exit.pk - crossing.pk : null
}

// Texte complet pour une traversee donnee — utilise le libelle deja lisible du backend pour une
// entree/sortie de zone (ex. "Entrée zone urbaine", cf. crossings.py:_zone_crossing) tel quel, et
// combine terme + nom/sous-categorie pour une traversee ponctuelle.
export function crossingDisplayText(c: Pick<Crossing, 'kind' | 'label' | 'subtype'>): string {
  if (isZoneKind(c.kind)) return c.label ?? crossingKindLabel(c.kind)
  const base = crossingKindLabel(c.kind)
  if (c.label) return `${base} — ${c.label}`
  if (c.subtype) return `${base} (${c.subtype})`
  return base
}
