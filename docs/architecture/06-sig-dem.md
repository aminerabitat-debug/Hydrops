# 6. Stratégie SIG et DEM

Répond au point ouvert §20 "Choix du fournisseur/source DEM global et stratégie de cache" et à [cdc §6](../functional-spec/cahier-des-charges-v1.md#6-sig-topographie-et-profil).

## 6.1 Import et validation géométrique (KML/KMZ)

- Un KML/KMZ = une trace continue (V1-01). Validation à l'import : géométrie mono-partie (pas de MultiLineString), pas d'auto-intersection significative, coordonnées en WGS84.
- Le fichier source est conservé tel quel dans le paquet `.hydrops` (`traces/<id>.source.kml`, [04-format-hydrops.md](04-format-hydrops.md)) — toute transformation (simplification, calcul de PK) est dérivée et reproductible, jamais destructive de l'original.
- Calcul du PK cumulé par intégration de la distance géodésique le long de la polyligne (projection locale UTM appropriée à la zone du projet pour la précision métrique, pas de calcul en degrés bruts).
- Sens hydraulique : `as_drawn` ou `reversed`, un simple flag qui inverse l'ordre de parcours pour le calcul du PK et de la topologie — ne modifie jamais la géométrie source stockée.

## 6.2 Choix de la source DEM

**Décision Phase 0 : Copernicus GLO-30 (DEM global, résolution ~30 m, licence ouverte)** comme source par défaut.

Justification :
- Couverture mondiale, cohérent avec l'ambition "SaaS international" ([cdc §1](../functional-spec/cahier-des-charges-v1.md#1-objet-et-vision)).
- Licence permettant un usage commercial et un cache serveur durable, sans coût récurrent par requête (contrairement à des API DEM commerciales facturées à l'appel).
- Résolution suffisante pour un usage **APS** (positionnement §1 : "sans dériver vers l'EXE") — une précision centimétrique n'est pas l'objectif à ce stade.

Le service est conçu **derrière une interface** (`DemProvider`) pour rester remplaçable sans impact sur `hydrops-engine` ni le modèle de données : un projet donné peut évoluer vers une source plus précise (LIDAR local, GeoTIFF utilisateur) sans changer `Node.z_source` au-delà de la valeur `"dem"` déjà prévue, ni la structure de `elevation_profile` dans `trace_geometry.schema.json`.

**Implémentation Lot 1 : cascade d'API publiques**, faute d'infrastructure de tuiles Copernicus à opérer nous-mêmes à ce stade — dans l'ordre : Open-Meteo Elevation (rapide, sans clé), OpenTopoData ASTER30m (topo dédiée), Open-Elevation (dernier recours). Une source échoue pour le lot entier (timeout, erreur réseau, réponse malformée) → la suivante est tentée ; l'échec n'est remonté (alerte `MISSING_ELEVATION_DATA`, §17) que si les trois échouent — jamais de repli silencieux vers une valeur synthétique en production. `dem_source`/`dem_version` enregistrés reflètent la source qui a effectivement répondu (`hydrops_api/services/dem.py::CascadingDemProvider`), pas un identifiant générique masquant l'origine réelle de la donnée.

## 6.3 Stratégie de cache des tuiles

Point de clarification important pour la confidentialité : **les tuiles DEM sont des données publiques de terrain, pas des données projet**. Leur cache peut donc être durable sur le serveur sans contredire V1-10 (aucune donnée projet conservée durablement) — c'est un cache d'infrastructure, au même titre qu'un cache de tuiles de fond de carte.

- Cache disque/objet (par tuile, clé = identifiant de dalle + version de source), peuplé à la demande (lazy) lors du premier import de trace dans une zone donnée.
- Pas de pré-téléchargement mondial en V1 : coût de stockage disproportionné par rapport à l'usage réel (projets ponctuels, pas un usage cartographique généraliste).
- Le service DEM enregistre `dem_source` + `dem_version` avec chaque échantillonnage — cette paire est copiée dans `Calculation.dem_source_version` et `Results.traceability` pour la traçabilité (V1-11, §17) : si la source DEM change de version (mise à jour Copernicus), les calculs existants restent attribuables à la version utilisée au moment de leur exécution.

## 6.4 Échantillonnage et profil

- Échantillonnage du profil altimétrique brut à un pas régulier le long du PK (ex. tous les 10–20 m, paramétrable), plus les points de rupture géométrique de la trace.
- Génération d'un profil **lissé** par une méthode de lissage simple et déterministe (ex. moyenne mobile ou spline à fenêtre fixe) — le choix exact de méthode/fenêtre est un paramètre de `hydrops-engine.topology`, documenté et testé en Lot 2 (voir [09-strategie-tests.md](09-strategie-tests.md)), pas figé dans cette Phase 0 au-delà de l'exigence "brut conservé + lissé généré" (§6).
- Détection automatique des points hauts/bas sur le profil **lissé uniquement** (le brut sert de référence visuelle, pas de détection — évite de générer des faux candidats sur du bruit DEM). Chaque candidat devient un `Node` avec `validated: false` tant que l'utilisateur ne l'a pas confirmé ou supprimé (§6, modèle §3.5).

## 6.5 Positionnement des ouvrages

Les ouvrages sont positionnables depuis la carte **ou** le profil, avec projection/snap sur la trace (§6) : une opération géométrique commune (`snap_to_trace(point, trace_geometry) -> pk`) partagée entre les deux vues, implémentée une seule fois côté client (le calcul de PK est une fonction pure sur la géométrie déjà chargée en mémoire — pas besoin d'un aller-retour serveur pour un simple déplacement de curseur), avec confirmation persistée via l'API `network` ([05-api.md](05-api.md) §5.4).

## 6.6 Rôle de PostGIS

PostGIS (schéma `session`, éphémère) est utilisé pour :
- Les requêtes spatiales pendant l'édition d'une session ouverte : recherche du segment le plus proche d'un clic carte, calcul de PK par projection sur géométrie, détection d'auto-intersection à l'import.
- Il ne stocke **aucune tuile DEM** (ça, c'est le cache de tuiles, séparé, durable, non lié à une session) ni aucune géométrie au-delà de la durée de vie de la session en cours.

## 6.7 Préparation à l'import GeoTIFF (hors périmètre V1, anticipé)

`DemProvider` définit déjà la frontière qui permettra d'ajouter un GeoTIFF utilisateur comme source locale prioritaire sur une emprise donnée sans changer le contrat d'échantillonnage (`sample(lat, lon) -> elevation, source, version`). Aucune implémentation n'est faite en V1 (hors périmètre explicite, §2) — c'est une note d'architecture, pas un développement anticipé.
