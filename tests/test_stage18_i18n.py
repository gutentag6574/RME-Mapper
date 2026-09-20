"""Тесты локализации RU / EN для Этапа 18 (Point 26)."""

from rme_mapper.i18n import get_language, set_language, tr
from rme_mapper.i18n.translations_en import TRANSLATIONS_EN
from rme_mapper.i18n.translations_ru import TRANSLATIONS_RU
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.object_group import ObjectGroup


def test_stage18_translations_symmetry():
    """Проверка симметрии ключей локализации Этапа 18 в словарях RU и EN."""
    stage18_keys = [
        "panel.groups",
        "groups.all",
        "groups.ungrouped",
        "action.create_group",
        "action.rename_group",
        "action.edit_group_desc",
        "action.delete_group",
        "action.move_to_group",
        "action.show_group",
        "action.hide_group",
        "action.select_group_objects",
        "action.zoom_to_group",
        "action.edit_group_style",
        "action.change_category",
        "category.all",
        "dialog.group.create_title",
        "dialog.group.edit_title",
        "dialog.group.name_label",
        "dialog.group.desc_label",
        "dialog.delete_group.title",
        "dialog.delete_group.message",
        "dialog.change_category.title",
        "properties.group",
        "points.count_filtered",
        "points.count_total",
    ]

    for k in stage18_keys:
        assert k in TRANSLATIONS_RU, f"Ключ '{k}' отсутствует в TRANSLATIONS_RU"
        assert k in TRANSLATIONS_EN, f"Ключ '{k}' отсутствует в TRANSLATIONS_EN"
        assert len(TRANSLATIONS_RU[k]) > 0
        assert len(TRANSLATIONS_EN[k]) > 0


def test_user_strings_not_translated_on_language_change():
    """Проверка, что пользовательские названия групп, описания и категории не меняются при смене языка."""
    original_lang = get_language()
    try:
        set_language("ru")
        custom_group_name = "Участок №12 (Особый)"
        custom_group_desc = "Описание опытного участка"
        custom_category = "Редкие растения"

        grp = ObjectGroup(name=custom_group_name, description=custom_group_desc)
        pt = MapPoint(name="Точка 1", latitude=56.0, longitude=47.0, category=custom_category, group_id=grp.id)

        # Переключаем язык на English
        set_language("en")

        # Системные термины переводятся
        assert tr("groups.ungrouped") == "Ungrouped"
        assert tr("groups.all") == "All Objects"
        assert tr("category.all") == "All Categories"

        # Пользовательские строки остаются ровно такими, как их создал пользователь
        assert grp.name == custom_group_name
        assert grp.description == custom_group_desc
        assert pt.category == custom_category
        assert pt.name == "Точка 1"

        # Возвращаем русский язык
        set_language("ru")
        assert tr("groups.ungrouped") == "Без группы"
        assert tr("groups.all") == "Все объекты"
        assert tr("category.all") == "Все категории"

        assert grp.name == custom_group_name
        assert grp.description == custom_group_desc
        assert pt.category == custom_category

    finally:
        set_language(original_lang)
