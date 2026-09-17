"""Тестовый набор для ЭТАПА 12 — Двуязычный интерфейс Русский / English.

Охватывает:
- Раздел 45: Ядро интернационализации (i18n core, translations_ru/en, fallback, substitution, symmetry).
- Раздел 46: Настройки и персистентность языка (AppSettingsService, project serialization independence).
- Раздел 47: Локализация главного окна (MainWindow, меню, действия, панели, таблица, оверлей, заголовок).
- Раздел 48: Локализация диалоговых окон (PointDialog, OpenMapDialog, AboutDialog).
- Раздел 49: Локализация ошибок валидации (DD, DMS, Style, Zone, ValidationError).
- Раздел 50: Независимость пользовательских данных и моделей от языка.
- Раздел 51: Динамическое переключение 'на лету' (без перезапуска, сохранение карты, точек и состояния).
"""

import os
from pathlib import Path
import pytest

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from rme_mapper.app_info import (
    AUTHOR_NAME,
    APP_DESCRIPTION_EN,
    APP_DESCRIPTION_RU,
    APP_NAME,
    get_app_description,
)
from rme_mapper.coordinates.validator import CoordinateValidator, ValidationError
from rme_mapper.i18n import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    TranslationService,
    get_language,
    get_translation_service,
    set_language,
    tr,
)
from rme_mapper.i18n.translations_en import TRANSLATIONS_EN
from rme_mapper.i18n.translations_ru import TRANSLATIONS_RU
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import PointStyle, StyleValidator
from rme_mapper.models.project_data import ProjectData, ProjectMapData
from rme_mapper.services.app_settings_service import AppSettingsService
from rme_mapper.services.geodesic_service import GeodesicService
from rme_mapper.ui.about_dialog import AboutDialog
from rme_mapper.ui.add_point_dialog import PointDialog
from rme_mapper.ui.main_window import MainWindow, get_symbol_display_name
from rme_mapper.ui.open_map_dialog import OpenMapDialog


