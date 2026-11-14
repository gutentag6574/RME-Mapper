"""Bounded GPX/KML/KMZ import of points and persistent tracks in WGS84."""
from __future__ import annotations
from pathlib import Path
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from rme_mapper.models.map_point import MapPoint

MAX_XML_BYTES=32*1024*1024
MAX_COORDINATES=100000


def read_field_file(path):
    path=Path(path)
    if path.stat().st_size>MAX_XML_BYTES:
        raise ValueError("GPX/KML/KMZ exceeds 32 MB")
    if path.suffix.lower()==".kmz":
        with zipfile.ZipFile(path) as archive:
            entries=[entry for entry in archive.infolist() if entry.filename.lower().endswith('.kml')]
            if len(entries)!=1 or entries[0].file_size>MAX_XML_BYTES:
                raise ValueError("KMZ must contain one KML document up to 32 MB")
            raw=archive.read(entries[0])
    else:
        raw=path.read_bytes()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper() or b'\x00' in raw:
        raise ValueError("Unsupported XML declarations or encoding")
    root=ET.fromstring(raw)
    for node in root.iter():
        node.tag=node.tag.split('}')[-1]
    points,annotations=[],[]
    count=0
    def coordinate(lon,lat):
        nonlocal count
        lon,lat=float(lon),float(lat)
        count+=1
        if count>MAX_COORDINATES or not math.isfinite(lon) or not math.isfinite(lat) or not(-180<=lon<=180 and -90<=lat<=90):
            raise ValueError("Invalid or too many field coordinates")
        return [lon,lat]
    def _parse_kml_tuples(text):
        normalized = re.sub(r"\s*,\s*", ",", (text or "").strip())
        if not normalized:
            return []
        tuples = []
        for token in normalized.split():
            parts = token.split(",")
            if len(parts) < 2:
                raise ValueError("Invalid KML coordinate tuple")
            tuples.append(parts[:2])
        return tuples

    if root.tag=='gpx':
        for node in root.findall('wpt'):
            raw_lon = node.attrib.get('lon')
            raw_lat = node.attrib.get('lat')
            if raw_lon is None or raw_lat is None:
                raise ValueError("GPX waypoint missing lat/lon attributes")
            lon,lat=coordinate(raw_lon,raw_lat)
            points.append(MapPoint(node.findtext('name') or str(len(points)+1),lat,lon))
        for node in root.findall('trk')+root.findall('rte'):
            segments=node.findall('trkseg') if node.tag=='trk' else [node]
            for segment in segments:
                coords=[]
                for p in segment:
                    if p.tag in ('trkpt','rtept'):
                        raw_lon = p.attrib.get('lon')
                        raw_lat = p.attrib.get('lat')
                        if raw_lon is None or raw_lat is None:
                            raise ValueError("GPX track/route point missing lat/lon attributes")
                        coords.append(coordinate(raw_lon,raw_lat))
                if len(coords)>=2:
                    annotations.append(dict(kind='line',coordinates=coords,name=node.findtext('name') or path.stem))
    elif root.tag=='kml':
        for feature in root.iter('Placemark'):
            raw_name=feature.findtext('name')
            for node in feature.iter('Point'):
                vals_list=_parse_kml_tuples(node.findtext('coordinates'))
                if vals_list:
                    lon,lat=coordinate(*vals_list[0])
                    points.append(MapPoint(raw_name or str(len(points)+1),lat,lon))
            for kind in ('LineString','Polygon'):
                for node in feature.iter(kind):
                    text=node.findtext('coordinates') if kind=='LineString' else node.findtext('outerBoundaryIs/LinearRing/coordinates')
                    coords=[coordinate(*vals) for vals in _parse_kml_tuples(text)]
                    if kind=='Polygon' and node.find('innerBoundaryIs') is not None:
                        raise ValueError("KML polygon holes are not supported")
                    if len(coords)>=(3 if kind=='Polygon' else 2):
                        annotations.append(dict(kind='polygon' if kind=='Polygon' else 'line',coordinates=coords,name=raw_name or str(len(annotations)+1)))
    else:
        raise ValueError("Expected GPX or KML document")
    return points,annotations
