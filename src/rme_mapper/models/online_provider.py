"""Модели и конфигурация провайдеров онлайн-карт (OnlineTileProvider)."""

from dataclasses import dataclass, field
from enum import Enum
import os
import re
from typing import Any


class MapType(str, Enum):
    """Тип отображения онлайн-карты."""

    STANDARD = "standard"    # Стандартная картографическая схема
    SATELLITE = "satellite"  # Спутниковая/аэрофотосъемка
    HYBRID = "hybrid"        # Спутниковая съемка с подписями и дорогами
    CUSTOM = "custom"        # Пользовательский XYZ-сервер


@dataclass
class OnlineTileProvider:
    """Конфигурация провайдера тайлов онлайн-карты."""

    id: str
    display_name: str
    map_type: MapType
    url_template: str
    min_zoom: int = 0
    max_zoom: int = 19
    tile_size: int = 256
    attribution: str = ""
    attribution_required: bool = True
    logo_required: bool = False
    additional_attribution: str = ""
    requires_api_key: bool = False
    api_key_env_name: str | None = None
    api_key_param_name: str | None = None
    subdomains: list[str] = field(default_factory=list)
    is_custom: bool = False

    @property
    def name(self) -> str:
        """Псевдоним для display_name для единообразия API."""
        return self.display_name

    @property
    def attribution_text(self) -> str:
        """Текст атрибуции провайдера (синоним для attribution)."""
        return self.attribution

    @staticmethod
    def validate_url_template(template: str) -> bool:
        """Проверка наличия обязательных плейсхолдеров {z}, {x}, {y} в шаблоне URL."""
        if not template or not isinstance(template, str):
            return False
        clean = template.strip()
        has_z = "{z}" in clean
        has_x = "{x}" in clean
        has_y = "{y}" in clean
        return has_z and has_x and has_y

    def get_effective_api_key(self, user_key: str | None = None) -> str | None:
        """Получение ключа: сначала пользовательский, затем из переменной окружения."""
        key = None
        if user_key and user_key.strip():
            key = user_key.strip()
        elif self.api_key_env_name:
            env_val = os.environ.get(self.api_key_env_name, "").strip()
            if env_val:
                key = env_val

        if key and key.startswith("sk."):
            raise ValueError("Mapbox secret tokens (sk...) are strictly forbidden in client applications.")
        return key

    def build_tile_url(self, z: int, x: int, y: int, api_key: str | None = None) -> str:
        """Построение итогового URL для скачивания тайла (z, x, y)."""
        if not self.validate_url_template(self.url_template):
            raise ValueError(f"Некорректный шаблон URL для провайдера '{self.id}': {self.url_template}")

        subdomain = ""
        if self.subdomains:
            # Детерминированный выбор субдомена по координатам
            idx = (x + y) % len(self.subdomains)
            subdomain = self.subdomains[idx]

        effective_key = self.get_effective_api_key(api_key) or ""
        if effective_key.startswith("sk."):
            raise ValueError("Mapbox secret tokens (sk...) are strictly forbidden in client applications.")

        url = self.url_template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        if "{s}" in url:
            url = url.replace("{s}", subdomain)
        if "{api_key}" in url:
            url = url.replace("{api_key}", effective_key)
        elif "{key}" in url:
            url = url.replace("{key}", effective_key)
        elif self.api_key_param_name and effective_key:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{self.api_key_param_name}={effective_key}"

        return url

    def to_dict(self) -> dict[str, Any]:
        """Сериализация провайдера (без секретных ключей!)."""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "map_type": self.map_type.value,
            "url_template": self.url_template,
            "min_zoom": self.min_zoom,
            "max_zoom": self.max_zoom,
            "tile_size": self.tile_size,
            "attribution": self.attribution,
            "attribution_text": self.attribution,
            "attribution_required": self.attribution_required,
            "logo_required": self.logo_required,
            "additional_attribution": self.additional_attribution,
            "requires_api_key": self.requires_api_key,
            "api_key_env_name": self.api_key_env_name,
            "api_key_param_name": self.api_key_param_name,
            "subdomains": list(self.subdomains),
            "is_custom": self.is_custom,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OnlineTileProvider":
        """Десериализация провайдера из словаря."""
        map_type_str = data.get("map_type", "standard")
        try:
            map_type = MapType(map_type_str)
        except ValueError:
            map_type = MapType.STANDARD

        attr = str(data.get("attribution_text") or data.get("attribution", ""))
        return cls(
            id=str(data["id"]),
            display_name=str(data.get("display_name") or data["id"]),
            map_type=map_type,
            url_template=str(data.get("url_template", "")),
            min_zoom=int(data.get("min_zoom", 0)),
            max_zoom=int(data.get("max_zoom", 19)),
            tile_size=int(data.get("tile_size", 256)),
            attribution=attr,
            attribution_required=bool(data.get("attribution_required", True)),
            logo_required=bool(data.get("logo_required", False)),
            additional_attribution=str(data.get("additional_attribution", "")),
            requires_api_key=bool(data.get("requires_api_key", False)),
            api_key_env_name=data.get("api_key_env_name"),
            subdomains=list(data.get("subdomains", [])),
            is_custom=bool(data.get("is_custom", False)),
        )


