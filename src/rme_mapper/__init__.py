"""GeoPoint Mapper: Универсальное настольное приложение для нанесения географических координат и зон на карты."""
from __future__ import annotations


import os
from pathlib import Path

from rme_mapper.app_info import APP_VERSION

__version__ = APP_VERSION

def _setup_gis_environment() -> None:
    """Настройка путей к базам данных PROJ и GDAL при их отсутствии в окружении."""
    import sys
    app_dir = Path(__file__).resolve().parent
    exe_dir = Path(sys.executable).resolve().parent

    # Потенциальные пути к PROJ: сначала собственный deployment/bundle, затем системные
    proj_candidates = [
        exe_dir / "share" / "proj",
        exe_dir / "proj",
        app_dir / "share" / "proj",
        Path(sys.prefix) / "share" / "proj",
        Path(r"C:\Program Files\QGIS 3.44.14\share\proj"),
        Path(r"C:\Program Files\QGIS 3.34\share\proj"),
    ]
    if "PROJ_DATA" not in os.environ and "PROJ_LIB" not in os.environ:
        for candidate in proj_candidates:
            if candidate.is_dir() and (candidate / "proj.db").exists():
                os.environ["PROJ_DATA"] = str(candidate)
                break

    # Потенциальные пути к GDAL: сначала собственный deployment/bundle, затем системные
    gdal_candidates = [
        exe_dir / "share" / "gdal",
        exe_dir / "gdal",
        app_dir / "share" / "gdal",
        Path(sys.prefix) / "share" / "gdal",
        Path(r"C:\Program Files\QGIS 3.44.14\apps\gdal\share\gdal"),
        Path(r"C:\Program Files\QGIS 3.34\apps\gdal\share\gdal"),
    ]
    if "GDAL_DATA" not in os.environ:
        for candidate in gdal_candidates:
            if candidate.is_dir() and (candidate / "header.dxf").exists():
                os.environ["GDAL_DATA"] = str(candidate)
                break

_setup_gis_environment()

