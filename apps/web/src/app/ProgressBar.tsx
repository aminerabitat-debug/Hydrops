// Barre de progression INDETERMINEE (consigne utilisateur : calcul hydraulique, 1ere detection de
// traversees) — une simple animation continue, pas un pourcentage : ni /calcul (synchrone, un seul
// aller-retour HTTP) ni la detection Overpass (un seul appel reseau non subdivisable) ne peuvent
// remonter une vraie progression sans reecrire ces endpoints en jobs asynchrones (hors de portee
// de cette demande — juste "montrer que ça travaille", pas un vrai % d'avancement).

export function ProgressBar({ label }: { label?: string }) {
  return (
    <div className="progress-bar-wrap" role="progressbar" aria-label={label ?? 'En cours'}>
      <div className="progress-bar-track">
        <div className="progress-bar-fill" />
      </div>
      {label && <span className="progress-bar-label">{label}</span>}
    </div>
  )
}
