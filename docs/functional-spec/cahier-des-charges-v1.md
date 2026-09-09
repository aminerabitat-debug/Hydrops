Source : `HydroPS_V1_Cahier_des_charges_fonctionnel.docx` (V1.0, 7 septembre 2026), copié ici pour référence versionnée dans le dépôt.

Voir le fichier original pour la mise en forme. Le contenu textuel intégral est repris tel quel ci-dessous pour être diffable et citable depuis les autres documents d'architecture (`[cdc §n]`).

---

## 1. Objet et vision

HydroPS est une application web professionnelle destinée au dimensionnement préliminaire (APS / Preliminary Design) des systèmes d'adduction et de transport d'eau. La V1 couvre les adductions gravitaires, par pompage et mixtes, avec comparaison hydraulique et technico-économique de variantes. Le moteur de calcul est déterministe.

Usage initial professionnel/interne, avec architecture compatible avec un futur SaaS international. Positionnement APS : suffisamment détaillé pour comparer et dimensionner, sans dériver vers l'EXE. Cartographie SIG, profil en long, table de données et résultats synchronisés. Données projet non conservées durablement côté serveur. Optimisation automatique par défaut, avec possibilité de forcer localement certains choix.

## 2. Périmètre V1

**Inclus** : adductions gravitaires, pompées et mixtes ; réseaux arborescents multi-traces ; import KML/KMZ (une ligne continue par trace) ; DEM global et profil topo ; hydraulique, optimisation, CAPEX/OPEX, VAN ; livrables APS PDF/XLSX/DOCX.

**Hors périmètre V1** : réseaux maillés / solveur de boucles complet ; dessin libre des tracés ; import GeoTIFF (prévu ultérieurement) ; dimensionnement détaillé process des stations de traitement ; APD/EXE détaillé ; DWG/DXF/SHP avancés (phase ultérieure).

## 3. Confidentialité et fichier projet

Le projet est enregistré localement par l'utilisateur dans un fichier `.hydrops`. Le serveur peut utiliser une base PostgreSQL/PostGIS uniquement comme espace de travail temporaire de session. Purge à la déconnexion, à l'expiration de session et via nettoyage des sessions orphelines. Éviter les données sensibles dans les logs et sauvegardes serveur.

Le fichier `.hydrops` est un paquet structuré de type ZIP contenant JSON, KML/KMZ d'origine et résultats structurés. Les résultats stockés dans `.hydrops` sont invalidés lorsque leurs entrées dépendantes sont modifiées.

| Élément .hydrops | Contenu |
|---|---|
| `metadata.json` | Version format, version logiciel, unités et métadonnées techniques |
| `project.json` | Projet, paramètres généraux et références |
| `techno_economic.json` | Hypothèses technico-économiques |
| `/traces/` | Géométries KML/KMZ importées |
| `/variants/` | Variantes, objets, forçages, règles |
| `/results/` | Résultats hydrauliques et économiques |
| `/assets/` | Éléments optionnels légers |

## 4. Interface utilisateur

Barre de menus supérieure et barre d'accès rapide immédiatement en dessous. Arborescence projet à gauche sur toute la hauteur utile. Espace central adaptable : Carte seule, Profil/Données seul, ou vue combinée avec séparateur réglable. Profil et table de données occupent le même panneau et sont alternés par onglet/bouton intégré. Barre d'état en bas : contexte, sélection, état de calcul, avertissements. Carte, profil et table sont bidirectionnellement synchronisés (survol, sélection, positionnement). Le même espace central peut afficher les résultats.

| Menu | Commandes principales |
|---|---|
| Fichier | Nouveau ; Ouvrir .hydrops ; Enregistrer ; Enregistrer sous ; Exporter |
| Variante | Nouvelle ; Dupliquer ; Supprimer |
| Calcul | Options de calcul ; Lancer calcul ; Tranchée type |
| Base de données | Diamètres ; coûts ; matériaux ; classes de pression ; bibliothèques |
| Affichage | Carte ; Profil ; Table ; Résultats |
| Langue | Français ; English |
| Aide | Documentation ; À propos |