@pytest.fixture(scope="module")
def qapp():
    """Инициализация QApplication для тестов интерфейса."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture(autouse=True)
def reset_language():
    """Автоматический сброс языка в 'ru' перед и после каждого теста."""
    set_language("ru")
    yield
    set_language("ru")


# =============================================================================
# РАЗДЕЛ 45: ЯДРО ИНТЕРНАЦИОНАЛИЗАЦИИ (i18n Core)
# =============================================================================

def test_01_default_language_is_ru():
    """01. Язык по умолчанию — 'ru'."""
    assert DEFAULT_LANGUAGE == "ru"
    assert get_language() == "ru"


def test_02_supported_languages():
    """02. Поддерживаются ровно два языка: 'ru' и 'en'."""
    assert set(SUPPORTED_LANGUAGES) == {"ru", "en"}


def test_03_set_language_en():
    """03. Переключение языка на 'en' обновляет активный язык."""
    set_language("en")
    assert get_language() == "en"
    set_language("ru")
    assert get_language() == "ru"


def test_04_set_unsupported_language_fallback():
    """04. Попытка установить неподдерживаемый язык вызывает ValueError и не меняет активный язык."""
    with pytest.raises(ValueError):
        set_language("fr")
    assert get_language() == "ru"
    with pytest.raises(ValueError):
        set_language("de")
    assert get_language() == "ru"


def test_05_translate_existing_key_ru():
    """05. Перевод существующего ключа в RU возвращает русский текст."""
    set_language("ru")
    assert tr("menu.file") == "Файл"
    assert tr("action.open_map") == "Открыть карту..."
    assert tr("common.yes") == "Да"


def test_06_translate_existing_key_en():
    """06. Перевод существующего ключа в EN возвращает английский текст."""
    set_language("en")
    assert tr("menu.file") == "File"
    assert tr("action.open_map") == "Open Map..."
    assert tr("common.yes") == "Yes"


def test_07_param_substitution():
    """07. Параметрическая подстановка в tr() работает корректно в обоих языках."""
    set_language("ru")
    res_ru = tr("status.map_info", name="Марий Эл", crs="EPSG:4326", count=5)
    assert "Марий Эл" in res_ru and "EPSG:4326" in res_ru and "5" in res_ru

    set_language("en")
    res_en = tr("status.map_info", name="Mari El", crs="EPSG:4326", count=5)
    assert "Mari El" in res_en and "EPSG:4326" in res_en and "5" in res_en


def test_08_missing_key_returns_key():
    """08. Несуществующий ключ возвращает сам ключ без аварийного завершения."""
    assert tr("some.nonexistent.key.xyz") == "some.nonexistent.key.xyz"


def test_09_missing_key_in_en_falls_back_to_ru():
    """09. Если ключ отсутствует в EN, возвращается русский перевод (fallback)."""
    ts = get_translation_service()
    # Временно инжектируем тестовый ключ только в RU
    ts._dictionaries["ru"]["test.temp_only_ru"] = "Только русский"
    try:
        assert ts.translate_in_language("en", "test.temp_only_ru") == "Только русский"
    finally:
        ts._dictionaries["ru"].pop("test.temp_only_ru", None)


def test_10_translations_symmetry_and_counts():
    """10. Словари TRANSLATIONS_RU и TRANSLATIONS_EN имеют идентичный набор ключей."""
    ru_keys = set(TRANSLATIONS_RU.keys())
    en_keys = set(TRANSLATIONS_EN.keys())

    diff_ru_minus_en = ru_keys - en_keys
    diff_en_minus_ru = en_keys - ru_keys

    assert not diff_ru_minus_en, f"Ключи есть в RU, но нет в EN: {diff_ru_minus_en}"
    assert not diff_en_minus_ru, f"Ключи есть в EN, но нет в RU: {diff_en_minus_ru}"
    assert len(ru_keys) >= 200, f"Ожидается не менее 200 ключей, получено {len(ru_keys)}"


def test_11_no_empty_translations():
    """11. Ни один перевод в обоих словарях не является пустым (кроме служебных пустых заголовков колонок)."""
    allowed_empty = {"dialog.map.col_check"}
    for k, v in TRANSLATIONS_RU.items():
        if k not in allowed_empty:
            assert v.strip(), f"Пустое значение в RU для ключа '{k}'"
    for k, v in TRANSLATIONS_EN.items():
        if k not in allowed_empty:
            assert v.strip(), f"Пустое значение в EN для ключа '{k}'"


def test_12_language_changed_signal_emitted():
    """12. При смене языка генерируется сигнал language_changed."""
    ts = get_translation_service()
    emitted_langs = []
    ts.language_changed.connect(lambda lang: emitted_langs.append(lang))

    set_language("en")
    assert emitted_langs == ["en"]
    set_language("ru")
    assert emitted_langs == ["en", "ru"]


# =============================================================================
# РАЗДЕЛ 46: НАСТРОЙКИ И ПЕРСИСТЕНТНОСТЬ (Settings & Persistence)
# =============================================================================

def test_13_app_settings_service_save_and_restore():
    """13. AppSettingsService корректно сохраняет и считывает язык."""
    svc = AppSettingsService(settings=None)  # режим memory-fallback
    assert svc.get_language() == "ru"
    svc.set_language("en")
    assert svc.get_language() == "en"
    svc.set_language("ru")
    assert svc.get_language() == "ru"


def test_14_default_settings_returns_ru():
    """14. Свежий экземпляр AppSettingsService без сохраненных данных возвращает 'ru'."""
    svc = AppSettingsService(settings=None)
    svc.clear()
    assert svc.get_language() == "ru"


def test_15_switching_language_persists_in_settings(qapp):
    """15. Переключение языка в MainWindow сохраняет настройку в AppSettingsService."""
    win = MainWindow()
    win.switch_language("en")
    assert win._settings_service.get_language() == "en"
    win.switch_language("ru")
    assert win._settings_service.get_language() == "ru"
    win.close()


def test_16_project_data_serialization_excludes_language():
    """16. ProjectData и формат *.gpmap никогда не содержат поле language."""
    proj = ProjectData(
        version="1",
        map=ProjectMapData(map_id="mari_el", name="Марий Эл"),
        points=[],
        layers={},
    )
    serialized = proj.to_dict()
    assert "language" not in serialized
    assert "lang" not in serialized
    assert "locale" not in serialized


def test_17_loading_project_does_not_alter_active_language(qapp, tmp_path):
    """17. Открытие файла проекта не меняет текущий язык интерфейса приложения."""
    win = MainWindow()
    win.switch_language("en")

    # Создаем фиктивный проект
    proj_path = tmp_path / "test_proj.gpmap"
    proj_data = ProjectData(
        version="1",
        map=ProjectMapData(name="Test Map"),
        points=[],
        layers={},
    )
    win._project_service.save_project(proj_data, proj_path)

    win.open_project(proj_path)
    assert get_language() == "en"
    win.close()


def test_18_language_switch_does_not_modify_project_dirty_state(qapp):
    """18. Переключение языка не взводит флаг is_modified в проекте."""
    win = MainWindow()
    assert not win.is_modified

    win.switch_language("en")
    assert not win.is_modified

    win.switch_language("ru")
    assert not win.is_modified
    win.close()


def test_19_language_switch_preserves_current_project_path(qapp):
    """19. Переключение языка сохраняет текущий путь к файлу проекта."""
    win = MainWindow()
    fake_path = Path("D:/Projects/sample.gpmap")
    win._current_project_path = fake_path

    win.switch_language("en")
    assert win.current_project_path == fake_path

    win.switch_language("ru")
    assert win.current_project_path == fake_path
    win.close()


# =============================================================================
# РАЗДЕЛ 47: ЛОКАЛИЗАЦИЯ ГЛАВНОГО ОКНА (MainWindow UI)
# =============================================================================

def test_20_main_window_menu_titles_ru(qapp):
    """20. Заголовки верхнего меню на русском языке."""
    win = MainWindow()
    win.switch_language("ru")

    assert win.file_menu.title() == "Файл"
    assert win.map_menu.title() == "Карта"
    assert win.coords_menu.title() == "Координаты"
    assert win.import_menu.title() == "Импорт"
    assert win.export_menu.title() == "Экспорт"
    assert win.settings_menu.title() == "Настройки"
    assert win.language_menu.title() == "Язык"
    assert win.help_menu.title() == "Справка"
    win.close()


def test_21_main_window_menu_titles_en(qapp):
    """21. Заголовки верхнего меню на английском языке."""
    win = MainWindow()
    win.switch_language("en")

    assert win.file_menu.title() == "File"
    assert win.map_menu.title() == "Map"
    assert win.coords_menu.title() == "Coordinates"
    assert win.import_menu.title() == "Import"
    assert win.export_menu.title() == "Export"
    assert win.settings_menu.title() == "Settings"
    assert win.language_menu.title() == "Language"
    assert win.help_menu.title() == "Help"
    win.close()


def test_22_main_window_actions_translation(qapp):
    """22. Пункты меню (Actions) переводятся при смене языка."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.new_action.text() == "Новый проект"
    assert win.open_map_action.text() == "Открыть карту..."
    assert win.about_action.text() == "О программе..."

    win.switch_language("en")
    assert win.new_action.text() == "New Project"
    assert win.open_map_action.text() == "Open Map..."
    assert win.about_action.text() == "About..."
    win.close()


