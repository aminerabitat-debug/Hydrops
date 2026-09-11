"""Criteres de choix des materiaux des conduites (menu Calcul > Preferences, consigne
utilisateur) — reconstitution du tableau fourni par l'utilisateur (plage de DN x type de fluide
-> materiaux autorises), recroisee avec la liste des 6 fluides du projet (cf.
apps/web/src/shared/ouvrageFields.ts:FLUIDE_OPTIONS). "EB" = beton precontraint = "BP" dans notre
catalogue Conduites. CAO/BVA/BONNA (materiaux "sans pression" du tableau d'origine) ne sont pas
retenus (consigne utilisateur). "PRV" existe desormais dans le catalogue Conduites, recopie de
l'Acier a partir du DN300 (cf. data/pipe_catalog_seed.py:_generate_prv_rows) — un point de depart
editable (cdc §15), pas une verite figee : l'utilisateur peut corriger chaque ligne dans la
fenetre Preferences.

Regle d'application (cf. services/material_criteria.py) : dn_min/dn_max bornent le DN (bornes
incluses, None = pas de borne) ; fluid=None s'applique a tous les fluides. Si AUCUNE regle ne
s'applique a un (DN, fluide) donne, aucune restriction n'est appliquee (tous les materiaux actifs
du catalogue restent candidats) — evite qu'un materiau absent de ce tableau (fonte ductile, acier)
ne devienne silencieusement inutilisable.
"""

from __future__ import annotations

DEFAULT_MATERIAL_CRITERIA: list[dict] = [
    {"dn_min": None, "dn_max": 110, "fluid": None, "materials": ["PEHD"]},
    {"dn_min": 111, "dn_max": 300, "fluid": None, "materials": ["PVC"]},
    {"dn_min": 301, "dn_max": None, "fluid": "Eau potable", "materials": ["PVC", "PEHD", "PRV"]},
    {"dn_min": 301, "dn_max": None, "fluid": "Eau brute", "materials": ["PVC", "PEHD", "PRV"]},
    {"dn_min": 301, "dn_max": None, "fluid": "Eau usée brute", "materials": ["PVC", "PEHD", "PRV"]},
    {"dn_min": 301, "dn_max": None, "fluid": "Eau usée traitée", "materials": ["PVC", "PEHD", "PRV"]},
    {"dn_min": 301, "dn_max": None, "fluid": "Eau déminéralisée", "materials": ["PVC", "PEHD", "PRV"]},
    {"dn_min": 301, "dn_max": None, "fluid": "Eau de mer", "materials": ["BP", "PRV"]},
]