## 5. Modèle métier

### 5.1 Projet et paramètres technico-économiques

Projet : identifiant, nom, localisation, client, description, devise, type d'eau par défaut. Horizon d'étude, durée de vie du projet, année du premier investissement, taux d'actualisation, prix de l'énergie. Volume annuel constant ou table d'évolution jusqu'à l'horizon, puis maintien constant jusqu'à la fin de vie. Durées de vie par catégorie : conduites, génie civil, électromécanique, instrumentation/contrôle, autres. Options utilisateur : intégrer ou non les réinvestissements ; intégrer ou non la valeur résiduelle.

### 5.2 Variante, trace, nœud et segment

Une variante contient une ou plusieurs traces continues et peut être dupliquée intégralement. Chaque KML/KMZ correspond exactement à une trace continue ; les branches sont importées séparément. Une trace peut se raccorder/piquer sur une autre trace via un lien nodal explicite. Le réseau V1 est un graphe orienté arborescent, sans boucles. Le type d'eau est modifiable par trace.

| Objet | Attributs essentiels |
|---|---|
| Trace | id, géométrie, longueur, PK, sens hydraulique, ordre topologique, type d'eau |
| Nœud | id, type, PK, X, Y, Z, débit injecté, débit prélevé, trace, lien parent |
| Segment | nœuds amont/aval, PK, longueur, matériau, DN, DI, classe, rugosité, débit et résultats |

## 6. SIG, topographie et profil

Import et validation de la continuité géométrique ; calcul du PK cumulé ; possibilité d'inverser le sens hydraulique. Échantillonnage du profil altimétrique depuis un DEM global. Conservation du profil brut et génération d'un profil lissé. Détection automatique des points hauts et bas sur le profil lissé ; ce sont des candidats que l'utilisateur valide ou non. Les ouvrages sont positionnables depuis la carte ou le profil, avec projection/snap sur la trace. Architecture préparée pour un futur import GeoTIFF.

## 7. Table principale unique

HydroPS utilise une seule table de données. Les champs linéaires d'une ligne appartiennent au segment associé au nœud amont. Node ID ; type ; X ; Y ; Z ; distance partielle ; distance cumulée ; débit. DN ; DI ; rugosité ; matériau ; classe. Pertes de charge linéaires et totales. Charge hydraulique min/max ; charge hydrostatique min/max. Pression au sol min/max ; enveloppe de pression maximale. Sélecteur de colonnes par cases à cocher. Avant calcul : champs géométriques et d'entrée. Après calcul : activation des champs résultats.

## 8. Ouvrages

| Ouvrage | Règle / attributs V1 |
|---|---|
| Point haut | Détection candidate + validation utilisateur ; coût fonction du DN |
| Point bas | Détection candidate + validation utilisateur ; coût fonction du DN |
| Vanne de sectionnement | Placement automatique tous les 5 km par défaut ; distance modifiable ; déplacement individuel possible ; coût f(DN) |
| Vanne de régulation | Objet fonctionnel APS |
| Brise-charge | Objet fonctionnel APS |
| Réservoir | Volume, géométrie circulaire/rectangulaire, semi-enterré/surélevé, hauteur si surélevé |
| Station de pompage | Sur réseau ; sur réservoir ; avec bâche de régulation ; forage ; submersible ; puits/booster well |
| Prise d'eau | Mer ; barrage ; rivière ; canal ; piquage conduite ; réservoir |
| Station de traitement | Eau de surface ; dessalement ; déminéralisation eau saumâtre ; eaux usées ; chloration ; Fe/Mn |

## 9. Hydraulique

Méthode par défaut : Darcy-Weisbach avec Colebrook-White. Méthodes alternatives conservées : Hazen-Williams et option Swamee-Jain pour le facteur de frottement. Pertes singulières V1 : pourcentage des pertes de charge linéaires. Niveau amont gravitaire : valeur fixe ou plage min/max. Calcul des lignes hydraulique et hydrostatique, des pressions min/max et de l'enveloppe de pression. Contrôle de compatibilité avec la classe de pression. Contrainte de vitesse maximale ; aucune contrainte de vitesse minimale. Station de pompage : HMT toujours calculée puis marge utilisateur ajoutée ; puissance à partir de rendements explicites.

