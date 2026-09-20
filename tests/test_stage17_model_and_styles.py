"""Тесты для Этапа 17: Расширенная модель объектов, стили маркера и геозоны, валидация и форматы проектов."""

import json
from pathlib import Path
import pytest

from rme_mapper.coordinates.validator import ValidationError
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import (
    ALLOWED_BORDER_STYLES,
    ALLOWED_SYMBOLS,
    MAX_CATEGORY_LEN,
    MAX_DESCRIPTION_LEN,
    MAX_OBJECT_NUMBER_LEN,
    PointStyle,
    PointZoneStyle,
    StyleValidator,
    validate_border_style,
    validate_border_width,
    validate_category,
    validate_description,
    validate_object_number,
    validate_stroke_width,
)
from rme_mapper.models.project_data import (
    PRIMARY_PROJECT_FORMAT,
    ProjectData,
    ProjectMapData,
    ProjectPointData,
)
from rme_mapper.services.point_service import PointService
from rme_mapper.services.project_service import (
    MAX_SUPPORTED_VERSION,
    ProjectService,
)


# =============================================================================
# 1. Тесты модели MapPoint и дефолтных значений Этапа 17
# =============================================================================


def test_01_map_point_stage17_fields_defaults():
    """Проверка наличия и значений по умолчанию всех новых полей MapPoint."""
    p = MapPoint(name="Объект 1", latitude=56.6, longitude=47.8)

    # Метаданные объекта
    assert p.object_number == ""
    assert p.description == ""
    assert p.category == ""
    assert p.visible is True

    # Стиль маркера (обводка и прозрачность)
    assert p.stroke_red == 0
    assert p.stroke_green == 0
    assert p.stroke_blue == 0
    assert p.stroke_width == 1.0
    assert p.opacity == 100
    assert p.marker_opacity == 100

    # Стиль границы зоны
    assert p.zone_border_red == 220
    assert p.zone_border_green == 30
    assert p.zone_border_blue == 30
    assert p.zone_border_width == 1.0
    assert p.zone_border_style == "solid"


def test_02_map_point_style_and_zone_properties():
    """Проверка обратной совместимости через свойства style и zone."""
    p = MapPoint(
        name="Трансформатор",
        latitude=56.63,
        longitude=47.89,
        stroke_red=255,
        stroke_green=128,
        stroke_blue=0,
        stroke_width=2.5,
        opacity=80,
        zone_border_red=0,
        zone_border_green=0,
        zone_border_blue=255,
        zone_border_width=3.0,
        zone_border_style="dash",
    )

    style = p.style
    assert isinstance(style, PointStyle)
    assert style.stroke_red == 255
    assert style.stroke_width == 2.5
    assert style.opacity == 80

    zone = p.zone
    assert isinstance(zone, PointZoneStyle)
    assert zone.border_red == 0
    assert zone.border_green == 0
    assert zone.border_blue == 255
    assert zone.border_width == 3.0
    assert zone.border_style == "dash"


# =============================================================================
# 2. Валидаторы StyleValidator
# =============================================================================


def test_03_validate_stroke_width():
    """Проверка валидации толщины обводки маркера (0.0 .. 10.0 px)."""
    assert StyleValidator.validate_stroke_width(0.0) == 0.0
    assert StyleValidator.validate_stroke_width(10.0) == 10.0
    assert StyleValidator.validate_stroke_width("2,5") == 2.5
    assert StyleValidator.validate_stroke_width("3.0") == 3.0
    assert StyleValidator.validate_stroke_width(None) == 1.0
    assert validate_stroke_width(5) == 5.0

    with pytest.raises(ValidationError):
        StyleValidator.validate_stroke_width(-0.1)

    with pytest.raises(ValidationError):
        StyleValidator.validate_stroke_width(10.1)

    with pytest.raises(ValidationError):
        StyleValidator.validate_stroke_width("abc")


def test_04_validate_border_width():
    """Проверка валидации толщины границы зоны (0.0 .. 10.0 px)."""
    assert StyleValidator.validate_border_width(0) == 0.0
    assert StyleValidator.validate_border_width(10) == 10.0
    assert StyleValidator.validate_border_width("1,5") == 1.5
    assert validate_border_width(None) == 1.0

    with pytest.raises(ValidationError):
        StyleValidator.validate_border_width(-1)

    with pytest.raises(ValidationError):
        StyleValidator.validate_border_width(11)


def test_05_validate_border_style():
    """Проверка валидации стиля границы зоны ('solid', 'dash', 'dot')."""
    assert StyleValidator.validate_border_style("solid") == "solid"
    assert StyleValidator.validate_border_style("DASH") == "dash"
    assert StyleValidator.validate_border_style(" dot ") == "dot"
    assert validate_border_style("solid") == "solid"

    with pytest.raises(ValidationError):
        StyleValidator.validate_border_style("zigzag")

    with pytest.raises(ValidationError):
        StyleValidator.validate_border_style(123)


