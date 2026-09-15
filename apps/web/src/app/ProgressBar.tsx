// Barre de progression — INDETERMINEE par defaut (une simple animation continue, pas de
// pourcentage : la detection de traversees Overpass, `MapView.tsx`, reste un seul appel reseau non
// subdivisable). Mode DETERMINE si `percent` est fourni (consigne utilisateur : barre a
// pourcentage reel pour le calcul hydraulique, desormais un job asynchrone — cf.
// shared/pollCalcJob.ts) — reutilise le meme jeu de classes `.job-progress*` que l'import de trace
// (ProjectTree.tsx), un seul bloc CSS determine partage entre les deux.

export function ProgressBar({ label, percent }: { label?: string; percent?: number }) {
  const determinate = typeof percent === 'number'
  if (determinate) {
    return (
      <div className="job-progress">
        <div className="job-progress-track" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
          <div className="job-progress-track-fill" style={{ width: `${percent}%` }} />
        </div>
        {label && <span className="job-progress-label">{`${label} (${percent}%)`}</span>}
      </div>
    )
  }
  return (
    <div className="progress-bar-wrap" role="progressbar" aria-label={label ?? 'En cours'}>
      <div className="progress-bar-track">
        <div className="progress-bar-fill" />
      </div>
      {label && <span className="progress-bar-label">{label}</span>}
    </div>
  )
}
