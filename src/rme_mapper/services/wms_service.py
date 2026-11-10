"""WMS 1.1.1 GetMap templates on the EPSG:3857 XYZ grid."""
from __future__ import annotations
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode


def build_wms_template(endpoint,layers):
    parts=urlsplit(endpoint.strip())
    if parts.scheme not in ("http","https") or not parts.netloc or not layers.strip():
        raise ValueError("WMS requires an HTTP(S) URL and layer names")
    parameters={k:v for k,v in parse_qsl(parts.query) if k.upper() not in {"SERVICE","VERSION","REQUEST","LAYERS","STYLES","SRS","CRS","BBOX","WIDTH","HEIGHT","FORMAT","TRANSPARENT"}}
    parameters.update(SERVICE="WMS",VERSION="1.1.1",REQUEST="GetMap",LAYERS=layers.strip(),STYLES="",SRS="EPSG:3857",BBOX="{bbox}",WIDTH="256",HEIGHT="256",FORMAT="image/png",TRANSPARENT="TRUE")
    return urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(parameters,safe="{}"),""))
