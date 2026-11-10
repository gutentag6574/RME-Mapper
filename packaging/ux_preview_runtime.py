"""Keep the optional UX preview profile separate from the stable application."""
import os
from pathlib import Path

profile = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GeoPointMapperUXPreview"
os.environ.setdefault("RME_MAPPER_SETTINGS_DIR", str(profile / "settings"))
os.environ.setdefault("RME_MAPPER_CACHE_DIR", str(profile / "cache"))
