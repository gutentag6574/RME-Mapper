"""Тесты пользовательского интерфейса диалога геопривязки (Stage 21)."""

from pathlib import Path
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox
import pytest

from rme_mapper.models.georeference import ControlPoint
from rme_mapper.ui.georeference_dialog import GeoreferenceDialog


@pytest.fixture(scope="session")
def qapp():
    """Фикстура для инициализации QApplication."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def sample_image_path(tmp_path: Path) -> Path:
    """Создание тестового растрового изображения."""
    p = tmp_path / "dialog_test_raster.png"
    img = Image.new("RGBA", (300, 200), color=(120, 180, 240, 255))
    img.save(p, format="PNG")
    return p


class TestGeoreferenceDialog:
    """Тестирование функционала диалога ручной геопривязки GeoreferenceDialog."""

    def test_dialog_initial_state_empty(self, qapp, sample_image_path: Path):
        """Проверка начального состояния диалога без контрольных точек."""
        dialog = GeoreferenceDialog(image_path=sample_image_path)
        assert dialog.points_table.rowCount() == 0
        assert dialog.btn_apply.isEnabled() is False
        assert "—" in dialog.lbl_rmse.text() or "-" in dialog.lbl_rmse.text()
        assert dialog._image_info["width"] == 300
        assert dialog._image_info["height"] == 200
        dialog.close()

    def test_dialog_with_existing_points(self, qapp, sample_image_path: Path):
        """Проверка инициализации диалога с готовым набором точек."""
        existing = [
            ControlPoint("1", pixel_x=10.0, pixel_y=10.0, target_x=100.0, target_y=200.0),
            ControlPoint("2", pixel_x=100.0, pixel_y=10.0, target_x=200.0, target_y=200.0),
            ControlPoint("3", pixel_x=10.0, pixel_y=100.0, target_x=100.0, target_y=100.0),
        ]
        dialog = GeoreferenceDialog(
            image_path=sample_image_path,
            existing_points=existing,
            existing_crs="EPSG:3857",
        )
        assert dialog.points_table.rowCount() == 3
        # При 3 корректных точках трансформация должна быть рассчитана, а кнопка "Применить" активна
        assert dialog._current_affine is not None
        assert dialog.btn_apply.isEnabled() is True
        dialog.close()

    def test_add_points_and_recalculate(self, qapp, sample_image_path: Path):
        """Добавление точек и проверка автоматического пересчета аффинной матрицы."""
        dialog = GeoreferenceDialog(image_path=sample_image_path, existing_crs="EPSG:3857")

        # Добавляем точку 1
        dialog._on_point_placed_on_image(0.0, 0.0)
        assert dialog.points_table.rowCount() == 1
        assert dialog.btn_apply.isEnabled() is False

        # Добавляем точку 2
        dialog._on_point_placed_on_image(100.0, 0.0)
        assert dialog.points_table.rowCount() == 2
        assert dialog.btn_apply.isEnabled() is False

        # Задаем целевые координаты точек 1 и 2
        dialog._control_points[0].target_x = 0.0
        dialog._control_points[0].target_y = 0.0
        dialog._control_points[1].target_x = 100.0
        dialog._control_points[1].target_y = 0.0

        # Добавляем точку 3
        dialog._on_point_placed_on_image(0.0, 100.0)
        dialog._control_points[2].target_x = 0.0
        dialog._control_points[2].target_y = -100.0

        # Пересчитываем
        dialog._recalculate()
        assert dialog.btn_apply.isEnabled() is True
        assert dialog._current_affine is not None
        assert pytest.approx(dialog._current_rmse, abs=1e-5) == 0.0
        dialog.close()

    def test_disable_and_enable_point(self, qapp, sample_image_path: Path):
        """Отключение точки через чекбокс и влияние на доступность кнопки 'Применить'."""
        existing = [
            ControlPoint("1", pixel_x=10.0, pixel_y=10.0, target_x=100.0, target_y=200.0),
            ControlPoint("2", pixel_x=100.0, pixel_y=10.0, target_x=200.0, target_y=200.0),
            ControlPoint("3", pixel_x=10.0, pixel_y=100.0, target_x=100.0, target_y=100.0),
        ]
        dialog = GeoreferenceDialog(image_path=sample_image_path, existing_points=existing, existing_crs="EPSG:3857")
        assert dialog.btn_apply.isEnabled() is True

        # Отключаем первую точку (активных остается 2 < 3)
        cell_w = dialog.points_table.cellWidget(0, 6)
        assert cell_w is not None
        chk = cell_w.findChild(QCheckBox)
        assert chk is not None

        chk.setChecked(False)
        assert dialog._control_points[0].enabled is False
        assert dialog.btn_apply.isEnabled() is False

        # Включаем обратно
        chk.setChecked(True)
        assert dialog._control_points[0].enabled is True
        assert dialog.btn_apply.isEnabled() is True
        dialog.close()

    def test_delete_point(self, qapp, sample_image_path: Path):
        """Удаление точки из таблицы."""
        existing = [
            ControlPoint("1", pixel_x=10.0, pixel_y=10.0, target_x=100.0, target_y=200.0),
            ControlPoint("2", pixel_x=100.0, pixel_y=10.0, target_x=200.0, target_y=200.0),
            ControlPoint("3", pixel_x=10.0, pixel_y=100.0, target_x=100.0, target_y=100.0),
        ]
        dialog = GeoreferenceDialog(image_path=sample_image_path, existing_points=existing, existing_crs="EPSG:3857")
        assert dialog.points_table.rowCount() == 3

        # Выбираем строку 1 и удаляем
        dialog.points_table.selectRow(1)
        dialog._on_delete_selected_point()
        assert dialog.points_table.rowCount() == 2
        assert dialog.btn_apply.isEnabled() is False
        dialog.close()
