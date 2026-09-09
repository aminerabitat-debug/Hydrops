# 9. Stratégie de tests pour valider les calculs d'ingénierie

Un bug dans l'UI est gênant ; un bug dans `hydrops-engine` produit un dimensionnement d'ouvrage hydraulique faux, potentiellement livré à un client sans que personne ne s'en aperçoive. La stratégie de test est donc structurée autour d'un principe : **le moteur de calcul est le composant le plus critique du système et doit être le plus rigoureusement testé**, avec un niveau de preuve supérieur à celui d'une UI ou d'un CRUD classique.

## 9.1 Pyramide de test adaptée au projet

```
        ▲  E2E (Playwright) — parcours utilisateur complet, peu nombreux
        │  Import KML → calcul → export rapport
        │
        │  Tests d'intégration API — jobs async, purge de session,
        │  round-trip .hydrops (export puis réimport = même contenu)
        │
        │  Tests de référence métier — cas d'ingénierie connus,
        │  comparés à une solution analytique ou un calcul manuel documenté
        │
        │  Tests unitaires du moteur — chaque sous-module de hydrops-engine
        │  isolément (topology, hydraulics, optimization, economics, trench)
        ▼  Tests de propriété (property-based) — invariants mathématiques
           sur un espace large d'entrées générées
```

La base de la pyramide (tests unitaires + tests de propriété + cas de référence) porte l'essentiel de la confiance sur la **correction des calculs**. Le sommet (E2E) valide que l'assemblage fonctionne, pas l'exactitude numérique.

## 9.2 Tests unitaires du moteur (`packages/hydrops-engine/tests`)

Chaque sous-module se teste **sans réseau, sans base de données, sans API** — c'est la raison d'être de son isolation architecturale ([07-calcul-hydraulique-optimisation.md](07-calcul-hydraulique-optimisation.md) §7.1) :