def test_23_main_window_panels_translation(qapp):
    """23. Заголовки панелей (Слои, Точки, Свойства) переводятся."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.layers_title_label.text() == "Слои"
    assert win.points_title_label.text() == "Точки"
    assert win.properties_title_label.text() == "Свойства"

    win.switch_language("en")
    assert win.layers_title_label.text() == "Layers"
    assert win.points_title_label.text() == "Points"
    assert win.properties_title_label.text() == "Properties"
    win.close()


def test_24_main_window_table_headers_translation(qapp):
    """24. Заголовки таблицы точек переводятся на выбранный язык."""
    win = MainWindow()
    win.switch_language("ru")
    headers_ru = [win.points_table.horizontalHeaderItem(i).text() for i in range(6)]
    assert headers_ru == ["№", "Название", "Широта", "Долгота", "Форма", "Радиус"]

    win.switch_language("en")
    headers_en = [win.points_table.horizontalHeaderItem(i).text() for i in range(6)]
    assert headers_en == ["#", "Name", "Latitude", "Longitude", "Shape", "Radius"]
    win.close()


def test_25_startup_overlay_translation(qapp):
    """25. Тексты оверлея пустого старта обновляются при смене языка."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.map_canvas.empty_title_lbl.text() == "GeoPoint Mapper"
    assert win.map_canvas.empty_status_lbl.text() == "Карта не загружена"
    assert win.map_canvas.btn_open_map.text() == "📂  Открыть карту..."

    win.switch_language("en")
    assert win.map_canvas.empty_title_lbl.text() == "GeoPoint Mapper"
    assert win.map_canvas.empty_status_lbl.text() == "No map loaded"
    assert win.map_canvas.btn_open_map.text() == "📂  Open Map..."
    win.close()


def test_26_status_bar_empty_state_translation(qapp):
    """26. Строка состояния без загруженной карты отображает локализованный статус."""
    win = MainWindow()
    win.switch_language("ru")
    assert "Карта не загружена" in win.statusBar().currentMessage()

    win.switch_language("en")
    assert "No map loaded" in win.statusBar().currentMessage()
    win.close()


