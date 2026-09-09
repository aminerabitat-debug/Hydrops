"""Import KML/KMZ — cdc §5.2/§6, V1-01 : 'un KML/KMZ valide cree une trace continue'.

Parsing en stdlib pur (xml.etree + zipfile), sans dependance tierce (fastkml/pykml) pour ce
premier lot : le besoin est etroit (une seule LineString par fichier) et le stdlib suffit sans
ajouter une dependance dont on ne connait pas encore la robustesse sur des KML exportes par des
outils SIG varies (Google Earth, QGIS...). A reconsiderer si des cas reels exposent des besoins
KML plus larges (styles, placemarks multiples a filtrer, etc.).
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET


class KmlImportError(ValueError):
    pass


def extract_kml_bytes(filename: str, content: bytes) -> bytes:
    """Si `filename` est un .kmz, en extrait le .kml interne (convention doc.kml, y compris dans
    un sous-dossier — Google Earth/QGIS exportent parfois vers 'files/doc.kml' ou similaire —
    sinon le premier .kml trouve par ordre alphabetique pour un choix deterministe). Ignore les
    entrees macOS '__MACOSX/' parfois presentes dans les KMZ. Sinon retourne `content` tel quel
    (deja un .kml)."""
    if filename.lower().endswith(".kmz"):
        try:
            with zipfile.ZipFile(BytesIO(content)) as zf:
                kml_names = sorted(
                    n
                    for n in zf.namelist()
                    if n.lower().endswith(".kml") and not n.startswith("__MACOSX/")
                )
                if not kml_names:
                    raise KmlImportError("Le KMZ ne contient aucun fichier .kml")
                preferred = [n for n in kml_names if n.lower().rsplit("/", 1)[-1] == "doc.kml"]
                name = preferred[0] if preferred else kml_names[0]
                return zf.read(name)
        except zipfile.BadZipFile as e:
            raise KmlImportError(f"Fichier KMZ invalide (pas un ZIP): {e}") from e
    return content


def parse_single_linestring(kml_bytes: bytes) -> list[tuple[float, float]]:
    """Extrait la geometrie d'une trace continue. Leve KmlImportError si 0 ou plusieurs
    LineString sont trouvees : 'une trace = une ligne continue' (V1-01), les branches doivent
    etre importees comme des traces separees (cdc §5.2), jamais fusionnees silencieusement."""
    try:
        root = ET.fromstring(kml_bytes)
    except ET.ParseError as e:
        raise KmlImportError(f"XML KML invalide: {e}") from e

    linestrings = _findall_local_name(root, "LineString")
    if len(linestrings) == 0:
        raise KmlImportError("Aucune LineString trouvee dans le KML (une trace = une ligne continue)")
    if len(linestrings) > 1:
        raise KmlImportError(
            f"{len(linestrings)} LineString trouvees dans ce KML : un fichier doit contenir "
            "exactement une trace continue (importer les branches separement, cf. cdc §5.2)"
        )

    coords_elements = _findall_local_name(linestrings[0], "coordinates")
    if not coords_elements or not coords_elements[0].text:
        raise KmlImportError("LineString sans coordonnees")

    coordinates = _parse_coordinates_text(coords_elements[0].text)
    if len(coordinates) < 2:
        raise KmlImportError("La trace doit contenir au moins 2 points")
    return coordinates


def _findall_local_name(element: ET.Element, local_name: str) -> list[ET.Element]:
    # Les KML exportes varient dans leur usage des namespaces/prefixes ; on matche sur le nom
    # local de la balise plutot que d'exiger un namespace exact.
    return [el for el in element.iter() if _local_name(el.tag) == local_name]


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _parse_coordinates_text(text: str) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []
    for token in text.strip().split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        lon, lat = float(parts[0]), float(parts[1])
        coordinates.append((lon, lat))
    return coordinates
