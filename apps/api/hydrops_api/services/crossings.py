"""Detection des traversees (routes/pistes/voies ferrees, canaux/rivieres/cours d'eau, batiments,
zones urbaines/forestieres) — consigne utilisateur : "afficher et masquer" sur la carte et le
profil. Perimetre MVP, indicatif — base OpenStreetMap (Overpass API), pas un releve topographique
certifie (cf. reserve posee a l'utilisateur) : la couverture/qualite des donnees varie selon la
region, et aucun tag OSM dedie n'existe pour une "chaaba" (cours d'eau intermittent nord-africain)
— seuls les `waterway=*` effectivement cartographies (y compris `intermittent=yes`) sont detectes.
De meme, seules les zones urbaines/forestieres cartographiees comme des WAYS simples (pas les
relations multipolygones, hors perimetre MVP) sont detectees.

Decoupe en deux etapes independantes (consigne testabilite) :
- `fetch_osm_features` : appel reseau a Overpass, retourne les elements bruts (dict).
- `compute_crossings` : geometrie pure (shapely), testable sans reseau avec des elements
  synthetiques.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import dataclass
from typing import Literal, Optional

import httpx
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from hydrops_engine.topology import sample_at_step
from hydrops_engine.topology.geometry import Vertex, cumulative_pk

# Miroirs publics Overpass, essayes dans l'ordre (consigne utilisateur : le premier a deja renvoye
# un 504 Gateway Timeout sur une trace dense/longue) — meme principe de cascade que le DEM
# (services/dem.py), une seule source publique n'etant pas fiable a elle seule. osm.ch et
# maps.mail.ru ajoutes (constate en usage reel : "service indisponible" alors que overpass-api.de
# repond normalement la plupart du temps mais peut ponctuellement depasser OVERPASS_TIMEOUT_S sur
# une zone dense — building/landuse compris dans la requete — pendant que les deux autres miroirs
# historiques sont, eux, injoignables depuis certains reseaux) — plus de candidats independants
# augmente les chances qu'au moins un reponde a temps.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
OVERPASS_TIMEOUT_S = 40.0
# Delai de CONNEXION distinct, plus court que le delai global ci-dessus : un miroir injoignable
# (DNS/reseau bloque, serveur en panne) doit echouer vite pour passer au suivant, plutot que de
# faire attendre l'utilisateur ~40 s par miroir avant de conclure a l'echec (constate en usage
# reel : ~70 s cumules sur 3 miroirs avant l'erreur). Un miroir qui REPOND, lui, garde tout le
# temps du delai global pour traiter une requete lourde (trace dense/longue).
_CONNECT_TIMEOUT_S = 8.0
# Marge de securite : bien plus long que timeout HTTP client cote appelant (delai vecu par
# l'utilisateur, cf. hydrops_api.routers.traces), pour laisser Overpass repondre plutot que de
# couper la connexion trop tot depuis notre cote.
_QUERY_TIMEOUT_S = 30
# Overpass renvoie 406 Not Acceptable sans User-Agent explicite (regle anti-bot du serveur) —
# constate empiriquement, cf. httpx par defaut n'en envoie pas d'utilisable ici.
_REQUEST_HEADERS = {"User-Agent": "HydroPS/1.0 (hydraulic network design tool)", "Accept": "*/*"}

# Marge (degres) ajoutee autour de l'emprise (bounding box) de la trace avant interrogation
# Overpass — une traversee peut etre tres proche d'une extremite, une bbox exactement ajustee
# risquerait de la manquer si le tron de voie/cours d'eau depasse legerement.
BBOX_MARGIN_DEG = 0.01

# Pas d'echantillonnage (m) le long de la trace pour la detection de zones (urbain/foret, consigne
# utilisateur) — memes points que le profil altimetrique (DEFAULT_SAMPLE_STEP_M), pour rester
# coherent avec le reste de l'application plutot que d'introduire une autre granularite.
ZONE_SAMPLE_STEP_M = 20.0

CrossingKind = Literal["highway", "railway", "waterway", "building", "urban", "forest"]

# Repere court (routes/voies/batiments) : croisement PONCTUEL, detecte par intersection de lignes.
_POINT_KINDS: tuple[CrossingKind, ...] = ("highway", "railway", "waterway", "building")
# Zones (urbain/foret, consigne utilisateur) : la trace y ENTRE et en SORT — detecte par
# confinement (point-in-polygon) le long d'un echantillonnage regulier, pas par intersection de
# lignes (une zone est une SURFACE, pas un trait).
_ZONE_LABELS: dict[CrossingKind, str] = {"urban": "urbaine", "forest": "forestière"}

# Ordre de priorite si un element (rarement) porte plusieurs tags a la fois.
_LANDUSE_URBAN = {"residential", "commercial", "industrial", "retail", "construction"}


@dataclass(frozen=True)
class OsmFeature:
    kind: CrossingKind
    label: Optional[str]
    coordinates: list[tuple[float, float]]  # (lon, lat)
    # Valeur brute du tag OSM (ex. "primary", "river") — capturee independamment de `label`
    # (consigne utilisateur : palette de couleurs par sous-categorie, cf. shared/crossingColors.ts
    # cote frontend). `None` pour une zone (urbain/foret), pas de tag source unique.
    subtype: Optional[str] = None


@dataclass(frozen=True)
class Crossing:
    id: str
    kind: CrossingKind
    label: Optional[str]
    pk: float
    lon: float
    lat: float
    subtype: Optional[str] = None
    source: Literal["detected", "manual"] = "detected"


def _overpass_query(south: float, west: float, north: float, east: float) -> str:
    bbox = f"{south},{west},{north},{east}"
    return (
        f"[out:json][timeout:{_QUERY_TIMEOUT_S}];"
        f'(way["highway"]({bbox});way["railway"]({bbox});'
        f'way["waterway"]({bbox});way["building"]({bbox});'
        f'way["landuse"~"^(residential|commercial|industrial|retail|construction)$"]({bbox});'
        f'way["landuse"="forest"]({bbox});way["natural"="wood"]({bbox}););'
        "out geom;"
    )


def _kind_for_tags(tags: dict) -> Optional[CrossingKind]:
    if "railway" in tags:
        return "railway"
    if "waterway" in tags:
        return "waterway"
    if "building" in tags:
        return "building"
    landuse = tags.get("landuse")
    if landuse in _LANDUSE_URBAN:
        return "urban"
    if landuse == "forest" or tags.get("natural") == "wood":
        return "forest"
    if "highway" in tags:
        return "highway"
    return None


def _feature_from_element(element: dict) -> Optional[OsmFeature]:
    tags = element.get("tags") or {}
    geometry = element.get("geometry")
    if not geometry:
        return None
    kind = _kind_for_tags(tags)
    if kind is None:
        return None
    label = tags.get("name") or tags.get(kind) or tags.get("landuse") or tags.get("natural")
    # Valeur BRUTE du tag kind (ex. "primary", "river") — lue AVANT tout repli sur `name`, pour ne
    # jamais dependre de si l'element est nomme (consigne utilisateur : palette par sous-categorie).
    subtype = tags.get(kind)
    coordinates = [(pt["lon"], pt["lat"]) for pt in geometry if "lon" in pt and "lat" in pt]
    if len(coordinates) < 2:
        return None
    return OsmFeature(kind=kind, label=label, subtype=subtype, coordinates=coordinates)


async def fetch_osm_features(
    bbox: tuple[float, float, float, float], client: Optional[httpx.AsyncClient] = None
) -> list[OsmFeature]:
    """bbox = (south, west, north, east), en degres WGS84. Miroirs Overpass publics (OVERPASS_URLS)
    interroges EN PARALLELE, pas en cascade sequentielle (consigne utilisateur : "la détection des
    traversées ne marche toujours pas") — une cascade sequentielle pouvait attendre jusqu'a
    5×OVERPASS_TIMEOUT_S (200s) avant d'echouer si le PREMIER miroir tente est simplement
    injoignable depuis le reseau de l'utilisateur (firewall, miroir en panne...), ce qui ressemblait
    a un blocage pur et simple plutot qu'a une detection lente.

    Un miroir peut repondre 200 OK avec `elements: []` alors que la zone contient reellement des
    voies/bâtiments (constate en usage reel : overpass.osm.ch renvoie 0 element sur une requete ou
    maps.mail.ru en renvoie plusieurs milliers, pour la MEME bbox — pas une erreur HTTP, un miroir
    dont la replication est simplement incomplete pour cette zone) — accepter ce genre de reponse
    des qu'elle arrive ferait croire a tort "aucune traversee" a chaque fois qu'un tel miroir
    repond avant les autres. Un resultat NON VIDE est donc accepte immediatement (la reponse
    utile la plus rapide gagne, les autres requetes en vol sont annulees) ; un resultat VIDE est
    garde en reserve, sans conclure, tant qu'un miroir plus complet n'a pas eu sa chance de
    repondre — seulement retenu comme reponse finale si AUCUN miroir n'a produit mieux."""
    south, west, north, east = bbox
    query = _overpass_query(
        south - BBOX_MARGIN_DEG, west - BBOX_MARGIN_DEG, north + BBOX_MARGIN_DEG, east + BBOX_MARGIN_DEG
    )
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(OVERPASS_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S)
    )

    async def _query_mirror(url: str) -> dict:
        response = await client.post(url, data={"data": query}, headers=_REQUEST_HEADERS)
        response.raise_for_status()
        return response.json()

    payload = None
    empty_payload = None
    last_error: Optional[Exception] = None
    try:
        pending = {asyncio.ensure_future(_query_mirror(url)) for url in OVERPASS_URLS}
        while pending and payload is None:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    result = task.result()
                except (httpx.HTTPStatusError, httpx.TransportError) as e:
                    last_error = e
                    continue
                if result.get("elements"):
                    payload = result
                    break
                if empty_payload is None:
                    empty_payload = result
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if payload is None:
            payload = empty_payload
        if payload is None and last_error is not None:
            raise last_error
    finally:
        if owns_client:
            await client.aclose()
    features = [_feature_from_element(el) for el in (payload or {}).get("elements", [])]
    return [f for f in features if f is not None]