def test_27_window_title_untitled_ru_en(qapp):
    """27. Заголовок окна без имени отображает 'Без имени' (RU) и 'Untitled' (EN)."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.windowTitle() == "GeoPoint Mapper — Без имени"

    win.switch_language("en")
    assert win.windowTitle() == "GeoPoint Mapper — Untitled"
    win.close()


def test_28_window_title_modified_ru_en(qapp):
    """28. При наличии изменений звездочка '*' отображается в обоих языках."""
    win = MainWindow()
    win._set_modified(True)

    win.switch_language("ru")
    assert win.windowTitle() == "GeoPoint Mapper — Без имени *"

    win.switch_language("en")
    assert win.windowTitle() == "GeoPoint Mapper — Untitled *"
    win._set_modified(False)
    win.close()


def test_29_window_title_named_project_not_translated(qapp):
    """29. Имя сохраненного проекта не переводится при смене языка."""
    win = MainWindow()
    win._current_project_path = Path("MyTerritory.gpmap")

    win.switch_language("ru")
    assert win.windowTitle() == "GeoPoint Mapper — MyTerritory.gpmap"

    win.switch_language("en")
    assert win.windowTitle() == "GeoPoint Mapper — MyTerritory.gpmap"
    win.close()


def test_30_table_shape_column_localized(qapp):
    """30. Колонка формы в таблице точек динамически переводится при смене языка."""
    win = MainWindow()
    pt = win._point_service.add_point(
        name="Точка 1",
        latitude=56.63,
        longitude=47.88,
        symbol="circle",
    )
    win._add_point_to_table(pt)

    win.switch_language("ru")
    assert win.points_table.item(0, 4).text() == "Круг"

    win.switch_language("en")
    assert win.points_table.item(0, 4).text() == "Circle"
    win.close()


def test_31_table_radius_column_localized_units(qapp):
    """31. Колонка радиуса в таблице отображает 'км' в RU и 'km' в EN."""
    win = MainWindow()
    pt = win._point_service.add_point(
        name="Точка Зона",
        latitude=56.63,
        longitude=47.88,
        zone_enabled=True,
        radius_m=5000.0,
    )
    win._add_point_to_table(pt)

    win.switch_language("ru")
    assert win.points_table.item(0, 5).text() == "5 км"

    win.switch_language("en")
    assert win.points_table.item(0, 5).text() == "5 km"
    win.close()


def test_32_properties_panel_labels_localized(qapp):
    """32. Метки свойств в правой панели локализованы."""
    win = MainWindow()
    win.switch_language("ru")
    assert "Название:" in win.prop_name_lbl.text()
    assert "Широта:" in win.prop_lat_lbl.text()
    assert "Зона:" in win.prop_zone_lbl.text()

    win.switch_language("en")
    assert "Name:" in win.prop_name_lbl.text()
    assert "Latitude:" in win.prop_lat_lbl.text()
    assert "Zone:" in win.prop_zone_lbl.text()
    win.close()


def test_33_properties_panel_values_localized(qapp):
    """33. Значения свойств (Да/Нет, форма, радиус) локализованы."""
    win = MainWindow()
    pt = MapPoint(
        name="Йошкар-Ола",
        latitude=56.63,
        longitude=47.88,
        symbol="square",
        zone_enabled=True,
        radius_m=2000.0,
    )

    win.switch_language("ru")
    win._update_properties_panel(pt)
    assert win.prop_shape_val.text() == "Квадрат"
    assert win.prop_zone_val.text() == "Да"
    assert win.prop_zone_radius_val.text() == "2 км"

    win.switch_language("en")
    win._update_properties_panel(pt)
    assert win.prop_shape_val.text() == "Square"
    assert win.prop_zone_val.text() == "Yes"
    assert win.prop_zone_radius_val.text() == "2 km"
    win.close()


def test_34_language_menu_exclusive_actions(qapp):
    """34. Меню выбора языка имеет эксклюзивный выбор (QActionGroup)."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.lang_ru_action.isChecked()
    assert not win.lang_en_action.isChecked()

    win.switch_language("en")
    assert not win.lang_ru_action.isChecked()
    assert win.lang_en_action.isChecked()
    win.close()


# =============================================================================
# РАЗДЕЛ 48: ДИАЛОГОВЫЕ ОКНА (Dialogs Translation)
# =============================================================================

def test_35_point_dialog_create_mode_title_ru_en(qapp):
    """35. Заголовок PointDialog в режиме CREATE локализован."""
    set_language("ru")
    dlg_ru = PointDialog(mode="CREATE")
    assert dlg_ru.windowTitle() == "Добавить точку"

    set_language("en")
    dlg_en = PointDialog(mode="CREATE")
    assert dlg_en.windowTitle() == "Add Point"


def test_36_point_dialog_edit_mode_title_ru_en(qapp):
    """36. Заголовок PointDialog в режиме EDIT локализован."""
    pt = MapPoint(name="P1", latitude=56.0, longitude=47.0)
    set_language("ru")
    dlg_ru = PointDialog(point=pt, mode="EDIT")
    assert dlg_ru.windowTitle() == "Редактировать точку"

    set_language("en")
    dlg_en = PointDialog(point=pt, mode="EDIT")
    assert dlg_en.windowTitle() == "Edit Point"


