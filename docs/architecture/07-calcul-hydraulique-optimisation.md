# 7. Stratégie de calcul hydraulique et d'optimisation

Ce document décrit **l'architecture** du moteur de calcul (structure, contrats, déterminisme, traçabilité), pas les formules d'ingénierie elles-mêmes qui seront implémentées et validées en détail au Lot 3/Lot 4 ([cdc §21](../functional-spec/cahier-des-charges-v1.md#21-ordre-de-développement-recommandé)). L'objectif de la Phase 0 est de garantir que le moteur puisse être **déterministe, testable isolément et traçable** (§17, V1-11), pas de figer les hypothèses hydrauliques.

## 7.1 Principe directeur : moteur pur, sans effet de bord

`hydrops-engine` ([02-arborescence-repository.md](02-arborescence-repository.md)) reçoit un instantané complet des entrées et retourne un `Results` — jamais d'accès DB, fichier ou réseau depuis l'intérieur du moteur. Contrat de plus haut niveau :

```
calculate(
    network: NetworkSnapshot,        # traces + nodes + segments + structures d'une variante
    catalog: CatalogSnapshot,        # diamètres, matériaux, classes, coûts — figés au moment T
    economics: EconomicParams,       # horizon, taux, prix énergie, durées de vie, options
    options: CalculationOptions,     # méthode de frottement, mode d'optimisation, forçages
) -> Results
```

Conséquences directes :
- **Déterminisme** : mêmes arguments ⇒ même `Results`, bit pour bit sur les champs numériques (aux arrondis de virgule flottante près, contrôlés — voir [09-strategie-tests.md](09-strategie-tests.md)). C'est la condition pour des tests de non-régression fiables et pour la confiance de l'ingénieur dans un recalcul.
- **Traçabilité** : `catalog` et `economics` sont des **instantanés versionnés**, pas des références vivantes — un recalcul ultérieur avec un `catalog` mis à jour produit délibérément un nouveau `Results`, jamais une mutation silencieuse de l'ancien (§3.8, §3.9).
- **Testabilité** : le moteur se teste par des cas d'ingénierie de référence sans lancer l'API, la base de données ni le frontend.

## 7.2 Pipeline de calcul (interne à `hydrops-engine`)

```
NetworkSnapshot
     │
     ▼
[topology]   validation graphe orienté arborescent sans boucle, ordre topologique,
             PK cumulé cohérent, résolution des liens de raccordement/piquage
     │
     ▼
[hydraulics] pour chaque segment, dans l'ordre topologique :
               - pertes de charge linéaires (Darcy-Weisbach/Colebrook par défaut,
                 alternatives Hazen-Williams / Swamee-Jain)
               - pertes singulières (% des linéaires, §9)
               - ligne hydraulique et ligne hydrostatique, pressions min/max,
                 enveloppe de pression
               - HMT des stations de pompage (toujours calculée, puis marge
                 utilisateur ajoutée — cf. modèle Structure.attributes.hmt_margin)
               - contrôles : classe de pression, vitesse maximale
     │
     ▼
[validation] production des Alert (Information/Avertissement/Bloquant, §17) —
             une alerte Bloquante n'interrompt pas le calcul des autres segments
             mais marque le Results comme non exploitable pour un livrable final
     │
     ▼
[optimization]  si optimization_mode = auto (par variante/segment non forcé) :
                  - gravitaire : minimise le DN sous contraintes vitesse max +
                    pression min ; le coût n'intervient jamais dans cet objectif (V1-05)
                  - pompé : recherche technico-économique CAPEX / OPEX énergie /
                    coût actualisé (V1-06), sur diamètres commerciaux standards
                  - contrainte structurante appliquée dans les deux cas :
                    DI non croissants vers l'aval sur un même chemin (§10)
     │
     ▼
[economics]  CAPEX (conduites, tranchées, ouvrages), OPEX (énergie, maintenance,
             frais généraux, réactifs, sous-produits), réinvestissement et valeur
             résiduelle si activés indépendamment (V1-09), VAN et coût actualisé du m3
     │
     ▼
[trench]     métrés de tranchée type, formules exactes §11 (V1-08)
     │
     ▼
   Results
```

Chaque étage est un sous-module distinct et testable indépendamment (voir [09-strategie-tests.md](09-strategie-tests.md)) — en particulier `hydraulics` ne connaît rien de `economics`, et `optimization` orchestre les deux sans les fusionner.

## 7.3 Hydraulique : méthodes et choix

- **Par défaut** : Darcy-Weisbach + Colebrook-White (résolution itérative du facteur de frottement — Newton-Raphson ou approximation explicite type Colebrook accélérée, à trancher au Lot 3 avec un critère de convergence documenté et testé).
- **Alternatives conservées** : Hazen-Williams (formule explicite, plus rapide, moins physique) et Swamee-Jain (approximation explicite de Colebrook, évite l'itération). Les trois méthodes sont des implémentations interchangeables derrière une même interface `FrictionModel.head_loss(flow, di, roughness, length) -> head_loss`, sélectionnable par `Calculation.friction_method`.
- **Pertes singulières** : modélisées en V1 comme un pourcentage des pertes linéaires (§9) — pas de catalogue de coefficients de singularités détaillé, cohérent avec le positionnement APS.
- **Contraintes** : vitesse maximale (bloquante si dépassée), **aucune** contrainte de vitesse minimale (explicitement absente du cahier des charges — ne pas l'ajouter par excès de prudence, ce serait une déviation non demandée).
- **Niveau amont gravitaire** : valeur fixe ou plage min/max — quand une plage est fournie, le moteur doit documenter quel scénario (min/max/les deux) pilote le dimensionnement plutôt que de choisir silencieusement une valeur médiane.

## 7.4 Optimisation : deux régimes distincts, pas un solveur générique unique

Le cahier des charges distingue explicitement deux objectifs d'optimisation selon le régime du segment (§10) — l'architecture les traite comme **deux algorithmes différents**, pas un seul solveur paramétré par un poids coût/hydraulique :

- **Segments gravitaires** : problème de satisfaction de contraintes avec objectif "diamètre minimal" — recherche du plus petit DN commercial (parmi ceux compatibles avec la classe de pression et le matériau, dans le respect de la contrainte DI non croissant vers l'aval) qui respecte vitesse max et pression min. Le coût n'est **jamais** un critère ici (V1-05) — l'implémenter autrement serait une non-conformité silencieuse.
- **Segments pompés** : problème d'optimisation technico-économique (CAPEX conduite vs OPEX énergie, actualisés) — recherche parmi les DN commerciaux du compromis minimisant le coût actualisé sur la période d'analyse (V1-06). Une recherche exhaustive sur l'espace réduit des diamètres commerciaux standards est envisageable en V1 (l'espace est petit : quelques dizaines de DN normalisés par matériau/classe) plutôt qu'une métaheuristique — à confirmer au Lot 4 selon la taille réelle des réseaux testés, mais **privilégier l'exhaustif/déterministe tant que la taille du problème le permet**, pour rester cohérent avec l'exigence de déterminisme (une métaheuristique stochastique casserait la reproductibilité bit-à-bit sauf à fixer une graine, ce qui ajoute une variable de traçabilité supplémentaire à gérer).
- **Forçages utilisateur** (§10) : un `Forcing` retire tout ou partie du segment/de la trace concernée de l'espace de recherche de l'optimiseur. Si l'ensemble des forçages rend le problème infaisable (aucune combinaison ne respecte les contraintes), le moteur produit une alerte **Bloquante** `FORCING_BLOCKS_OPTIMIZATION` (§3.10) plutôt que de renvoyer silencieusement le meilleur résultat infaisable.

## 7.5 Exécution asynchrone côté API

Le calcul (et a fortiori l'optimisation pompée) s'exécute dans un job `arq` ([01-architecture-systeme.md](01-architecture-systeme.md) §1.4), jamais en synchrone dans le handler HTTP — même si la durée réelle est souvent courte sur un réseau arborescent V1, ce pattern est retenu dès la Phase 0 pour :
- ne jamais bloquer une requête HTTP sur un calcul dont la durée dépend de la taille du réseau et du nombre de DN candidats,
- permettre l'annulation (`POST /calculations/{job_id}/cancel`, [05-api.md](05-api.md) §5.7),
- fournir un point d'accroche naturel pour paralléliser plus tard (calcul indépendant par branche du graphe arborescent), sans changer le contrat API.

## 7.6 Ce qui reste ouvert pour les Lots 3/4 (assumé, pas traité ici)

- Critère de convergence exact de Colebrook-White (tolérance, nombre d'itérations max).
- Méthode de lissage du profil altimétrique (Lot 2, voir [06-sig-dem.md](06-sig-dem.md) §6.4).
- Seuils par défaut de vitesse maximale et pression minimale par profil régional (point ouvert §20 du cahier des charges, décision produit hors Phase 0 technique).
- Formules paramétriques initiales des stations de pompage/réservoirs/traitement (point ouvert §20) — le modèle de données (§3.7) prévoit déjà les champs porteurs, sans figer les formules.
