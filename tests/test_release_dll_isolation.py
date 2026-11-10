"""Prevent build-tool DLLs from breaking the standalone Qt runtime."""
import importlib.util
from pathlib import Path


def test_validator_rejects_shadowing_windows_icu(tmp_path):
    source = Path(__file__).resolve().parents[1] / "tools" / "validate_release.py"
    spec = importlib.util.spec_from_file_location("release_validator", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    internal = tmp_path / "_internal"
    internal.mkdir()
    (internal / "icuuc.dll").write_bytes(b"incompatible build-tool ICU")
    assert any("icuuc.dll" in error for error in module.validate_release_dir(tmp_path))