## 10. Optimisation

Mode automatique par défaut. Forçage possible du DN, matériau et/ou classe de pression sur une trace entière ou entre deux nœuds. Contrainte structurante : diamètres intérieurs non croissants vers l'aval, afin de réduire l'espace de recherche. Segments gravitaires : objectif = minimisation des diamètres, sous contraintes de vitesse maximale et pression minimale. Le coût n'intervient pas dans cette optimisation. Segments pompés : optimisation technico-économique CAPEX / énergie OPEX / coût actualisé. Diamètres commerciaux standards uniquement.

## 11. Tranchée type et métrés

La largeur B est définie par une règle paramétrable fonction du DN. La hauteur de remblai primaire h_rp est mesurée au-dessus de la génératrice supérieure de la conduite.

```
H = h_lit + D_ext + h_rp + h_rs
V_lit = L x B x h_lit
V_conduite = (pi x D_ext^2 / 4) x L
V_remblai_primaire = L x B x (D_ext + h_rp) - V_conduite
V_remblai_secondaire = L x B x h_rs
```

La règle de largeur peut être définie par plages de DN (ex. largeur fixe pour petits DN, puis DN + 2 x jeu latéral).

## 12. Moteur CAPEX

| Poste | Principe V1 |
|---|---|
| Conduites | Longueur x prix unitaire selon matériau, DN et classe |
| Tranchées | Excavation + lit de pose + remblai primaire + remblai secondaire |
| Points hauts/bas | Courbe/table de coût en fonction du DN |
| Vannes | Coût en fonction du DN |
| Réservoirs | f(volume, géométrie, type, hauteur) ; capacités standards marché + saisie libre |
| Stations de pompage | f(Q, HMT, puissance, type de station) avec composante GC/EM paramétrable |
| Stations de traitement | Approche APS f(débit, type), sans dimensionnement process détaillé |
| Coûts annexes | Saisie utilisateur : terrain, servitudes, accès, dévoiements, raccordements spéciaux, autres |

Les tables et courbes de coût sont éditables et destinées à être calibrées par région/pays, devise et année de référence.

## 13. Moteur OPEX

| Poste | Principe |
|---|---|
| Énergie | Énergie annuelle issue du fonctionnement hydraulique x tarif énergétique |
| Maintenance | Règle paramétrable par catégorie d'actif, pouvant être exprimée en % ou par table |
| Frais généraux | Valeur/règle paramétrable |
| Réactifs | Pour stations de traitement : consommation x coût unitaire, à un niveau APS |
| Sous-produits | Traitement/transport/évacuation des boues, saumures ou autres sous-produits selon le type de station |

## 14. Réinvestissement, valeur résiduelle et indicateurs

Ces deux mécanismes sont optionnels et activés séparément par l'utilisateur. Réinvestissement : lorsque la durée de vie d'une catégorie est inférieure à l'horizon d'analyse, les renouvellements correspondants peuvent être intégrés aux années concernées. Valeur résiduelle : si activée, prise en compte en fin d'horizon selon la durée de vie restante de l'actif.

```
VAN_coûts = Somme_t [ Coûts_t / (1+r)^t ] - Valeur_résiduelle_actualisée
Coût_actualisé_m3 = VAN_coûts / Somme_t [ Volume_t / (1+r)^t ]
```

## 15. Base de données technique et coûts

Diamètres standards, DI/DE, matériaux, classes de pression et rugosités. Prix des conduites et prix unitaires de terrassement/remblai. Courbes/tables de coûts des ouvrages. Capacités standards de réservoirs inspirées du marché, avec saisie libre. Coefficients de coûts régionaux et année de référence à terme. Toutes les valeurs doivent rester traçables et éditables ; éviter les coefficients universels opaques.

## 16. Livrables V1

