"""GeoPoint Mapper: Универсальное настольное приложение для нанесения географических координат и зон на карты."""
from __future__ import annotations


import os
from pathlib import Path

from rme_mapper.app_info import APP_VERSION

__version__ = APP_VERSION

def _setup_gis_environment() -> None:
    """Настройка путей к базам данных PROJ и GDAL при их отсутствии в окружении.

    Политика изоляции (BUG-007):
    - В упакованном приложении (sys.frozen == True) используются ТОЛЬКО bundled пути.
      Системный QGIS категорически исключен как fallback во избежание маскировки дефектов упаковки.
    - В development-режиме (sys.frozen == False) допускаются системные пути и QGIS fallback.
    """
    import sys
    app_dir = Path(__file__).resolve().parent
    exe_dir = Path(sys.executable).resolve().parent
    meipass = getattr(sys, "_MEIPASS", None)
    bundle_dirs = [Path(meipass)] if meipass else []
    is_frozen = bool(getattr(sys, "frozen", False))

    # Пути к PROJ: в frozen-режиме строго bundled, в dev-режиме с системными fallback
    proj_candidates = [
        *(d / "share" / "proj" for d in bundle_dirs),
        *(d / "proj" for d in bundle_dirs),
        *bundle_dirs,
        exe_dir / "_internal" / "share" / "proj",
        exe_dir / "_internal" / "proj",
        exe_dir / "share" / "proj",
        exe_dir / "proj",
    ]
    if not is_frozen:
        proj_candidates.extend([
            app_dir / "share" / "proj",
            app_dir / "proj",
            Path(sys.prefix) / "share" / "proj",
            Path(r"C:\Program Files\QGIS 3.44.14\share\proj"),
            Path(r"C:\Program Files\QGIS 3.34\share\proj"),
        ])

    if "PROJ_DATA" not in os.environ and "PROJ_LIB" not in os.environ:
        for candidate in proj_candidates:
            if candidate.is_dir() and (candidate / "proj.db").exists():
                os.environ["PROJ_DATA"] = str(candidate)
                os.environ["PROJ_LIB"] = str(candidate)
                try:
                    import pyproj.datadir
                    pyproj.datadir.set_data_dir(str(candidate))
                except Exception:
                    pass
                break

    # Python GIS bindings pass UTF-8 paths to GDAL, including its bundled data.
    # NO makes GDAL interpret these as ANSI and breaks installs in Cyrillic paths.
    if sys.platform == "win32" and "GDAL_FILENAME_IS_UTF8" not in os.environ:
        os.environ["GDAL_FILENAME_IS_UTF8"] = "YES"

    # Пути к GDAL: в frozen-режиме строго bundled, в dev-режиме с системными fallback
    gdal_candidates = [
        *(d / "share" / "gdal" for d in bundle_dirs),
        *(d / "gdal" for d in bundle_dirs),
        *bundle_dirs,
        exe_dir / "_internal" / "share" / "gdal",
        exe_dir / "_internal" / "gdal",
        exe_dir / "share" / "gdal",
        exe_dir / "gdal",
    ]
    if not is_frozen:
        gdal_candidates.extend([
            app_dir / "share" / "gdal",
            app_dir / "gdal",
            Path(sys.prefix) / "share" / "gdal",
            Path(r"C:\Program Files\QGIS 3.44.14\apps\gdal\share\gdal"),
            Path(r"C:\Program Files\QGIS 3.34\apps\gdal\share\gdal"),
        ])

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
        ]
        if not is_frozen:
            dll_candidates.extend([
                Path(sys.prefix) / "bin",
                Path(r"C:\Program Files\QGIS 3.44.14\bin"),
                Path(r"C:\Program Files\QGIS 3.34\bin"),
            ])

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

