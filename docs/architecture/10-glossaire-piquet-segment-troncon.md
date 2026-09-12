# 10. Glossaire Piquet / Segment / Tronçon / Ouvrage — DN comme tableau par piquet

Ce document fixe la terminologie **à utiliser dorénavant** dans tout le projet (code, commentaires,
échanges) pour ces quatre notions, suite à une clarification explicite de l'utilisateur — elle
**corrige/précise** [03-modele-donnees.md §3.6](03-modele-donnees.md) sur un point important : un
Segment ne relie pas forcément deux ouvrages réels, il relie deux **piquets consécutifs**.

## 10.1 Définitions

- **Piquet** — un point du profil en long. Peut être un simple échantillon de terrain (DEM, tous
  les ~20 m par défaut) ou la position d'un ouvrage/nœud. C'est l'unité atomique de position le
  long d'une trace — chaque piquet a un PK cumulé, une altitude, et (X, Y).
- **Segment** — la liaison entre **deux piquets consécutifs**, qu'ils portent un ouvrage réel ou
  non. Un segment porte des caractéristiques qui lui sont **propres** : matériau, DN, classe de
  pression, DI, rugosité, vitesse, pertes de charge, etc. Un Segment a un DN **unique**.
- **Tronçon** — un groupe de segments successifs (aujourd'hui délimité par deux ouvrages réels
  consécutifs le long d'une trace, avec zéro ou plusieurs piquages transparents entre les deux).
  Un tronçon n'a **pas** un DN unique : c'est un **tableau de valeurs**, une par segment qui le
  compose.
- **Ouvrage** (ou **nœud**) — un objet placé au niveau d'un piquet (réservoir, station de pompage,
  brise-charge, piquage, vanne, etc.). Tous les piquets ne portent pas un ouvrage — la plupart sont
  de simples points d'échantillonnage du terrain.

## 10.2 Conséquence directe : le DN d'un tronçon est un tableau, pas un scalaire

Comme le profil Data (`DataTable.tsx`) ne représente pas les segments comme des lignes à part — il
affiche des **piquets** — et que la convention retenue est d'attribuer l'information d'un segment à
son **piquet aval** (déjà le cas pour Matériau/DN/Classe/DI/Rugosité affichés par piquet), le "DN
d'un tronçon" doit se comprendre comme **un tableau de DN, un par piquet** (le DN du segment qui se
termine à ce piquet) — jamais une valeur scalaire unique appliquée à tout le tronçon.

## 10.3 Écart avec l'implémentation actuelle (à traiter dans un lot ultérieur, pas fait ici)

L'entité persistée `Segment` (`hydropack.models.Segment`, table `variants/*/segments.json`) relie
aujourd'hui deux **nœuds réels** (`upstream_node_id`/`downstream_node_id`) et peut donc couvrir de
nombreux piquets (plusieurs km, sans aucun ouvrage entre les deux) tout en ne portant qu'un DN
unique pour toute cette plage — ce qui correspond, dans la terminologie ci-dessus, à un **groupe de
segments réduit à une seule valeur** plutôt qu'à un vrai tableau par piquet. C'est cet écart qui a
fait qu'un cas réel (tronçon de ~29,9 km sans jonction intermédiaire) n'a produit aucune
optimisation télescopique : il n'existe aujourd'hui qu'UNE seule "case" de DN pour tout le tronçon.

Faire correspondre l'implémentation à ce glossaire (DN par piquet, pas par entité `Segment`
réel-nœud-à-réel-nœud) est un changement d'architecture qui reste à concevoir et implémenter — non
traité par ce document, qui ne fait qu'enregistrer la terminologie et le constat.
