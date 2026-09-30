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
    meipass = getattr(sys, "_MEIPASS", None)
    bundle_dirs = [Path(meipass)] if meipass else []

    # Потенциальные пути к PROJ: сначала собственный deployment/bundle, затем системные
    proj_candidates = [
        *(d / "share" / "proj" for d in bundle_dirs),
        *(d / "proj" for d in bundle_dirs),
        *bundle_dirs,
        exe_dir / "_internal" / "share" / "proj",
        exe_dir / "_internal" / "proj",
        exe_dir / "share" / "proj",
        exe_dir / "proj",
        app_dir / "share" / "proj",
        app_dir / "proj",
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
        *(d / "share" / "gdal" for d in bundle_dirs),
        *(d / "gdal" for d in bundle_dirs),
        *bundle_dirs,
        exe_dir / "_internal" / "share" / "gdal",
        exe_dir / "_internal" / "gdal",
        exe_dir / "share" / "gdal",
        exe_dir / "gdal",
        app_dir / "share" / "gdal",
        app_dir / "gdal",
        Path(sys.prefix) / "share" / "gdal",
        Path(r"C:\Program Files\QGIS 3.44.14\apps\gdal\share\gdal"),
        Path(r"C:\Program Files\QGIS 3.34\apps\gdal\share\gdal"),
    ]
    if "GDAL_DATA" not in os.environ:
        for candidate in gdal_candidates:
            if candidate.is_dir() and (candidate / "header.dxf").exists():
                os.environ["GDAL_DATA"] = str(candidate)
                break

    # Регистрация каталогов поиска native DLL (Python >= 3.8 на Windows)
    if hasattr(os, "add_dll_directory"):
        dll_candidates = [
            *(d / "bin" for d in bundle_dirs),
            *bundle_dirs,
            exe_dir / "_internal",
            exe_dir,
            Path(sys.prefix) / "bin",
            Path(r"C:\Program Files\QGIS 3.44.14\bin"),
            Path(r"C:\Program Files\QGIS 3.34\bin"),
        ]
        for dc in dll_candidates:
            if dc.is_dir():
                try:
                    os.add_dll_directory(str(dc))
                except Exception:
                    pass

    # Настройка SSL-сертификатов для безопасной работы с HTTPS в автономном рантайме
    if "SSL_CERT_FILE" not in os.environ:
        try:
            import certifi
            ca_file = certifi.where()
            if os.path.exists(ca_file):
                os.environ["SSL_CERT_FILE"] = ca_file
        except Exception:
            pass

_setup_gis_environment()

