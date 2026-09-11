// Barre de menus (cdc §4) : Fichier, Variante, Calcul, Base de donnees, Affichage, Langue, Aide.
// Calcul (Calculer/Preferences) et Base de donnees (Conduites) sont actives depuis l'ajout du
// moteur de calcul hydraulique (consigne utilisateur) — Langue reste non fonctionnelle (Lot 7).

import { MenuDropdown } from './MenuDropdown'
import type { LayoutMode } from './Workspace'

interface MenuBarProps {
  projectOpen: boolean
  variantSelected: boolean
  onNewProject: () => void
  onOpenProject: () => void
  onSaveProject: () => void
  onNewVariant: () => void
  onDuplicateVariant: () => void
  onDeleteVariant: () => void
  layoutMode: LayoutMode
  onLayoutModeChange: (mode: LayoutMode) => void
  onAbout: () => void
  onRunCalcul: () => void
  onOpenPreferences: () => void
  onOpenConduites: () => void
}

export function MenuBar({
  projectOpen,
  variantSelected,
  onNewProject,
  onOpenProject,
  onSaveProject,
  onNewVariant,
  onDuplicateVariant,
  onDeleteVariant,
  layoutMode,
  onLayoutModeChange,
  onAbout,
  onRunCalcul,
  onOpenPreferences,
  onOpenConduites,
}: MenuBarProps) {
  return (
    <header className="menu-bar">
      <MenuDropdown
        label="Fichier"
        items={[
          { label: 'Nouveau', onClick: onNewProject },
          { label: 'Ouvrir .hydrops', onClick: onOpenProject },
          { label: 'Enregistrer', onClick: onSaveProject, disabled: !projectOpen },
        ]}
      />
      <MenuDropdown
        label="Variante"
        items={[
          { label: 'Nouvelle', onClick: onNewVariant, disabled: !projectOpen },
          { label: 'Dupliquer', onClick: onDuplicateVariant, disabled: !variantSelected },
          { label: 'Supprimer', onClick: onDeleteVariant, disabled: !variantSelected },
        ]}
      />
      <MenuDropdown
        label="Calcul"
        items={[
          { label: 'Calculer', onClick: onRunCalcul, disabled: !variantSelected },
          { label: 'Préférences', onClick: onOpenPreferences, disabled: !projectOpen },
        ]}
      />
      <MenuDropdown
        label="Base de données"
        items={[{ label: 'Conduites', onClick: onOpenConduites }]}
      />
      <MenuDropdown
        label="Affichage"
        items={[
          { label: 'Carte seule', onClick: () => onLayoutModeChange('mapOnly') },
          { label: 'Profil / Table', onClick: () => onLayoutModeChange('profileOnly') },
          { label: 'Vue combinée', onClick: () => onLayoutModeChange('both') },
        ]}
        hint={`Vue actuelle : ${layoutMode === 'both' ? 'combinée' : layoutMode === 'mapOnly' ? 'carte seule' : 'profil / table'}`}
      />
      <MenuDropdown label="Langue" items={[{ label: 'Français', disabled: true }]} hint="Anglais disponible au Lot 7" />
      <MenuDropdown label="Aide" items={[{ label: 'À propos', onClick: onAbout }]} />
    </header>
  )
}
