"""GeoPoint Mapper: Универсальное настольное приложение для нанесения географических координат и зон на карты."""

import os
from pathlib import Path

__version__ = "0.1.0"

def _setup_gis_environment() -> None:
    """Настройка путей к базам данных PROJ и GDAL при их отсутствии в окружении."""
    # Потенциальные пути к PROJ в типичных установках QGIS
    proj_candidates = [
        Path(r"C:\Program Files\QGIS 3.44.14\share\proj"),
        Path(r"C:\Program Files\QGIS 3.34\share\proj"),
    ]
    if "PROJ_DATA" not in os.environ and "PROJ_LIB" not in os.environ:
        for candidate in proj_candidates:
            if candidate.is_dir() and (candidate / "proj.db").exists():
                os.environ["PROJ_DATA"] = str(candidate)
                break

    # Потенциальные пути к GDAL
    gdal_candidates = [
        Path(r"C:\Program Files\QGIS 3.44.14\apps\gdal\share\gdal"),
        Path(r"C:\Program Files\QGIS 3.34\apps\gdal\share\gdal"),
    ]
    if "GDAL_DATA" not in os.environ:
        for candidate in gdal_candidates:
            if candidate.is_dir() and (candidate / "header.dxf").exists():
                os.environ["GDAL_DATA"] = str(candidate)
                break

_setup_gis_environment()
