"""Tests unitaires de l'import KML/KMZ — V1-01 : 'un KML/KMZ valide cree une trace continue',
cdc §5.2 : 'chaque KML/KMZ correspond exactement a une trace continue'."""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

from hydrops_api.services.kml_import import (
    KmlImportError,
    extract_kml_bytes,
    parse_single_linestring,
)

SIMPLE_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <LineString><coordinates>2.35,48.85,0 2.36,48.86,0</coordinates></LineString>
    </Placemark>
  </Document>
</kml>"""


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def test_extract_kml_bytes_passthrough_for_plain_kml():
    assert extract_kml_bytes("trace.kml", SIMPLE_KML) == SIMPLE_KML


def test_extract_kml_bytes_finds_doc_kml_at_root():
    kmz = _zip_bytes({"doc.kml": SIMPLE_KML, "images/icon.png": b"\x89PNG"})
    assert extract_kml_bytes("trace.kmz", kmz) == SIMPLE_KML


def test_extract_kml_bytes_finds_doc_kml_in_subfolder():
    # Google Earth/QGIS exportent parfois vers un sous-dossier plutot que la racine du ZIP.
    kmz = _zip_bytes({"files/doc.kml": SIMPLE_KML})
    assert extract_kml_bytes("trace.kmz", kmz) == SIMPLE_KML


def test_extract_kml_bytes_ignores_macosx_junk_entries():
    other_kml = b"<kml><Document>autre</Document></kml>"
    kmz = _zip_bytes({"__MACOSX/._doc.kml": other_kml, "doc.kml": SIMPLE_KML})
    assert extract_kml_bytes("trace.kmz", kmz) == SIMPLE_KML


def test_extract_kml_bytes_falls_back_to_first_kml_alphabetically():
    kmz = _zip_bytes({"b_trace.kml": b"B", "a_trace.kml": b"A"})
    assert extract_kml_bytes("trace.kmz", kmz) == b"A"


def test_extract_kml_bytes_rejects_kmz_without_kml():
    kmz = _zip_bytes({"readme.txt": b"pas de kml ici"})
    with pytest.raises(KmlImportError, match="aucun fichier .kml"):
        extract_kml_bytes("trace.kmz", kmz)


def test_extract_kml_bytes_rejects_corrupted_zip():
    with pytest.raises(KmlImportError, match="pas un ZIP"):
        extract_kml_bytes("trace.kmz", b"not a zip file")


def test_parse_single_linestring_extracts_coordinates():
    coords = parse_single_linestring(SIMPLE_KML)
    assert coords == [(2.35, 48.85), (2.36, 48.86)]


def test_parse_single_linestring_rejects_no_linestring():
    kml = b"<kml><Document><Placemark><Point><coordinates>2.35,48.85</coordinates></Point></Placemark></Document></kml>"
    with pytest.raises(KmlImportError, match="Aucune LineString"):
        parse_single_linestring(kml)


def test_parse_single_linestring_rejects_multiple_linestrings():
    kml = b"""<kml><Document>
      <Placemark><LineString><coordinates>0,0 1,1</coordinates></LineString></Placemark>
      <Placemark><LineString><coordinates>1,1 2,2</coordinates></LineString></Placemark>
    </Document></kml>"""
    with pytest.raises(KmlImportError, match="2 LineString"):
        parse_single_linestring(kml)


def test_parse_single_linestring_accepts_linestring_wrapped_in_multigeometry():
    # Une trace unique exportee sous forme de MultiGeometry ne doit pas etre rejetee : on
    # cherche la LineString a n'importe quelle profondeur, pas seulement sous Placemark direct.
    kml = b"""<kml><Document><Placemark><MultiGeometry>
      <LineString><coordinates>0,0 1,1 2,2</coordinates></LineString>
    </MultiGeometry></Placemark></Document></kml>"""
    coords = parse_single_linestring(kml)
    assert coords == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]


def test_parse_single_linestring_rejects_invalid_xml():
    with pytest.raises(KmlImportError, match="XML KML invalide"):
        parse_single_linestring(b"<not-valid-xml")


def test_parse_single_linestring_rejects_empty_coordinates():
    kml = b"<kml><Document><Placemark><LineString><coordinates></coordinates></LineString></Placemark></Document></kml>"
    with pytest.raises(KmlImportError, match="sans coordonnees"):
        parse_single_linestring(kml)


def test_parse_single_linestring_rejects_single_point_trace():
    kml = b"<kml><Document><Placemark><LineString><coordinates>2.35,48.85,0</coordinates></LineString></Placemark></Document></kml>"
    with pytest.raises(KmlImportError, match="au moins 2 points"):
        parse_single_linestring(kml)


def test_parse_single_linestring_ignores_namespace_prefix():
    kml = (
        b'<kml:kml xmlns:kml="http://www.opengis.net/kml/2.2">'
        b"<kml:Document><kml:Placemark><kml:LineString>"
        b"<kml:coordinates>0,0 1,1</kml:coordinates>"
        b"</kml:LineString></kml:Placemark></kml:Document></kml:kml>"
    )
    assert parse_single_linestring(kml) == [(0.0, 0.0), (1.0, 1.0)]
