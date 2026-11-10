# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Определение базовых путей
SPECPATH = Path(SPECPATH).resolve()
SRC_PATH = SPECPATH / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Настройка путей для поиска native GIS DLLs
candidate_dll_dirs = [
    Path(r"C:\Program Files\QGIS 3.44.14\bin"),
    Path(r"C:\Program Files\QGIS 3.34\bin"),
    Path(sys.prefix) / "bin",
    Path(sys.prefix) / "Library" / "bin",
]
pathex = [str(SRC_PATH)]
for d in candidate_dll_dirs:
    if d.is_dir():
        pathex.append(str(d))
        if str(d) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")

# Сбор обязательных данных PROJ и GDAL
datas = []
binaries = []

# 1. PROJ данные (proj.db)
proj_candidates = [
    os.environ.get("PROJ_DATA"),
    os.environ.get("PROJ_LIB"),
    r"C:\Program Files\QGIS 3.44.14\share\proj",
    r"C:\Program Files\QGIS 3.34\share\proj",
    str(Path(sys.prefix) / "share" / "proj"),
]
proj_found = False
for pc in proj_candidates:
    if pc and Path(pc).is_dir() and (Path(pc) / "proj.db").exists():
        datas.append((str(pc), "share/proj"))
        datas.append((str(pc), "proj"))
        proj_found = True
        break

# 2. GDAL данные (header.dxf, csvs)
gdal_candidates = [
    os.environ.get("GDAL_DATA"),
    r"C:\Program Files\QGIS 3.44.14\apps\gdal\share\gdal",
    r"C:\Program Files\QGIS 3.34\apps\gdal\share\gdal",
    str(Path(sys.prefix) / "share" / "gdal"),
]
gdal_found = False
for gc in gdal_candidates:
    if gc and Path(gc).is_dir() and (Path(gc) / "header.dxf").exists():
        datas.append((str(gc), "share/gdal"))
        datas.append((str(gc), "gdal"))
        gdal_found = True
        break

# 3. Сертификаты certifi
try:
    import certifi
    ca_file = certifi.where()
    if os.path.exists(ca_file):
        datas.append((ca_file, "certifi"))
except Exception:
    pass

# 4. Ресурсы приложения (иконки, стили)
res_dir = SRC_PATH / "rme_mapper" / "resources"
if res_dir.is_dir():
    datas.append((str(res_dir), "rme_mapper/resources"))

# 5. Данные библиотек через PyInstaller hooks
datas += collect_data_files("rasterio")
datas += collect_data_files("pyogrio")
datas += collect_data_files("pyproj")
datas += collect_data_files("geopandas")
datas += collect_data_files("shapely")

# Hidden imports
hiddenimports = [
    "rme_mapper",
    "rme_mapper.app_info",
    "rme_mapper.main",
    "rme_mapper.backends",
    "rme_mapper.backends.factory",
    "rme_mapper.backends.geopackage",
    "rme_mapper.backends.geotiff",
    "rme_mapper.backends.online_xyz",
    "rme_mapper.models",
    "rme_mapper.services",
    "rme_mapper.ui",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
    "pyproj",
    "pyproj.datadir",
    "geopandas",
    "shapely",
    "shapely.geometry",
    "pandas",
    "openpyxl",
    "numpy",
    "pyogrio",
    "rasterio",
    "rasterio.sample",
    "rasterio._features",
    "rasterio._shim",
    "affine",
    "certifi",
]
hiddenimports += collect_submodules("rme_mapper")
hiddenimports += collect_submodules("rasterio")
hiddenimports += collect_submodules("pyogrio")

icon_ico = str(SRC_PATH / "rme_mapper" / "resources" / "icon.ico")
version_file = str(SPECPATH / "packaging" / "file_version_info.txt")

a = Analysis(
    [str(SRC_PATH / "rme_mapper" / "main.py")],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "tkinter",
        "matplotlib",
        "IPython",
        "scipy.optimize",
        "pytest",
        "_pytest",
        "geopandas.tests",
        "pyogrio.tests",
        "pyarrow.tests",
        "pandas.tests",
        "numpy.tests",
    ],
    noarchive=False,
    optimize=0,
)

# Qt uses the Windows system ICU API (unversioned exports). A third-party
# icuuc.dll found on the build machine's PATH (e.g. Poppler) can shadow it
# and cause "DLL load failed while importing QtWidgets" on startup.
if sys.platform == "win32":
    a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() != "icuuc.dll"]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GeoPointMapper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_ico if os.path.exists(icon_ico) else None,
    version=version_file if os.path.exists(version_file) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GeoPointMapper",
)