def test_37_point_dialog_button_create_mode_ru_en(qapp):
    """37. Кнопка отправки формы PointDialog в режиме CREATE."""
    set_language("ru")
    dlg_ru = PointDialog(mode="CREATE")
    assert dlg_ru.btn_add.text() == "Добавить"

    set_language("en")
    dlg_en = PointDialog(mode="CREATE")
    assert dlg_en.btn_add.text() == "Add"


def test_38_point_dialog_button_edit_mode_ru_en(qapp):
    """38. Кнопка отправки формы PointDialog в режиме EDIT."""
    pt = MapPoint(name="P1", latitude=56.0, longitude=47.0)
    set_language("ru")
    dlg_ru = PointDialog(point=pt, mode="EDIT")
    assert dlg_ru.btn_add.text() == "Сохранить"

    set_language("en")
    dlg_en = PointDialog(point=pt, mode="EDIT")
    assert dlg_en.btn_add.text() == "Save"


def test_39_point_dialog_labels_and_placeholders_ru_en(qapp):
    """39. Подписи полей и плейсхолдеры PointDialog локализованы."""
    set_language("ru")
    dlg_ru = PointDialog(mode="CREATE")
    assert dlg_ru.name_label.text() == "Название:"
    assert dlg_ru.rb_dd.text() == "Десятичные градусы (DD)"
    assert dlg_ru.rb_dms.text() == "Градусы / минуты / секунды (DMS)"

    set_language("en")
    dlg_en = PointDialog(mode="CREATE")
    assert dlg_en.name_label.text() == "Name:"
    assert dlg_en.rb_dd.text() == "Decimal Degrees (DD)"
    assert dlg_en.rb_dms.text() == "Degrees / Minutes / Seconds (DMS)"


def test_40_point_dialog_shape_combo_items_ru_en(qapp):
    """40. Элементы выпадающего списка форм маркера локализованы."""
    set_language("ru")
    dlg_ru = PointDialog(mode="CREATE")
    assert dlg_ru.symbol_combo.itemText(0) == "Круг"
    assert dlg_ru.symbol_combo.itemText(1) == "Квадрат"
    assert dlg_ru.symbol_combo.itemText(2) == "Треугольник"

    set_language("en")
    dlg_en = PointDialog(mode="CREATE")
    assert dlg_en.symbol_combo.itemText(0) == "Circle"
    assert dlg_en.symbol_combo.itemText(1) == "Square"
    assert dlg_en.symbol_combo.itemText(2) == "Triangle"


def test_41_open_map_dialog_title_ru_en(qapp):
    """41. Заголовок OpenMapDialog локализован."""
    set_language("ru")
    dlg_ru = OpenMapDialog()
    assert dlg_ru.windowTitle() == "Открыть карту — GeoPoint Mapper"

    set_language("en")
    dlg_en = OpenMapDialog()
    assert dlg_en.windowTitle() == "Open Map — GeoPoint Mapper"


def test_42_open_map_dialog_widgets_ru_en(qapp):
    """42. Кнопки и группы OpenMapDialog локализованы."""
    set_language("ru")
    dlg_ru = OpenMapDialog()
    assert dlg_ru.mode_group.title() == "Источник карты"
    assert dlg_ru.rb_file.text() == "Файл GeoPackage (*.gpkg)"
    assert dlg_ru.rb_catalog.text() == "Каталог профилей"
    assert dlg_ru.btn_open.text() == "Открыть карту"

    set_language("en")
    dlg_en = OpenMapDialog()
    assert dlg_en.mode_group.title() == "Map Source"
    assert dlg_en.rb_file.text() == "GeoPackage File (*.gpkg)"
    assert dlg_en.rb_catalog.text() == "Profile Catalog"
    assert dlg_en.btn_open.text() == "Open Map"


def test_43_about_dialog_title_ru_en(qapp):
    """43. Заголовок AboutDialog локализован."""
    set_language("ru")
    dlg_ru = AboutDialog()
    assert dlg_ru.windowTitle() == "О программе — GeoPoint Mapper"

    set_language("en")
    dlg_en = AboutDialog()
    assert dlg_en.windowTitle() == "About — GeoPoint Mapper"


def test_44_about_dialog_labels_and_desc_ru_en(qapp):
    """44. Метки и описание AboutDialog локализованы на RU и EN."""
    set_language("ru")
    dlg_ru = AboutDialog()
    assert dlg_ru.author_title_label.text() == "Автор и разработчик:"
    assert dlg_ru.desc_label.text() == APP_DESCRIPTION_RU

    set_language("en")
    dlg_en = AboutDialog()
    assert dlg_en.author_title_label.text() == "Author and Developer:"
    assert dlg_en.desc_label.text() == APP_DESCRIPTION_EN