- `topology` : construction d'un graphe orienté arborescent, détection de cycle (doit être rejetée), calcul de PK cumulé sur des cas à raccordements multiples, résolution correcte de l'ordre topologique.
- `hydraulics` : pour un segment isolé à `(Q, DI, rugosité, longueur)` fixés, la perte de charge calculée par Darcy-Weisbach/Colebrook doit correspondre à une valeur de référence connue (voir §9.3) à une tolérance numérique explicite près (ex. 1e-6 relatif) ; test similaire pour Hazen-Williams et Swamee-Jain ; test de non-régression sur le nombre d'itérations/critère de convergence de Colebrook.
- `trench` : les formules de métré (§11 du cahier des charges) sont des égalités arithmétiques exactes — testées avec des valeurs numériques simples calculées à la main, tolérance quasi nulle (V1-08 : "applique exactement la formule validée", donc un test qui vérifie l'exactitude, pas une approximation).
- `economics` : VAN et coût actualisé du m³ sur des séries temporelles construites à la main (horizon court, ex. 3–5 ans, calculable manuellement), avec et sans réinvestissement/valeur résiduelle activés indépendamment (couvre V1-09).
- `optimization` (gravitaire) : sur un cas à solution évidente (un seul DN commercial respecte les contraintes), vérifier que c'est bien celui-ci qui est choisi, et qu'aucun critère de coût n'influence le résultat même si des coûts incohérents sont injectés dans le `catalog` de test (test de non-régression sur V1-05 : si quelqu'un branche accidentellement le coût dans l'objectif gravitaire, ce test doit rougir).
- `optimization` (pompé) : cas à deux DN candidats avec un compromis CAPEX/OPEX construit pour qu'un des deux soit clairement optimal — vérifie que l'algorithme compare bien un coût actualisé sur la période d'analyse (V1-06), pas un CAPEX seul ou un OPEX seul.
- `validation` : chaque code d'alerte (`PRESSURE_BELOW_MIN`, `PRESSURE_CLASS_EXCEEDED`, `VELOCITY_EXCEEDED`, `MISSING_COST_DATA`, `MISSING_ELEVATION_DATA`, `FORCING_BLOCKS_OPTIMIZATION`, §3.10) a au moins un test qui construit délibérément la situation qui doit le déclencher, et un test qui vérifie qu'il ne se déclenche **pas** à tort sur un cas conforme voisin.

## 9.3 Cas de référence métier (golden cases)

Un dossier `packages/hydrops-engine/tests/reference_cases/` contient des scénarios hydrauliques complets (topologie + résultats attendus), chacun documenté avec :
- l'énoncé du cas (ex. "conduite gravitaire simple, réservoir amont fixe, un point de livraison aval"),
- la méthode de calcul de référence utilisée pour établir la valeur attendue (calcul manuel documenté en commentaire, ou comparaison à un exemple publié dans un ouvrage de référence d'hydraulique — Chaudhry, Bureau of Reclamation, etc. — cité explicitement),
- la tolérance acceptée et sa justification.

Ces cas jouent le rôle de **suite de non-régression prioritaire** : toute modification du moteur (y compris un simple refactor) doit les faire passer avant merge. Ce sont eux, pas les tests unitaires atomiques, qui donnent la confiance qu'un ingénieur peut avoir dans le logiciel — ils doivent être relus et validés par un profil hydraulicien, pas seulement par un développeur.

## 9.4 Tests de propriété (property-based testing)

Complément aux golden cases : utiliser `hypothesis` (Python) pour vérifier des **invariants** sur un espace large d'entrées générées aléatoirement (mais de façon reproductible, graine fixée) plutôt que des valeurs ponctuelles :
- monotonie : à `(DI, rugosité, longueur)` fixés, la perte de charge croît strictement avec `Q` ;
- cohérence dimensionnelle : jamais de `DI` négatif ou nul en sortie d'optimisation ;
- la contrainte "DI non croissant vers l'aval" (§10) est vérifiée sur toute solution produite par l'optimiseur, quel que soit le réseau généré ;
- déterminisme : deux appels à `calculate()` avec des arguments strictement identiques produisent un `Results` strictement identique (sérialisé, comparé octet à octet) — ce test protège directement l'exigence de déterminisme énoncée dans la vision produit ([cdc §1](../functional-spec/cahier-des-charges-v1.md#1-objet-et-vision)).

## 9.5 Tests du format `.hydrops` et de la traçabilité

- **Round-trip** : `export(import(f)) == f` sur le contenu sémantique (pas nécessairement l'octet ZIP brut, mais chaque JSON interne validé champ à champ) — garantit qu'ouvrir puis enregistrer un projet ne perd et n'altère aucune donnée.
- **Validation de schéma** : chaque fichier interne au `.hydrops` est validé contre son JSON Schema (`packages/hydropack/schema/`, [04-format-hydrops.md](04-format-hydrops.md)) à l'import ; un test dédié vérifie qu'un fichier corrompu/non conforme est rejeté avec une erreur explicite, jamais accepté silencieusement avec des champs manquants traités comme `null`.
- **Invalidation de résultats** (V1-03) : test qui modifie un champ dépendant (ex. un DN forcé) après un calcul réussi et vérifie que `input_hash` change en conséquence et que la variante passe bien en `stale`, sans que `results.json` existant soit supprimé.
- **Traçabilité de bout en bout** (V1-11) : un `Results` généré doit permettre de retrouver, sans accès à une base vivante, la version exacte du moteur, du `catalog` et de la source DEM utilisées — testé en générant un `Results`, en modifiant ensuite le `catalog` "vivant", et en vérifiant que le `Results` déjà produit référence toujours l'ancienne version.

## 9.6 Tests d'intégration API et de confidentialité

- Cycle de vie complet d'une session (création → import → édition → calcul asynchrone → export → purge) via des tests d'intégration FastAPI (`TestClient`/`httpx`), avec une base Postgres de test (conteneur éphémère en CI).
- Test explicite de purge : après expiration simulée du TTL ou déconnexion, vérifier qu'aucune ligne du schéma `session` ne subsiste pour cette session (requête directe sur la base de test) — c'est un test de **confidentialité**, pas seulement de fonctionnalité, il doit faire partie de la CI bloquante, pas d'une suite optionnelle.
- Test de non-fuite dans les logs : capturer les logs générés pendant un scénario avec des données de projet distinctives (ex. un nom de client factice improbable) et vérifier qu'elles n'apparaissent dans aucune ligne de log.
- Test du refus de rapport "final" en présence d'une alerte bloquante (§17, [05-api.md](05-api.md) §5.10).

## 9.7 Tests end-to-end (Playwright)

Un nombre volontairement restreint de parcours complets, représentatifs des règles de validation V1-01 à V1-11 :
- import KML → PK et profil DEM générés → carte/profil/table synchronisés lors d'une sélection (V1-01, V1-02) ;
- duplication de variante → modification de l'original → vérifier que la copie n'est pas affectée (V1-03) ;
- forçage d'un DN rendant l'optimisation infaisable → vérifier l'alerte bloquante visible dans l'UI, pas seulement dans une réponse API (V1-04 à V1-07) ;
- export d'un rapport avec une alerte bloquante active → vérifier le refus ou l'estampillage "brouillon" (§17).

Ces tests valident l'assemblage UI/API, pas l'exactitude numérique — cette dernière est déjà couverte en amont (§9.2–9.4), ce qui évite de dupliquer des assertions numériques fragiles dans des tests E2E lents.

## 9.8 Matrice de traçabilité V1-01 → V1-11

| Règle | Type de test principal | Emplacement |
|---|---|---|
| V1-01 | Unitaire (`topology`) + E2E | `packages/hydrops-engine/tests/topology`, E2E import |
| V1-02 | E2E (synchro client) | E2E sélection carte/profil/table |
| V1-03 | Intégration format (`.hydrops`) + E2E | §9.5, §9.7 |
| V1-04 | Golden cases + unitaire `hydraulics` | §9.2, §9.3 |
| V1-05 | Unitaire `optimization` (gravitaire) | §9.2 |
| V1-06 | Unitaire `optimization` (pompé) | §9.2 |
| V1-07 | Unitaire `structures`/`validation` | §9.2 |
| V1-08 | Unitaire `trench` (exactitude arithmétique) | §9.2 |
| V1-09 | Unitaire `economics` | §9.2 |
| V1-10 | Intégration API (purge de session) | §9.6 |
| V1-11 | Intégration format + traçabilité | §9.5 |

Cette matrice est tenue à jour dans `docs/testing/` au fur et à mesure que chaque lot est implémenté ; elle sert de check-list de recette avant toute mise en production d'un lot.

## 9.9 Outillage recommandé

| Couche | Outil |
|---|---|
| Tests unitaires Python | `pytest` |
| Tests de propriété | `hypothesis` |
| Couverture | `pytest-cov`, seuil élevé et **bloquant en CI spécifiquement sur `packages/hydrops-engine`** (le reste du code peut tolérer un seuil plus souple) |
| Tests d'intégration API | `httpx` + `TestClient` FastAPI, conteneur Postgres/PostGIS éphémère en CI |
| Tests frontend unitaires | `vitest` + `@testing-library/react` |
| Tests E2E | `Playwright` |
| CI | pipeline qui exécute `hydrops-engine` en premier et bloque tout le reste si les golden cases échouent — le calcul est le goulot de confiance, pas un test parmi d'autres |
