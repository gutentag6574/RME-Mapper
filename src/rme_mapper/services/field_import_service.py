"""Bounded GPX/KML/KMZ import of points and persistent tracks in WGS84."""
from __future__ import annotations
from pathlib import Path
import math
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
    if root.tag=='gpx':
        for node in root.findall('wpt'):
            lon,lat=coordinate(node.attrib['lon'],node.attrib['lat'])
            points.append(MapPoint(node.findtext('name') or str(len(points)+1),lat,lon))
        for node in root.findall('trk')+root.findall('rte'):
            segments=node.findall('trkseg') if node.tag=='trk' else [node]
            for segment in segments:
                coords=[coordinate(p.attrib['lon'],p.attrib['lat']) for p in segment if p.tag in ('trkpt','rtept')]
                if len(coords)>=2:
                    annotations.append(dict(kind='line',coordinates=coords,name=node.findtext('name') or path.stem))
    elif root.tag=='kml':
        for feature in root.iter('Placemark'):
            name=feature.findtext('name') or str(len(points)+1)
            for node in feature.iter('Point'):
                text=node.findtext('coordinates') or ''
                vals=text.strip().split()[0].split(',') if text.strip() else []
                if len(vals)>=2:
                    lon,lat=coordinate(*vals[:2])
                    points.append(MapPoint(name,lat,lon))
            for kind in ('LineString','Polygon'):
                for node in feature.iter(kind):
                    text=node.findtext('coordinates') if kind=='LineString' else node.findtext('outerBoundaryIs/LinearRing/coordinates')
                    coords=[coordinate(*token.split(',')[:2]) for token in (text or '').split()]
                    if kind=='Polygon' and node.find('innerBoundaryIs') is not None:
                        raise ValueError("KML polygon holes are not supported")
                    if len(coords)>=(3 if kind=='Polygon' else 2):
                        annotations.append(dict(kind='polygon' if kind=='Polygon' else 'line',coordinates=coords,name=name))
    else:
        raise ValueError("Expected GPX or KML document")
    return points,annotations