def test_45_about_dialog_author_and_contacts_immutable(qapp):
    """45. Имя автора, Telegram и Email не меняются при переключении языка."""
    set_language("ru")
    dlg_ru = AboutDialog()
    author_ru = dlg_ru.author_val_label.text()
    tg_ru = dlg_ru.tg_label.text()
    email_ru = dlg_ru.email_label.text()

    set_language("en")
    dlg_en = AboutDialog()
    author_en = dlg_en.author_val_label.text()
    tg_en = dlg_en.tg_label.text()
    email_en = dlg_en.email_label.text()

    assert author_ru == author_en == "Кульдеев Вадим Алексеевич"
    assert tg_ru == tg_en
    assert email_ru == email_en


def test_46_about_dialog_close_button_ru_en(qapp):
    """46. Кнопка закрытия AboutDialog переводится."""
    set_language("ru")
    dlg_ru = AboutDialog()
    assert dlg_ru.close_btn.text() == "Закрыть"

    set_language("en")
    dlg_en = AboutDialog()
    assert dlg_en.close_btn.text() == "Close"


# =============================================================================
# РАЗДЕЛ 49: ЛОКАЛИЗАЦИЯ ОШИБОК ВАЛИДАЦИИ (Validation Errors)
# =============================================================================

def test_47_dd_empty_coordinate_error_ru_en():
    """47. Ошибка пустой координаты DD локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        CoordinateValidator.parse_dd("")
    assert "не может быть пустым" in str(exc_ru.value)
    assert exc_ru.value.localized_message("en") == "Coordinate value cannot be empty"


def test_48_dd_invalid_number_error_ru_en():
    """48. Ошибка нечислового формата DD локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        CoordinateValidator.parse_dd("abc")
    assert "Некорректный формат числа" in str(exc_ru.value)
    assert "Invalid number format: 'abc'" == exc_ru.value.localized_message("en")


def test_49_dd_lat_range_error_ru_en():
    """49. Ошибка диапазона широты DD локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        CoordinateValidator.validate_latitude(95.5)
    assert "Широта должна находиться в диапазоне от -90 до 90" in str(exc_ru.value)
    assert "Latitude must be between -90 and 90 degrees" in exc_ru.value.localized_message("en")


def test_50_dd_lon_range_error_ru_en():
    """50. Ошибка диапазона долготы DD локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        CoordinateValidator.validate_longitude(-190.0)
    assert "Долгота должна находиться в диапазоне от -180 до 180" in str(exc_ru.value)
    assert "Longitude must be between -180 and 180 degrees" in exc_ru.value.localized_message("en")


def test_51_dms_empty_field_error_ru_en():
    """51. Ошибка незаполненного поля DMS локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        CoordinateValidator.validate_dms_latitude("", "10", "10", "N")
    assert "Введите" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        CoordinateValidator.validate_dms_latitude("", "10", "10", "N")
    assert "Enter" in str(exc_en.value) and "For zero specify 0" in str(exc_en.value)


def test_52_dms_int_error_ru_en():
    """52. Ошибка нецелого значения градусов DMS локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        CoordinateValidator.validate_dms_latitude("56.5", "10", "10", "N")
    assert "должны быть целым числом" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        CoordinateValidator.validate_dms_latitude("56.5", "10", "10", "N")
    assert "must be an integer" in str(exc_en.value)


def test_53_dms_seconds_number_error_ru_en():
    """53. Ошибка нечисловых секунд DMS локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        CoordinateValidator.validate_dms_latitude("56", "10", "xyz", "N")
    assert "Секунды" in str(exc_ru.value) and "должны быть числом" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        CoordinateValidator.validate_dms_latitude("56", "10", "xyz", "N")
    assert "Seconds" in str(exc_en.value) and "must be a number" in str(exc_en.value)


def test_54_dms_lat_range_error_ru_en():
    """54. Ошибка диапазона градусов широты DMS локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        CoordinateValidator.validate_dms_latitude("95", "0", "0", "N")
    assert "Градусы широты должны быть от 0 до 90" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        CoordinateValidator.validate_dms_latitude("95", "0", "0", "N")
    assert "Latitude degrees must be between 0 and 90" in str(exc_en.value)


def test_55_dms_direction_error_ru_en():
    """55. Ошибка направления DMS (N/S или E/W) локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        CoordinateValidator.validate_dms_latitude("56", "0", "0", "X")
    assert "допустимы только направления N и S" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        CoordinateValidator.validate_dms_latitude("56", "0", "0", "X")
    assert "Only N and S directions are valid" in str(exc_en.value)


def test_56_style_symbol_error_ru_en():
    """56. Ошибка недопустимой формы маркера локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        StyleValidator.validate_symbol("star")
    assert "Недопустимая форма маркера" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        StyleValidator.validate_symbol("star")
    assert "Invalid marker shape" in str(exc_en.value)


