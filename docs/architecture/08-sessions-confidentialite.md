# 8. Gestion des sessions et confidentialité

Répond directement à V1-10 et au point ouvert §20 "Politique exacte de session, durée d'expiration et purge technique".

## 8.1 Ce qui est confidentiel, ce qui ne l'est pas

Distinction fondatrice, reprise de [01-architecture-systeme.md](01-architecture-systeme.md) §1.4 :

| Donnée | Régime | Justification |
|---|---|---|
| Contenu d'un `.hydrops` (traces, nœuds, segments, structures, résultats) | **Éphémère**, jamais durable côté serveur | V1-10, [cdc §3](../functional-spec/cahier-des-charges-v1.md#3-confidentialité-et-fichier-projet) |
| Bibliothèques `catalog` (diamètres, coûts, matériaux...) | Durable | Donnée de référence de l'application, pas une donnée client (§15) |
| Tuiles DEM | Durable (cache infra) | Donnée publique de terrain, pas une donnée projet ([06-sig-dem.md](06-sig-dem.md) §6.3) |
| Logs applicatifs | Durable mais **sans contenu projet** | "Éviter les données sensibles dans les logs et sauvegardes serveur" (§3) |

## 8.2 Cycle de vie d'une session

1. **Création** : à l'ouverture de l'application (ou au premier appel API), le serveur émet un identifiant de session (UUID) et un TTL (ex. 4 h glissantes, à confirmer avec l'usage réel constaté en Lot 1 — c'est un paramètre de configuration, pas une valeur figée en dur).
2. **Maintien** : chaque appel API prolonge le TTL (`heartbeat` implicite sur toute requête, ou explicite via `POST /sessions/{id}/heartbeat`, [05-api.md](05-api.md) §5.1). Le client envoie un heartbeat périodique tant que l'onglet reste ouvert, même sans action utilisateur, pour éviter une purge intempestive pendant une lecture longue d'un profil complexe.
3. **Purge à la déconnexion** : fermeture explicite (`DELETE /sessions/{id}`) déclenchée par l'action "Fermer"/fermeture d'onglet détectée côté client (`beforeunload` + best-effort `sendBeacon`) → suppression immédiate de toutes les lignes du schéma `session` associées à cette session.
4. **Purge à l'expiration** : un TTL atteint sans heartbeat marque la session comme expirée ; un job planifié (`arq` cron, ex. toutes les 5 minutes) supprime les lignes `session` des sessions expirées.
5. **Balayage des sessions orphelines** : au-delà de l'expiration normale (crash serveur, worker tué, navigateur fermé brutalement sans `beforeunload`), un second job planifié à fréquence plus basse (ex. toutes les heures) recherche les sessions dont le TTL est dépassé depuis un délai de sécurité supplémentaire et force leur purge, y compris les fichiers temporaires ou jobs de calcul orphelins associés.

Ces trois mécanismes (déconnexion explicite, expiration TTL, balayage orphelin) sont **indépendants et redondants** : aucun ne doit être la seule ligne de défense contre une rétention prolongée de données projet.

## 8.3 Ce que la purge supprime concrètement

- Toutes les lignes du schéma Postgres `session` dont la clé de session correspond (traces, nœuds, segments, structures, résultats de calcul en cours, état de job).
- Tout fichier temporaire éventuellement matérialisé sur disque pendant un traitement (ex. dépaquetage d'un `.hydrops` volumineux) — utiliser un répertoire temporaire dédié par session, supprimé en bloc, jamais un répertoire partagé entre sessions.
- Tout job `arq` en attente ou en cours référençant cette session est annulé, pas seulement ignoré (éviter qu'un job en file continue de produire un `Results` après la purge de son `variant_id`).
- Les fichiers de rapport générés (§5.10) portent leur propre TTL court, indépendant du TTL de session, et sont supprimés dès téléchargement confirmé ou à leur propre expiration.

Ce que la purge **ne supprime pas** : le `catalog` (durable par conception) et le cache de tuiles DEM (durable, non lié à une session, §6.3).

## 8.4 Journalisation

- Les logs applicatifs (accès, erreurs, performance) ne contiennent **aucune donnée métier de projet** : pas de coordonnées, pas de débits, pas de noms de client/projet en clair. Utiliser des identifiants opaques (session_id, variant_id) dans les logs, jamais les valeurs qu'ils désignent.
- Un log d'erreur de calcul peut inclure le `code` d'une `Alert` et des métriques agrégées (nombre de segments, durée), pas les valeurs d'entrée qui ont déclenché l'alerte.
- Aucune sauvegarde automatique de base de données ne doit inclure le schéma `session` — si une politique de backup Postgres globale existe, elle doit explicitement exclure ce schéma (ou le schéma `session` doit vivre dans une instance/tablespace séparée si la politique de backup ne peut pas être filtrée par schéma).

## 8.5 Authentification V1 vs évolution SaaS

V1 : "usage professionnel/interne" ([cdc §1](../functional-spec/cahier-des-charges-v1.md#1-objet-et-vision)) — une authentification simple (compte partagé d'équipe, ou pas d'authentification si déploiement sur réseau interne contrôlé) suffit ; le point important est que **la notion de session éphémère ne dépend pas du mécanisme d'authentification choisi**. C'est ce découplage qui permettra, pour un futur SaaS, d'ajouter une couche OIDC/multi-tenant en amont des routers sans toucher au modèle de session ni au moteur de calcul ([01-architecture-systeme.md](01-architecture-systeme.md) §1.6).

## 8.6 Ce que ça implique pour le développement (Lot 1 et Lot 7)

- Le Lot 1 (socle) doit livrer le mécanisme de session éphémère et sa purge **dès le début**, pas comme un durcissement de fin de projet — c'est une contrainte structurante du modèle de données (schéma `session` vs `catalog`), pas une fonctionnalité additive.
- Le Lot 7 (durcissement, [cdc §21](../functional-spec/cahier-des-charges-v1.md#21-ordre-de-développement-recommandé)) valide cette politique avec des tests d'intégration dédiés (voir [09-strategie-tests.md](09-strategie-tests.md) §9.6) : simulation de déconnexion brutale, vérification qu'aucune ligne `session` ne persiste au-delà du TTL + délai de sécurité, audit des logs pour absence de donnée métier.