def test_06_validate_object_strings():
    """Проверка ограничений длины строк номера объекта, категории и описания."""
    assert validate_object_number("A-123") == "A-123"
    assert validate_object_number(" " * 5) == ""
    assert validate_category("Опоры ЛЭП") == "Опоры ЛЭП"
    assert validate_description("Подробное примечание...") == "Подробное примечание..."

    # Лимит номера объекта (100)
    valid_num = "X" * MAX_OBJECT_NUMBER_LEN
    assert validate_object_number(valid_num) == valid_num
    with pytest.raises(ValidationError):
        validate_object_number("X" * (MAX_OBJECT_NUMBER_LEN + 1))

    # Лимит категории (200)
    valid_cat = "C" * MAX_CATEGORY_LEN
    assert validate_category(valid_cat) == valid_cat
    with pytest.raises(ValidationError):
        validate_category("C" * (MAX_CATEGORY_LEN + 1))

    # Лимит описания (8192)
    valid_desc = "D" * MAX_DESCRIPTION_LEN
    assert validate_description(valid_desc) == valid_desc
    with pytest.raises(ValidationError):
        validate_description("D" * (MAX_DESCRIPTION_LEN + 1))


# =============================================================================
# 3. Сервис точек (PointService) и категории
# =============================================================================


def test_07_point_service_get_used_categories():
    """Проверка сбора уникальных категорий для выпадающего списка."""
    ps = PointService()
    ps.add_point("Точка 1", 56.0, 47.0, category="Скважины")
    ps.add_point("Точка 2", 56.1, 47.1, category="Трубопровод")
    ps.add_point("Точка 3", 56.2, 47.2, category="Скважины")  # дубликат
    ps.add_point("Точка 4", 56.3, 47.3, category="")  # пустая

    cats = ps.get_used_categories()
    assert cats == ["Скважины", "Трубопровод"]


# =============================================================================
# 4. Проекты: сериализация, v1 обратная совместимость и v2
# =============================================================================


def test_08_project_point_data_roundtrip():
    """Сериализация и десериализация всех полей ProjectPointData."""
    p = MapPoint(
        name="ТП-504",
        latitude=56.634,
        longitude=47.892,
        object_number="№504-Б",
        description="Трансформаторная подстанция 10/0.4 кВ\nВведена в 2021 г.",
        category="Энергетика",
        visible=False,
        stroke_red=10,
        stroke_green=20,
        stroke_blue=30,
        stroke_width=2.0,
        opacity=90,
        zone_enabled=True,
        radius_m=500.0,
        zone_border_red=40,
        zone_border_green=50,
        zone_border_blue=60,
        zone_border_width=3.5,
        zone_border_style="dot",
    )

    p_data = ProjectPointData.from_map_point(p)
    d = p_data.to_dict()

    assert d["object_number"] == "№504-Б"
    assert d["description"].startswith("Трансформаторная")
    assert d["category"] == "Энергетика"
    assert d["visible"] is False
    assert d["stroke_red"] == 10
    assert d["stroke_width"] == 2.0
    assert d["opacity"] == 90
    assert d["zone_border_style"] == "dot"

    restored = ProjectPointData.from_dict(d).to_map_point()
    assert restored.object_number == "№504-Б"
    assert restored.description == p.description
    assert restored.category == "Энергетика"
    assert restored.visible is False
    assert restored.stroke_red == 10
    assert restored.stroke_width == 2.0
    assert restored.opacity == 90
    assert restored.zone_border_style == "dot"
    assert restored.zone_border_width == 3.5


def test_09_v1_project_backward_compatibility(tmp_path):
    """Проект версии 1 без полей Этапа 17 успешно загружается со значениями по умолчанию."""
    v1_dict = {
        "format": PRIMARY_PROJECT_FORMAT,
        "version": 1,
        "map": {"map_id": "test_map", "source_type": "geopackage"},
        "layers": {"boundary": True},
        "points": [
            {
                "id": "old-point-1",
                "name": "Старая точка",
                "latitude": 56.63,
                "longitude": 47.89,
                "source_crs": "OGC:CRS84",
                "symbol": "square",
                "size": 14.0,
                "red": 200,
                "green": 50,
                "blue": 50,
                "zone_enabled": True,
                "radius_m": 1200.0,
                "zone_red": 200,
                "zone_green": 50,
                "zone_blue": 50,
                "zone_opacity": 35,
            }
        ],
    }

    file_path = tmp_path / "legacy_v1.gpmap"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(v1_dict, f)

    loaded = ProjectService.load_project(file_path)
    assert len(loaded.points) == 1
    pt = loaded.points[0].to_map_point()
    assert pt.name == "Старая точка"
    assert pt.object_number == ""
    assert pt.description == ""
    assert pt.category == ""
    assert pt.visible is True
    assert pt.stroke_width == 1.0
    assert pt.opacity == 100
    assert pt.zone_border_style == "solid"


def test_10_v2_project_save_and_load(tmp_path):
    """Проект версии 2 сохраняет и восстанавливает расширенную модель объектов."""
    p = MapPoint(
        name="Насосная станция",
        latitude=56.55,
        longitude=47.77,
        object_number="НС-12",
        description="Резервная станция",
        category="Водоснабжение",
        visible=True,
        stroke_width=2.5,
        opacity=75,
        zone_enabled=True,
        radius_m=3000.0,
        zone_border_style="dash",
        zone_border_width=2.0,
    )
    proj = ProjectData(
        version=2,
        points=[ProjectPointData.from_map_point(p)],
    )

    out_file = tmp_path / "project_v2.gpmap"
    ProjectService.save_project(proj, out_file)

    loaded = ProjectService.load_project(out_file)
    assert loaded.version == 2
    assert len(loaded.points) == 1
    restored = loaded.points[0].to_map_point()
    assert restored.object_number == "НС-12"
    assert restored.category == "Водоснабжение"
    assert restored.opacity == 75
    assert restored.zone_border_style == "dash"
