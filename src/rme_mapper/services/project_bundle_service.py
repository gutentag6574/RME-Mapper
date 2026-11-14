"""Create a self-contained ZIP without modifying the current project or map."""
from __future__ import annotations
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import zipfile

from rme_mapper.maps.map_config import get_project_root
from rme_mapper.models.project_data import ProjectData
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.georeference_service import WORLD_FILE_EXTENSIONS

_RASTER_SIDECAR_EXTENSIONS = WORLD_FILE_EXTENSIONS | {".prj", ".aux.xml", ".ovr"}


def _resolve_source_path(raw_path: Path | str, candidate_dirs: list[Path]) -> Path:
    """Разрешение пути исходного файла относительно каталога проекта и резервных директорий."""
    p = Path(raw_path)
    if p.is_absolute():
        return p.resolve()
    for base in candidate_dirs:
        candidate = (base / p).resolve()
        if candidate.exists():
            return candidate
    if candidate_dirs:
        return (candidate_dirs[0] / p).resolve()
    return p.resolve()


def _collect_raster_sidecars(source: Path) -> list[Path]:
    """Сбор всех сопутствующих файлов геопривязки (world-файлы, .prj, .aux.xml, .ovr) рядом с растром."""
    sidecars: list[Path] = []
    if not source.parent.is_dir():
        return sidecars
    for sibling in sorted(source.parent.iterdir()):
        if sibling == source or not sibling.is_file():
            continue
        if any(
            sibling.name.casefold() in ((source.stem + ext).casefold(), (source.name + ext).casefold())
            for ext in _RASTER_SIDECAR_EXTENSIONS
        ):
            sidecars.append(sibling)
    return sidecars


def create_project_bundle(
    project: ProjectData,
    target: Path,
    map_path: Path | str | None = None,
    base_dir: Path | str | None = None,
) -> Path:
    target = Path(target).resolve()
    candidate_dirs: list[Path] = []
    if base_dir is not None:
        candidate_dirs.append(Path(base_dir).resolve())
    if map_path is not None:
        mp = Path(map_path)
        if mp.is_absolute():
            candidate_dirs.append(mp.resolve().parent)
    if target.parent not in candidate_dirs:
        candidate_dirs.append(target.parent)
    root_dir = get_project_root().resolve()
    if root_dir not in candidate_dirs:
        candidate_dirs.append(root_dir)

    result = deepcopy(project)
    files: list[tuple[Path, str]] = []
    used_arcnames: set[str] = {"project.gpmap"}

    if result.map.source_type != "online_xyz" and (map_path or result.map.relative_path):
        source = _resolve_source_path(map_path if map_path is not None else result.map.relative_path, candidate_dirs)
        if not source.is_file():
            raise FileNotFoundError(f"Map file not found: {source}")
        if source == target:
            raise ValueError("Archive must not overwrite the map")
        if source.parent not in candidate_dirs:
            candidate_dirs.insert(1 if base_dir is not None else 0, source.parent)

        map_arcname = f"maps/{source.name}"
        if map_arcname.casefold() in used_arcnames:
            map_arcname = f"maps/base_{source.name}"
        used_arcnames.add(map_arcname.casefold())
        files.append((source, map_arcname))

        for sibling in _collect_raster_sidecars(source):
            sidecar_arc = f"maps/{sibling.name}"
            if sidecar_arc.casefold() in used_arcnames:
                continue
            used_arcnames.add(sidecar_arc.casefold())
            files.append((sibling, sidecar_arc))

        result.map.relative_path = map_arcname

    target.parent.mkdir(parents=True, exist_ok=True)
    overlay_files: list[tuple[Path, str]] = []
    for index, overlay in enumerate(result.map.raster_overlays):
        source = _resolve_source_path(overlay["path"], candidate_dirs)
        if not source.is_file():
            raise FileNotFoundError(f"Overlay not found: {source}")
        if source == target:
            raise ValueError("Archive must not overwrite an overlay")
        archive_name = f"overlays/{index}/{source.name}"
        used_arcnames.add(archive_name.casefold())
        overlay_files.append((source, archive_name))
        for sibling in _collect_raster_sidecars(source):
            sidecar_arc = f"overlays/{index}/{sibling.name}"
            if sidecar_arc.casefold() in used_arcnames:
                continue
            used_arcnames.add(sidecar_arc.casefold())
            overlay_files.append((sibling, sidecar_arc))
        overlay["path"] = archive_name

    # Stage next to the output, then atomically replace it only after success.
    with tempfile.TemporaryDirectory(prefix="gp-bundle-", dir=target.parent) as folder:
        staged = Path(folder)
        ProjectService().save_project(result, staged / "project.gpmap")
        archive = staged / "bundle.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            output.write(staged / "project.gpmap", "project.gpmap")
            for source, arcname in files:
                output.write(source, arcname)
            for source, name in overlay_files:
                output.write(source, name)
        os.replace(archive, target)
    return target
