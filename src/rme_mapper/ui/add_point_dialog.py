"""Диалоговое окно ручного добавления точки в формате десятичных градусов (DD)."""

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.coordinates.validator import CoordinateValidator
from rme_mapper.services.coordinate_service import CoordinateService

logger = logging.getLogger("rme_mapper.ui.add_point_dialog")


class AddPointDialog(QDialog):
    """Диалог ввода параметров пользовательской точки."""

    def __init__(
        self,
        parent: QWidget | None = None,
        boundary_geometry: Any = None,
        default_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Добавить точку")
        self.setModal(True)
        self.resize(360, 200)

        self._boundary_geometry = boundary_geometry
        self._parsed_data: tuple[str, float, float] | None = None

        self._setup_ui(default_name)

    def _setup_ui(self, default_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("pointNameEdit")
        self.name_edit.setPlaceholderText(default_name or "Название (опционально)")
        form_layout.addRow("Название:", self.name_edit)

        self.lat_edit = QLineEdit(self)
        self.lat_edit.setObjectName("pointLatEdit")
        self.lat_edit.setPlaceholderText("Пример: 56.637 или 56,637")
        form_layout.addRow("Широта (DD):", self.lat_edit)

        self.lon_edit = QLineEdit(self)
        self.lon_edit.setObjectName("pointLonEdit")
        self.lon_edit.setPlaceholderText("Пример: 47.886 или 47,886")
        form_layout.addRow("Долгота (DD):", self.lon_edit)

        layout.addLayout(form_layout)

        # Сообщение с подсказкой диапазона
        hint_label = QLabel("Диапазон: широта [-90; 90], долгота [-180; 180]")
        hint_label.setStyleSheet("color: #777777; font-size: 11px;")
        layout.addWidget(hint_label)

        # Кнопки диалога
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_add = QPushButton("Добавить", self)
        self.btn_add.setObjectName("btnAddPointSubmit")
        self.btn_add.setDefault(True)
        self.btn_add.clicked.connect(self._validate_and_submit)
        btn_layout.addWidget(self.btn_add)

        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_cancel.setObjectName("btnAddPointCancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def _validate_and_submit(self) -> None:
        """Проверка ввода, валидация координат и проверка выхода за пределы РМЭ."""
        lat_text = self.lat_edit.text()
        lon_text = self.lon_edit.text()

        try:
            lat, lon = CoordinateValidator.validate_dd_pair(lat_text, lon_text)
        except ValueError as err:
            logger.warning("Ошибка валидации координат: %s", err)
            QMessageBox.warning(
                self,
                "Некорректные координаты",
                f"Ошибка в формате координат:\n{err}",
            )
            return

        name = self.name_edit.text().strip()

        # Проверка выхода за границу РМЭ
        if self._boundary_geometry is not None:
            is_inside = CoordinateService.is_point_inside_boundary(
                longitude=lon,
                latitude=lat,
                boundary_geometry=self._boundary_geometry,
            )
            if not is_inside:
                logger.info("Введенная точка (%s, %s) вне границы РМЭ", lon, lat)
                reply = QMessageBox.question(
                    self,
                    "Предупреждение",
                    "Координата находится за пределами Республики Марий Эл.\nДобавить точку?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        self._parsed_data = (name, lat, lon)
        self.accept()

    def get_point_data(self) -> tuple[str, float, float] | None:
        """Возвращает кортеж (name, latitude, longitude) после успешного завершения."""
        return self._parsed_data
