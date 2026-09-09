// Volume annuel variable (cdc §5.1, demande utilisateur) : l'utilisateur colle une colonne de
// valeurs depuis Excel (une par annee, a partir de l'annee de mise en service, sur "duree
// d'amortissement" annees) ; les cases vides sont interpolees (entre deux valeurs connues) ou
// extrapolees (avant la 1ere / apres la derniere valeur connue, par la pente du couple le plus
// proche). Le tableau final (sans trous) est ce qui est envoye au backend (annual_volume_points).

export interface VolumeYear {
  year: number
  value: number
  wasPasted: boolean // false = valeur comblee par interpolation/extrapolation
}

/** Decoupe un texte colle en valeurs brutes — une ligne par annee (cas Excel standard, copier une
 * colonne), ou tabulation/virgule si tout tient sur une seule ligne. */
export function splitPastedValues(text: string): string[] {
  const normalized = text.replace(/\r/g, '')
  if (normalized.includes('\n')) return normalized.split('\n')
  if (normalized.includes('\t')) return normalized.split('\t')
  if (normalized.includes(',')) return normalized.split(',')
  return normalized.split('\n')
}

export function parsePastedValues(text: string): (number | null)[] {
  return splitPastedValues(text).map((raw) => {
    const trimmed = raw.trim().replace(',', '.') // tolere la virgule decimale (Excel FR)
    if (trimmed === '') return null
    const n = Number(trimmed)
    return Number.isFinite(n) ? n : null
  })
}

/** Comble les trous (null) d'une serie par interpolation lineaire entre valeurs connues, et
 * extrapolation lineaire (pente du couple connu le plus proche) avant la 1ere / apres la derniere
 * valeur connue. Toujours pleine longueur `length` (valeurs manquantes en fin de liste = 0 si
 * aucune valeur connue n'existe). Le resultat est ecrete a 0 (un volume ne peut pas etre negatif). */
export function fillVolumeGaps(values: (number | null)[], length: number): number[] {
  const padded = Array.from({ length }, (_, i) => values[i] ?? null)
  const knownIdx = padded.map((v, i) => (v != null ? i : -1)).filter((i) => i >= 0)

  if (knownIdx.length === 0) return padded.map(() => 0)
  if (knownIdx.length === 1) {
    const only = padded[knownIdx[0]] as number
    return padded.map(() => Math.max(0, only))
  }

  const filled: number[] = new Array(length)
  for (let k = 0; k < knownIdx.length - 1; k++) {
    const i0 = knownIdx[k]
    const i1 = knownIdx[k + 1]
    const v0 = padded[i0] as number
    const v1 = padded[i1] as number
    for (let i = i0; i <= i1; i++) {
      const t = i1 === i0 ? 0 : (i - i0) / (i1 - i0)
      filled[i] = v0 + t * (v1 - v0)
    }
  }

  const first = knownIdx[0]
  if (first > 0) {
    const i0 = knownIdx[0]
    const i1 = knownIdx[1]
    const v0 = padded[i0] as number
    const v1 = padded[i1] as number
    const slope = i1 === i0 ? 0 : (v1 - v0) / (i1 - i0)
    for (let i = 0; i < first; i++) filled[i] = v0 + slope * (i - i0)
  }

  const last = knownIdx[knownIdx.length - 1]
  if (last < length - 1) {
    const i1 = knownIdx[knownIdx.length - 1]
    const i0 = knownIdx[knownIdx.length - 2] ?? i1
    const v1 = padded[i1] as number
    const v0 = padded[i0] as number
    const slope = i1 === i0 ? 0 : (v1 - v0) / (i1 - i0)
    for (let i = last + 1; i < length; i++) filled[i] = v1 + slope * (i - i1)
  }

  return filled.map((v) => Math.max(0, v))
}

export function buildVolumeSeries(pastedText: string, commissioningYear: number, amortizationYears: number): VolumeYear[] {
  const parsed = parsePastedValues(pastedText)
  const filled = fillVolumeGaps(parsed, amortizationYears)
  return filled.map((value, i) => ({
    year: commissioningYear + i,
    value,
    wasPasted: parsed[i] != null,
  }))
}