def trace_bbox(coordinates: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    lons = [c[0] for c in coordinates]
    lats = [c[1] for c in coordinates]
    return (min(lats), min(lons), max(lats), max(lons))


def _pk_at_point(vertices: list, lon: float, lat: float) -> float:
    """PK par projection sur le SEGMENT de trace le plus proche (approximation planaire locale sur
    lon/lat, largement suffisante a l'echelle d'un point de croisement) — plus precis qu'un simple
    "sommet le plus proche" (cf. `nearestPkForPoint` cote frontend, utilise pour le survol) des que
    les sommets de la trace sont espaces (KML importe avec peu de points intermediaires)."""
    best_pk = vertices[0].pk
    best_dist = math.inf
    for v1, v2 in zip(vertices, vertices[1:]):
        dx, dy = v2.lon - v1.lon, v2.lat - v1.lat
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq <= 0:
            t = 0.0
        else:
            t = ((lon - v1.lon) * dx + (lat - v1.lat) * dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
        proj_lon, proj_lat = v1.lon + t * dx, v1.lat + t * dy
        dist = (proj_lon - lon) ** 2 + (proj_lat - lat) ** 2
        if dist < best_dist:
            best_dist = dist
            best_pk = v1.pk + t * (v2.pk - v1.pk)
    return best_pk


def _zone_polygon(features_of_kind: list[OsmFeature]):
    """Union (shapely) de toutes les surfaces d'une meme nature (urbain/foret) — plusieurs
    polygones OSM voisins/qui se recouvrent doivent compter comme UNE seule zone continue, pas
    generer une entree/sortie a chaque limite de way individuelle. `None` si aucune surface valide
    (way non fermee/degeneree — silencieusement ignoree, coherent avec l'aspect indicatif de cette
    detection)."""
    polygons = []
    for f in features_of_kind:
        if len(f.coordinates) < 3:
            continue
        try:
            poly = Polygon(f.coordinates)
        except Exception:
            continue
        if poly.is_valid and not poly.is_empty:
            polygons.append(poly)
    if not polygons:
        return None
    return unary_union(polygons)


def _zone_crossing(kind: CrossingKind, verb: str, vertex: Vertex) -> Crossing:
    return Crossing(
        id=str(uuid.uuid4()), kind=kind, label=f"{verb} zone {_ZONE_LABELS[kind]}",
        pk=vertex.pk, lon=vertex.lon, lat=vertex.lat,
    )


def _compute_zone_crossings(trace_coordinates: list[tuple[float, float]], features: list[OsmFeature]) -> list[Crossing]:
    """Une zone (urbain/foret, consigne utilisateur) est une SURFACE, pas un trait — on echantillonne
    la trace regulierement (memes points que le profil altimetrique) et on teste, a chaque point, si
    elle est CONTENUE dans l'union des polygones de cette nature : chaque passage dehors -> dedans
    genere une "Entrée", chaque dedans -> dehors une "Sortie" (plusieurs zones separees le long de la
    meme trace donnent donc plusieurs paires). Sensible au pas d'echantillonnage (ZONE_SAMPLE_STEP_M)
    pour la position exacte de l'entree/sortie — indicatif, coherent avec le reste de la detection."""
    crossings: list[Crossing] = []
    samples = sample_at_step(trace_coordinates, ZONE_SAMPLE_STEP_M)
    for kind in _ZONE_LABELS:
        region = _zone_polygon([f for f in features if f.kind == kind])
        if region is None:
            continue
        prepared = prep(region)
        was_inside = False
        entry_vertex: Optional[Vertex] = None
        last_inside_vertex: Optional[Vertex] = None
        for v in samples:
            inside = prepared.contains(Point(v.lon, v.lat))
            if inside:
                if not was_inside:
                    entry_vertex = v
                last_inside_vertex = v
            elif was_inside and entry_vertex is not None and last_inside_vertex is not None:
                crossings.append(_zone_crossing(kind, "Entrée", entry_vertex))
                crossings.append(_zone_crossing(kind, "Sortie", last_inside_vertex))
                entry_vertex = None
            was_inside = inside
        if was_inside and entry_vertex is not None:
            # Encore dans la zone au tout dernier echantillon : la trace s'arrete la, on ne sait
            # pas si la zone continue au-dela — seule l'entree est rapportee, jamais de "Sortie"
            # fabriquee au dernier point (qui ne correspond a aucune vraie sortie observee).
            crossings.append(_zone_crossing(kind, "Entrée", entry_vertex))
    return crossings


def compute_crossings(trace_coordinates: list[tuple[float, float]], features: list[OsmFeature]) -> list[Crossing]:
    """Intersection geometrique (shapely) entre la trace et chaque element OSM PONCTUEL (route/voie
    ferree/cours d'eau/bâtiment — une ligne dans les trois premiers cas, et TOUJOURS une ligne,
    jamais un polygone, pour un bâtiment : le contour suffit a detecter une entree/sortie de son
    emprise sans les soucis de validite de polygone hors perimetre de cette detection indicative) —
    et confinement (point-in-polygon) pour les ZONES (urbain/foret, consigne utilisateur), qui sont
    des surfaces traversees plutot que des traits croises, cf. `_compute_zone_crossings`."""
    if len(trace_coordinates) < 2:
        return []
    trace_line = LineString(trace_coordinates)
    vertices = cumulative_pk(trace_coordinates)
    crossings: list[Crossing] = []
    for feature in features:
        if feature.kind not in _POINT_KINDS or len(feature.coordinates) < 2:
            continue
        feature_line = LineString(feature.coordinates)
        intersection = trace_line.intersection(feature_line)
        points: list[Point] = []
        if intersection.is_empty:
            continue
        if intersection.geom_type == "Point":
            points = [intersection]
        elif intersection.geom_type == "MultiPoint":
            points = list(intersection.geoms)
        elif intersection.geom_type in ("LineString", "MultiLineString", "GeometryCollection"):
            # Chevauchement (trace et voie quasi-paralleles) plutot qu'un croisement net — hors
            # perimetre MVP (pas de "traversee" ponctuelle a signaler), on l'ignore silencieusement.
            continue
        for point in points:
            pk = _pk_at_point(vertices, point.x, point.y)
            crossings.append(
                Crossing(
                    id=str(uuid.uuid4()),
                    kind=feature.kind,
                    label=feature.label,
                    subtype=feature.subtype,
                    pk=pk,
                    lon=point.x,
                    lat=point.y,
                )
            )
    crossings.extend(_compute_zone_crossings(trace_coordinates, features))
    crossings.sort(key=lambda c: c.pk)
    return crossings
