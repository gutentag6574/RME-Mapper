"""Create a self-contained ZIP without modifying the current project or map."""
from __future__ import annotations
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import zipfile

from rme_mapper.models.project_data import ProjectData
from rme_mapper.services.project_service import ProjectService
from rme_mapper.services.georeference_service import WORLD_FILE_EXTENSIONS


def create_project_bundle(project: ProjectData, target: Path, map_path: Path | None = None) -> Path:
    target = Path(target).resolve()
    result = deepcopy(project)
    files = []
    if result.map.source_type != "online_xyz" and result.map.relative_path:
        source = Path(map_path or result.map.relative_path).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Map file not found: {source}")
        if source == target:
            raise ValueError("Archive must not overwrite the map")
        files.append(source)
        sidecars = WORLD_FILE_EXTENSIONS | {".prj", ".aux.xml", ".ovr"}
        for sibling in source.parent.iterdir():
            if sibling == source or not sibling.is_file():
                continue
            if any(sibling.name.casefold() in ((source.stem + ext).casefold(), (source.name + ext).casefold()) for ext in sidecars):
                files.append(sibling)
        result.map.relative_path = "maps/" + source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    overlay_files = []
    for index, overlay in enumerate(result.map.raster_overlays):
        source = Path(overlay["path"]).resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Overlay not found: {source}")
        if source == target:
            raise ValueError("Archive must not overwrite an overlay")
        archive_name = f"overlays/{index}/{source.name}"
        overlay_files.append((source, archive_name))
        overlay["path"] = archive_name
    # Stage next to the output, then atomically replace it only after success.
    with tempfile.TemporaryDirectory(prefix="gp-bundle-", dir=target.parent) as folder:
        staged = Path(folder)
        ProjectService().save_project(result, staged / "project.gpmap")
        archive = staged / "bundle.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            output.write(staged / "project.gpmap", "project.gpmap")
            for source in files:
                output.write(source, "maps/" + source.name)
            for source, name in overlay_files:
                output.write(source, name)
        os.replace(archive, target)
    return target