# =============================================================================
# Встроенные стандартные провайдеры
# =============================================================================

# OpenStreetMap Standard (единственный разрешенный публичный XYZ без API-ключа при соблюдении ToS)
OSM_STANDARD = OnlineTileProvider(
    id="osm_standard",
    display_name="OpenStreetMap",
    map_type=MapType.STANDARD,
    url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    min_zoom=0,
    max_zoom=19,
    tile_size=256,
    attribution="© OpenStreetMap contributors",
    attribution_required=True,
    logo_required=False,
    additional_attribution="",
    requires_api_key=False,
    api_key_env_name=None,
    subdomains=[],
    is_custom=False,
)

# Архитектурная поддержка провайдеров спутниковых снимков с требованием API-ключа
MAPBOX_SATELLITE = OnlineTileProvider(
    id="mapbox_satellite",
    display_name="Mapbox Satellite",
    map_type=MapType.SATELLITE,
    url_template="https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}.jpg?access_token={api_key}",
    min_zoom=0,
    max_zoom=22,
    tile_size=256,
    attribution="© Mapbox © OpenStreetMap © Maxar",
    attribution_required=True,
    logo_required=True,
    additional_attribution="© Maxar",
    requires_api_key=True,
    api_key_env_name="MAPBOX_API_KEY",
    subdomains=[],
    is_custom=False,
)

MAPBOX_HYBRID = OnlineTileProvider(
    id="mapbox_hybrid",
    display_name="Mapbox Satellite Streets (Hybrid)",
    map_type=MapType.HYBRID,
    url_template="https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/tiles/256/{z}/{x}/{y}?access_token={api_key}",
    min_zoom=0,
    max_zoom=22,
    tile_size=256,
    attribution="© Mapbox © OpenStreetMap",
    attribution_required=True,
    logo_required=True,
    additional_attribution="",
    requires_api_key=True,
    api_key_env_name="MAPBOX_API_KEY",
    subdomains=[],
    is_custom=False,
)


class ProviderRegistry:
    """Реестр доступных картографических провайдеров."""

    _providers: dict[str, OnlineTileProvider] = {}

    @classmethod
    def _ensure_defaults(cls) -> None:
        if not cls._providers:
            cls.register_provider(OSM_STANDARD)
            cls.register_provider(MAPBOX_SATELLITE)
            cls.register_provider(MAPBOX_HYBRID)

    @classmethod
    def register_provider(cls, provider: OnlineTileProvider) -> None:
        """Регистрация провайдера."""
        cls._providers[provider.id] = provider

    @classmethod
    def get_provider(cls, provider_id: str) -> OnlineTileProvider | None:
        """Получение провайдера по идентификатору."""
        cls._ensure_defaults()
        return cls._providers.get(provider_id)

    @classmethod
    def list_providers(cls, map_type: MapType | None = None) -> list[OnlineTileProvider]:
        """Список зарегистрированных провайдеров с опциональной фильтрацией по типу."""
        cls._ensure_defaults()
        if map_type is None:
            return list(cls._providers.values())
        return [p for p in cls._providers.values() if p.map_type == map_type]

    @classmethod
    def create_custom_provider(
        cls,
        name: str,
        url_template: str,
        map_type: MapType = MapType.CUSTOM,
        attribution: str = "",
        attribution_required: bool = True,
        logo_required: bool = False,
        additional_attribution: str = "",
        min_zoom: int = 0,
        max_zoom: int = 19,
        requires_api_key: bool = False,
        id: str | None = None,
        api_key_param_name: str | None = None,
    ) -> OnlineTileProvider:
        """Создание и регистрация пользовательского провайдера Custom XYZ."""
        safe_id = id or ("custom_" + re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower()))
        provider = OnlineTileProvider(
            id=safe_id,
            display_name=name.strip(),
            map_type=map_type,
            url_template=url_template.strip(),
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            tile_size=256,
            attribution=attribution.strip(),
            attribution_required=attribution_required,
            logo_required=logo_required,
            additional_attribution=additional_attribution.strip(),
            requires_api_key=requires_api_key,
            api_key_param_name=api_key_param_name,
            is_custom=True,
        )
        cls.register_provider(provider)
        return provider