Rapport de conception APS / Preliminary Design configurable. Note de calcul hydraulique. Métré et estimation CAPEX/OPEX. Profil en long multi-feuilles avec terrain, HGL, hydrostatique, DN, matériaux, classes et ouvrages. Comparatif des variantes : CAPEX, OPEX, énergie, VAN, coût actualisé du m3 et critères hydrauliques. Formats prioritaires : PDF et XLSX ; DOCX pour rapport modifiable. La variante la moins chère peut être identifiée, mais la variante recommandée reste une décision de l'ingénieur.

## 17. Traçabilité, contrôles et avertissements

Les rapports rappellent les méthodes, paramètres hydrauliques, hypothèses économiques, source DEM et version de la base de coûts. Niveaux d'alerte : Information, Avertissement, Bloquant. Exemples : pression insuffisante, dépassement de classe, vitesse excessive, coût manquant, données altimétriques absentes, forçage empêchant l'optimisation. Une erreur bloquante ne doit pas conduire silencieusement à un livrable présenté comme valide.

## 18. Internationalisation

Codes internes stables indépendants de la langue ; labels FR/EN traduits. Le concept interne est Preliminary Design ; APS est un libellé régional. Devise, unités, format des nombres et format de page configurables. Personnalisation entreprise : logo, client, projet, numéro document, révision, date d'émission, préparé/vérifié/approuvé.

## 19. Règles de validation V1

| ID | Critère d'acceptation |
|---|---|
| V1-01 | Un KML/KMZ valide crée une trace continue avec PK et profil DEM. |
| V1-02 | Carte, profil et table restent synchronisés pour sélection et positionnement. |
| V1-03 | Une variante est duplicable sans altérer l'original ; ses résultats sont invalidés si les entrées changent. |
| V1-04 | Le calcul hydraulique respecte Darcy-Weisbach/Colebrook par défaut et les forçages utilisateur. |
| V1-05 | L'optimisation gravitaire minimise les DN sans utiliser le coût comme objectif. |
| V1-06 | L'optimisation pompée évalue le compromis CAPEX-énergie sur la période d'analyse. |
| V1-07 | Les vannes de sectionnement sont proposées tous les 5 km par défaut et restent déplaçables. |
| V1-08 | Le métrage du remblai primaire applique exactement la formule validée. |
| V1-09 | Réinvestissement et valeur résiduelle peuvent être activés/désactivés indépendamment. |
| V1-10 | Aucune donnée projet n'est conservée durablement sur le serveur après purge de session. |
| V1-11 | Les résultats exportés sont traçables jusqu'aux hypothèses et versions de bases utilisées. |

## 20. Points restant à préciser avant implémentation détaillée

Choix du fournisseur/source DEM global et stratégie de cache. Format exact de la marge HMT (mCE, %, ou les deux). Seuils par défaut de vitesse maximale et pression minimale par profil régional. Bibliothèque initiale de coûts et capacités standards de réservoirs par marché cible. Formules paramétriques initiales des stations de pompage, réservoirs et traitement. Politique exacte de session, durée d'expiration et purge technique. Stack technique, architecture front/back, moteur SIG et stratégie de calcul.

> Ces points sont traités par les décisions d'architecture de la Phase 0 (voir `docs/architecture/`) — certains restent volontairement ouverts pour une décision produit ultérieure (bibliothèques de coûts par marché, seuils régionaux par défaut).

## 21. Ordre de développement recommandé

| Lot | Contenu |
|---|---|
| Lot 1 - Socle | Projet .hydrops, UI, arborescence, import KML/KMZ, carte/profil/table |
| Lot 2 - Topographie | DEM, profil brut/lissé, PK, points hauts/bas candidats |
| Lot 3 - Métier hydraulique | Nœuds, segments, ouvrages, graphe, calcul hydraulique |
| Lot 4 - Optimisation | Gravitaire puis pompage, forçages et contrôles |
| Lot 5 - Économie | Métrés, CAPEX/OPEX, réinvestissement, valeur résiduelle, VAN |
| Lot 6 - Livrables | PDF/XLSX/DOCX, profil multi-feuilles, comparatif variantes |
| Lot 7 - Durcissement | Tests, sécurité/confidentialité, i18n, performance, packaging |
