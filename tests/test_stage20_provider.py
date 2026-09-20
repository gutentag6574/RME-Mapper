"""Тесты провайдеров онлайн-карт (Этап 20: Tests 9-18)."""

import os
import pytest

from rme_mapper.models.online_provider import (
    MapType,
    OnlineTileProvider,
    ProviderRegistry,
    OSM_STANDARD,
    MAPBOX_SATELLITE,
    MAPBOX_HYBRID,
)


def test_09_provider_config_fields():
    """Тест 9: Модель провайдера содержит все требуемые спецификацией поля."""
    p = OSM_STANDARD
    assert p.id == "osm_standard"
    assert p.display_name == "OpenStreetMap"
    assert p.map_type == MapType.STANDARD
    assert "{z}" in p.url_template and "{x}" in p.url_template and "{y}" in p.url_template
    assert p.min_zoom == 0
    assert p.max_zoom == 19
    assert p.tile_size == 256
    assert "OpenStreetMap" in p.attribution


def test_10_standard_map_type():
    """Тест 10: Провайдеры типа Standard доступны через реестр."""
    standards = ProviderRegistry.list_providers(MapType.STANDARD)
    assert any(p.id == "osm_standard" for p in standards)
    assert all(p.map_type == MapType.STANDARD for p in standards)


def test_11_satellite_map_type():
    """Тест 11: Провайдеры типа Satellite требуют API-ключ."""
    satellites = ProviderRegistry.list_providers(MapType.SATELLITE)
    assert len(satellites) > 0
    assert any(p.requires_api_key is True for p in satellites)


def test_12_hybrid_map_type():
    """Тест 12: Провайдеры типа Hybrid зарегистрированы корректно."""
    hybrids = ProviderRegistry.list_providers(MapType.HYBRID)
    assert len(hybrids) > 0
    assert any(p.map_type == MapType.HYBRID for p in hybrids)


def test_13_min_max_zoom_limits():
    """Тест 13: Ограничения зума провайдера валидны."""
    assert OSM_STANDARD.min_zoom == 0
    assert OSM_STANDARD.max_zoom == 19
    assert MAPBOX_SATELLITE.max_zoom >= 19


def test_14_attribution_mandatory():
    """Тест 14: Каждый провайдер имеет непустую обязательную атрибуцию."""
    for p in ProviderRegistry.list_providers():
        assert len(p.attribution.strip()) > 0, f"Пустая атрибуция у провайдера {p.id}"


def test_15_api_key_required_flag():
    """Тест 15: Флаг requires_api_key и получение ключа из переменной окружения."""
    p = MAPBOX_SATELLITE
    assert p.requires_api_key is True
    assert p.api_key_env_name == "MAPBOX_API_KEY"

    # При отсутствии ключа
    orig_env = os.environ.get("MAPBOX_API_KEY")
    if "MAPBOX_API_KEY" in os.environ:
        del os.environ["MAPBOX_API_KEY"]

    try:
        assert p.get_effective_api_key(None) is None
        assert p.get_effective_api_key("user_secret_123") == "user_secret_123"

        # Из переменной окружения
        os.environ["MAPBOX_API_KEY"] = "env_secret_456"
        assert p.get_effective_api_key(None) == "env_secret_456"
    finally:
        if orig_env is not None:
            os.environ["MAPBOX_API_KEY"] = orig_env
        elif "MAPBOX_API_KEY" in os.environ:
            del os.environ["MAPBOX_API_KEY"]


def test_16_url_generation_substitution():
    """Тест 16: Корректная подстановка {z}, {x}, {y}, {api_key} в URL."""
    url = OSM_STANDARD.build_tile_url(z=5, x=10, y=12)
    assert url == "https://tile.openstreetmap.org/5/10/12.png"

    url_key = MAPBOX_SATELLITE.build_tile_url(z=8, x=100, y=120, api_key="my_key")
    assert "8/100/120" in url_key
    assert "access_token=my_key" in url_key


def test_17_invalid_url_template_validation():
    """Тест 17: Валидация шаблона URL отклоняет строки без обязательных плейсхолдеров."""
    assert OnlineTileProvider.validate_url_template("https://tiles.org/{z}/{x}/{y}.png") is True
    assert OnlineTileProvider.validate_url_template("https://tiles.org/{z}/{x}.png") is False  # без {y}
    assert OnlineTileProvider.validate_url_template("https://tiles.org/{x}/{y}.png") is False  # без {z}
    assert OnlineTileProvider.validate_url_template("https://tiles.org/map.png") is False
    assert OnlineTileProvider.validate_url_template("") is False


def test_18_custom_xyz_provider_creation():
    """Тест 18: Создание и регистрация пользовательского Custom XYZ провайдера."""
    custom = ProviderRegistry.create_custom_provider(
        name="Local Server",
        url_template="https://localhost:8080/tiles/{z}/{x}/{y}.png",
        attribution="© Local Data",
        min_zoom=1,
        max_zoom=16,
    )
    assert custom.is_custom is True
    assert custom.id.startswith("custom_")
    assert ProviderRegistry.get_provider(custom.id) is not None

    url = custom.build_tile_url(3, 4, 5)
    assert url == "https://localhost:8080/tiles/3/4/5.png"
