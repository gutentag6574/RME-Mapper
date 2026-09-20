"""Тесты верификации технической уборки после Этапа 17.

Проверяет:
- Публичное имя приложения (GeoPoint Mapper) и метаданные;
- Drag & Drop табличных файлов (.xlsx, .csv, .txt) открывает ImportWizard, а не старый ImportDialog;
- Наличие и работоспособность устаревшего метода open_import_dialog для обратной совместимости;
- Целостность зависимостей (numpy, pyogrio, rasterio);
- Наличие единого источника истины docs/CURRENT_PLAN.md и архива устаревшей документации.
"""

from pathlib import Path
import openpyxl
import pytest
from PySide6.QtCore import QMimeData, QPointF, QUrl
from PySide6.QtGui import QDropEvent

from PySide6.QtWidgets import QApplication

from rme_mapper.app_info import APP_NAME, APP_VERSION
from rme_mapper.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class DummyDropEvent:
    """Имитация QDropEvent для проверки механизма Drag & Drop главного окна."""

    def __init__(self, file_path: Path):
        self._path = file_path
        self._accepted = False

    def mimeData(self):
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self._path))])
        return mime

    def acceptProposedAction(self):
        self._accepted = True

    def ignore(self):
        self._accepted = False

    def isAccepted(self):
        return self._accepted


def test_public_application_name_and_metadata(qapp):
    """Публичное имя приложения строго 'GeoPoint Mapper', версия '0.12.0'."""
    assert APP_NAME == "GeoPoint Mapper"
    assert APP_VERSION == "0.12.0"

    win = MainWindow()
    assert "GeoPoint Mapper" in win.windowTitle()
    win.close()


@pytest.mark.parametrize("ext", [".xlsx", ".csv", ".txt"])
def test_drag_and_drop_opens_import_wizard(qapp, tmp_path, monkeypatch, ext):
    """Drag & Drop файлов .xlsx, .csv, .txt вызывает open_import_wizard (а не старый ImportDialog)."""
    win = MainWindow()
    test_file = tmp_path / f"test_data{ext}"
    if ext == ".xlsx":
        wb = openpyxl.Workbook()
        wb.save(str(test_file))
        wb.close()
    else:
        test_file.write_text("name,lat,lon\nP1,56.0,47.0\n", encoding="utf-8")

    wizard_calls = []
    dialog_calls = []

    monkeypatch.setattr(
        win.import_controller,
        "open_import_wizard",
        lambda path: wizard_calls.append(path),
    )
    monkeypatch.setattr(
        win.import_controller,
        "open_import_dialog",
        lambda path: dialog_calls.append(path),
    )

    ev = DummyDropEvent(test_file)
    win.dropEvent(ev)

    assert ev.isAccepted() is True
    assert len(wizard_calls) == 1
    assert wizard_calls[0] == test_file
    assert len(dialog_calls) == 0, "Старый ImportDialog не должен вызываться при Drag & Drop!"
    win.close()


def test_legacy_import_dialog_api_remains_available(qapp, monkeypatch):
    """Метод open_import_dialog сохранен на контроллере как deprecated API."""
    win = MainWindow()
    assert hasattr(win.import_controller, "open_import_dialog")
    assert callable(win.import_controller.open_import_dialog)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *args, **kwargs: None)
    # При отсутствии карты метод безопасно возвращает False
    res = win.import_controller.open_import_dialog()
    assert res is False
    win.close()


def test_production_dependencies_importable():
    """Все заявленные runtime-зависимости успешно импортируются."""
    import numpy
    import pyogrio
    import rasterio

    assert numpy is not None
    assert pyogrio is not None
    assert rasterio is not None


def test_documentation_structure_integrity():
    """Проверка структуры документации: CURRENT_PLAN.md активен, legacy в архиве."""
    repo_root = Path(__file__).resolve().parent.parent
    current_plan = repo_root / "docs" / "CURRENT_PLAN.md"
    assert current_plan.exists(), "docs/CURRENT_PLAN.md должен существовать как источник истины"
    plan_text = current_plan.read_text(encoding="utf-8")
    assert "GeoPoint Mapper" in plan_text
    assert "17" in plan_text
    assert "18" in plan_text

    legacy_dir = repo_root / "docs" / "archive" / "legacy"
    assert legacy_dir.is_dir(), "Каталог docs/archive/legacy должен существовать"
    assert (legacy_dir / "README.md").exists()
    assert (legacy_dir / "TZ.md").exists()
    assert (legacy_dir / "DEVELOPMENT_PLAN.md").exists()
    assert (legacy_dir / "OPEN_QUESTIONS.md").exists()

    # Проверка отсутствия старых файлов в корне docs
    assert not (repo_root / "docs" / "TZ.md").exists()
    assert not (repo_root / "docs" / "DEVELOPMENT_PLAN.md").exists()
    assert not (repo_root / "docs" / "OPEN_QUESTIONS.md").exists()

    # Проверка удаления пустого test_data
    assert not (repo_root / "test_data").exists(), "Пустой каталог test_data/ должен быть удален"