def test_57_style_size_range_error_ru_en():
    """57. Ошибка диапазона размера маркера локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        StyleValidator.validate_size(2.0)
    assert "Размер маркера должен быть в диапазоне от 4.0 до 50.0 px" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        StyleValidator.validate_size(100.0)
    assert "must be in range from 4.0 to 50.0 px" in str(exc_en.value)


def test_58_style_rgb_range_error_ru_en():
    """58. Ошибка диапазона компонент цвета RGB локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        StyleValidator.validate_rgb_component(300, "R")
    assert "в диапазоне от 0 до 255" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        StyleValidator.validate_rgb_component(-10, "B")
    assert "must be in range from 0 to 255" in str(exc_en.value)


def test_59_zone_radius_range_error_ru_en():
    """59. Ошибка диапазона радиуса геодезической зоны локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        StyleValidator.validate_radius(0.0)
    assert "Радиус зоны должен" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        StyleValidator.validate_radius(2_000_000.0)
    assert "Zone radius must be in range from 1 m to 1 000 000 m" in str(exc_en.value)


def test_60_zone_opacity_range_error_ru_en():
    """60. Ошибка диапазона непрозрачности зоны локализована."""
    set_language("ru")
    with pytest.raises(ValidationError) as exc_ru:
        StyleValidator.validate_opacity(150)
    assert "Прозрачность зоны должна быть в диапазоне от 0% до 100%" in str(exc_ru.value)

    set_language("en")
    with pytest.raises(ValidationError) as exc_en:
        StyleValidator.validate_opacity(-5)
    assert "Zone opacity must be in range from 0% to 100%" in str(exc_en.value)


def test_61_validation_error_inherits_value_error():
    """61. ValidationError является подклассом ValueError (обратная совместимость)."""
    err = ValidationError("val.coord.empty_coord")
    assert isinstance(err, ValueError)


def test_62_validation_error_str_uses_active_language():
    """62. str(ValidationError) автоматически реагирует на текущий активный язык."""
    err = ValidationError("val.coord.empty_coord")
    set_language("ru")
    assert str(err) == "Значение координаты не может быть пустым"

    set_language("en")
    assert str(err) == "Coordinate value cannot be empty"


# =============================================================================
# РАЗДЕЛ 50: НЕЗАВИСИМОСТЬ ПОЛЬЗОВАТЕЛЬСКИХ ДАННЫХ (Data Independence)
# =============================================================================

def test_63_internal_symbol_model_code_independent():
    """63. Внутренний код формы в MapPoint всегда 'circle', 'square', 'triangle'."""
    pt = MapPoint(name="P", latitude=56.0, longitude=47.0, symbol="triangle")
    set_language("ru")
    assert pt.symbol == "triangle"
    set_language("en")
    assert pt.symbol == "triangle"


def test_64_point_name_never_translated():
    """64. Пользовательское имя точки не изменяется при смене языка."""
    pt = MapPoint(name="Моя особенная точка", latitude=56.0, longitude=47.0)
    set_language("en")
    assert pt.name == "Моя особенная точка"
    set_language("ru")
    assert pt.name == "Моя особенная точка"


def test_65_coordinates_numeric_integrity():
    """65. Числовые координаты не подвергаются языковой модификации."""
    pt = MapPoint(name="P", latitude=56.123456, longitude=47.987654)
    assert isinstance(pt.latitude, float)
    assert isinstance(pt.longitude, float)
    set_language("en")
    assert pt.latitude == 56.123456
    assert pt.longitude == 47.987654


def test_66_geopackage_layer_names_unmodified():
    """66. Идентификаторы и исходные имена слоев карты не переводятся."""
    layer = MapLayer(
        id="boundary",
        source_name="mari_el_boundary",
        display_name="Граница",
        geometry_type="Polygon",
        crs="EPSG:4326",
        role=LayerRole.BOUNDARY,
    )
    set_language("en")
    assert layer.id == "boundary"
    assert layer.source_name == "mari_el_boundary"


def test_67_map_profile_data_unmodified():
    """67. Данные MapProfile сохраняют свои оригинальные значения."""
    from rme_mapper.models.map_profile import MapProfile
    prof = MapProfile(id="prof1", name="Республика Марий Эл", source_path="test.gpkg", crs="EPSG:4326")
    set_language("en")
    assert prof.id == "prof1"
    assert prof.name == "Республика Марий Эл"


def test_68_geodesic_calculations_independent_of_language():
    """68. Геодезические вычисления окружности зоны идентичны независимо от языка."""
    set_language("ru")
    geom_ru = GeodesicService.create_geodesic_circle(47.88, 56.63, 1000.0)

    set_language("en")
    geom_en = GeodesicService.create_geodesic_circle(47.88, 56.63, 1000.0)

    assert geom_ru.equals(geom_en)


# =============================================================================
# РАЗДЕЛ 51: ДИНАМИЧЕСКОЕ ПЕРЕКЛЮЧЕНИЕ 'НА ЛЕТУ' (Live Dynamic Switching)
# =============================================================================

def test_69_dynamic_switch_ru_to_en_main_window(qapp):
    """69. Динамическое переключение RU -> EN в реальном времени без перезапуска."""
    win = MainWindow()
    win.switch_language("ru")
    assert win.file_menu.title() == "Файл"
    assert win.windowTitle() == "GeoPoint Mapper — Без имени"

    win.switch_language("en")
    assert win.file_menu.title() == "File"
    assert win.windowTitle() == "GeoPoint Mapper — Untitled"
    win.close()


def test_70_dynamic_switch_en_to_ru_main_window(qapp):
    """70. Динамическое переключение EN -> RU возвращает все тексты обратно."""
    win = MainWindow()
    win.switch_language("en")
    assert win.file_menu.title() == "File"

    win.switch_language("ru")
    assert win.file_menu.title() == "Файл"
    assert win.windowTitle() == "GeoPoint Mapper — Без имени"
    win.close()


def test_71_map_remains_loaded_after_language_switch(qapp, tmp_path):
    """71. Загруженная карта остается активной после переключения языка."""
    from rme_mapper.models.map_profile import MapProfile
    win = MainWindow()

    prof = MapProfile(
        id="test_map",
        name="Тестовая Карта",
        source_path=str(tmp_path / "dummy.gpkg"),
        crs="EPSG:4326",
    )
    win._active_profile = prof
    win.retranslate_ui()

    win.switch_language("en")
    assert win._active_profile is not None
    assert win._active_profile.id == "test_map"
    assert "Map: Тестовая Карта" in win.map_title_label.text()

    win.switch_language("ru")
    assert "Карта: Тестовая Карта" in win.map_title_label.text()
    win.close()


def test_72_points_and_zones_remain_intact_after_switch(qapp):
    """72. Добавленные точки и зоны сохраняются при многократном переключении языка."""
    win = MainWindow()
    pt = win._point_service.add_point(
        name="Точка Альфа",
        latitude=56.63,
        longitude=47.88,
        symbol="triangle",
        zone_enabled=True,
        radius_m=1500.0,
    )
    win._add_point_to_table(pt)

    assert win.points_table.rowCount() == 1
    assert len(win._point_service) == 1

    win.switch_language("en")
    assert win.points_table.rowCount() == 1
    assert len(win._point_service) == 1
    assert win.points_table.item(0, 1).text() == "Точка Альфа"
    assert win.points_table.item(0, 4).text() == "Triangle"
    assert win.points_table.item(0, 5).text() == "1.5 km"

    win.switch_language("ru")
    assert win.points_table.rowCount() == 1
    assert len(win._point_service) == 1
    assert win.points_table.item(0, 1).text() == "Точка Альфа"
    assert win.points_table.item(0, 4).text() == "Треугольник"
    assert win.points_table.item(0, 5).text() == "1.5 км"
    win.close()


def test_73_is_modified_flag_not_dirtied_by_language_switch(qapp):
    """73. Многократное переключение языка не изменяет статус сохранения проекта."""
    win = MainWindow()
    win._set_modified(False)

    for lang in ["en", "ru", "en", "ru"]:
        win.switch_language(lang)
        assert not win.is_modified

    win.close()


def test_74_current_project_path_preserved_after_switch(qapp):
    """74. Текущий путь к проекту сохраняется неизменным после смены языка."""
    win = MainWindow()
    target_path = Path("D:/Maps/Project2026.gpmap")
    win._current_project_path = target_path

    win.switch_language("en")
    assert win.current_project_path == target_path
    win.switch_language("ru")
    assert win.current_project_path == target_path
    win.close()


def test_75_repeated_language_switches_idempotent_no_leaks(qapp):
    """75. 10 циклов переключения языков подряд идемпотентны и не создают дубликатов действий."""
    win = MainWindow()
    file_actions_count = len(win.file_menu.actions())

    for _ in range(10):
        win.switch_language("en")
        win.switch_language("ru")

    assert len(win.file_menu.actions()) == file_actions_count
    assert win.lang_ru_action.isChecked()
    assert not win.lang_en_action.isChecked()
    win.close()
