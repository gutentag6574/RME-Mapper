"""Диалоговое окно ручного добавления точки в формате DD или DMS."""

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.coordinates.validator import CoordinateValidator
from rme_mapper.services.coordinate_service import CoordinateService

logger = logging.getLogger("rme_mapper.ui.add_point_dialog")


class AddPointDialog(QDialog):
    """Диалог ввода параметров пользовательской точки с поддержкой DD и DMS."""

    def __init__(
        self,
        parent: QWidget | None = None,
        boundary_geometry: Any = None,
        default_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Добавить точку")
        self.setModal(True)
        self.resize(440, 300)

        self._boundary_geometry = boundary_geometry
        self._parsed_data: tuple[str, float, float] | None = None

        self._setup_ui(default_name)

    def _setup_ui(self, default_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Поле названия точки
        name_layout = QHBoxLayout()
        name_label = QLabel("Название:", self)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("pointNameEdit")
        self.name_edit.setPlaceholderText(default_name or "Название (опционально)")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)

        # Выбор формата координат
        format_group_box = QGroupBox("Формат координат", self)
        format_layout = QHBoxLayout(format_group_box)
        self.rb_dd = QRadioButton("Десятичные градусы (DD)", format_group_box)
        self.rb_dd.setObjectName("rbFormatDD")
        self.rb_dd.setChecked(True)

        self.rb_dms = QRadioButton("Градусы / минуты / секунды (DMS)", format_group_box)
        self.rb_dms.setObjectName("rbFormatDMS")

        format_layout.addWidget(self.rb_dd)
        format_layout.addWidget(self.rb_dms)
        layout.addWidget(format_group_box)

        # QStackedWidget для страниц DD и DMS
        self.stack_widget = QStackedWidget(self)

        # --- Страница 0: Режим DD ---
        dd_widget = QWidget(self.stack_widget)
        dd_layout = QVBoxLayout(dd_widget)
        dd_layout.setContentsMargins(0, 0, 0, 0)
        dd_form = QFormLayout()
        dd_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.lat_edit = QLineEdit(dd_widget)
        self.lat_edit.setObjectName("pointLatEdit")
        self.lat_edit.setPlaceholderText("Пример: 56.637 или 56,637")
        dd_form.addRow("Широта (DD):", self.lat_edit)

        self.lon_edit = QLineEdit(dd_widget)
        self.lon_edit.setObjectName("pointLonEdit")
        self.lon_edit.setPlaceholderText("Пример: 47.886 или 47,886")
        dd_form.addRow("Долгота (DD):", self.lon_edit)

        dd_hint = QLabel("Диапазон: широта [-90; 90], долгота [-180; 180]", dd_widget)
        dd_hint.setStyleSheet("color: #777777; font-size: 11px;")

        dd_layout.addLayout(dd_form)
        dd_layout.addWidget(dd_hint)
        self.stack_widget.addWidget(dd_widget)

        # --- Страница 1: Режим DMS ---
        dms_widget = QWidget(self.stack_widget)
        dms_layout = QVBoxLayout(dms_widget)
        dms_layout.setContentsMargins(0, 0, 0, 0)

        # Сетка ввода DMS
        dms_grid = QGridLayout()
        dms_grid.setSpacing(6)

        # Заголовки колонок
        dms_grid.addWidget(QLabel(""), 0, 0)
        dms_grid.addWidget(QLabel("Градусы"), 0, 1)
        dms_grid.addWidget(QLabel("Минуты"), 0, 2)
        dms_grid.addWidget(QLabel("Секунды"), 0, 3)
        dms_grid.addWidget(QLabel("Напр."), 0, 4)

        # Широта (DMS)
        dms_grid.addWidget(QLabel("Широта:"), 1, 0)
        self.lat_deg_edit = QLineEdit(dms_widget)
        self.lat_deg_edit.setObjectName("pointLatDegEdit")
        self.lat_deg_edit.setPlaceholderText("0..90")
        dms_grid.addWidget(self.lat_deg_edit, 1, 1)

        self.lat_min_edit = QLineEdit(dms_widget)
        self.lat_min_edit.setObjectName("pointLatMinEdit")
        self.lat_min_edit.setPlaceholderText("0..59")
        dms_grid.addWidget(self.lat_min_edit, 1, 2)

        self.lat_sec_edit = QLineEdit(dms_widget)
        self.lat_sec_edit.setObjectName("pointLatSecEdit")
        self.lat_sec_edit.setPlaceholderText("0..59.9")
        dms_grid.addWidget(self.lat_sec_edit, 1, 3)

        self.lat_dir_combo = QComboBox(dms_widget)
        self.lat_dir_combo.setObjectName("pointLatDirCombo")
        self.lat_dir_combo.addItems(["N", "S"])
        dms_grid.addWidget(self.lat_dir_combo, 1, 4)

        # Долгота (DMS)
        dms_grid.addWidget(QLabel("Долгота:"), 2, 0)
        self.lon_deg_edit = QLineEdit(dms_widget)
        self.lon_deg_edit.setObjectName("pointLonDegEdit")
        self.lon_deg_edit.setPlaceholderText("0..180")
        dms_grid.addWidget(self.lon_deg_edit, 2, 1)

        self.lon_min_edit = QLineEdit(dms_widget)
        self.lon_min_edit.setObjectName("pointLonMinEdit")
        self.lon_min_edit.setPlaceholderText("0..59")
        dms_grid.addWidget(self.lon_min_edit, 2, 2)

        self.lon_sec_edit = QLineEdit(dms_widget)
        self.lon_sec_edit.setObjectName("pointLonSecEdit")
        self.lon_sec_edit.setPlaceholderText("0..59.9")
        dms_grid.addWidget(self.lon_sec_edit, 2, 3)

        self.lon_dir_combo = QComboBox(dms_widget)
        self.lon_dir_combo.setObjectName("pointLonDirCombo")
        self.lon_dir_combo.addItems(["E", "W"])
        dms_grid.addWidget(self.lon_dir_combo, 2, 4)

        dms_hint = QLabel(
            "Широта: 0..90° [N/S], Долгота: 0..180° [E/W]. Секунды поддерживают 15.2 и 15,2.",
            dms_widget,
        )
        dms_hint.setStyleSheet("color: #777777; font-size: 11px;")

        dms_layout.addLayout(dms_grid)
        dms_layout.addWidget(dms_hint)
        self.stack_widget.addWidget(dms_widget)

        layout.addWidget(self.stack_widget)

        # Переключение форматов
        self.rb_dd.toggled.connect(self._on_format_changed)

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

    def _on_format_changed(self, is_dd_checked: bool) -> None:
        """Переключение отображаемой формы ввода координат (DD или DMS)."""
        if is_dd_checked:
            self.stack_widget.setCurrentIndex(0)
        else:
            self.stack_widget.setCurrentIndex(1)

    def _validate_and_submit(self) -> None:
        """Проверка ввода, валидация координат и проверка выхода за пределы РМЭ."""
        if self.rb_dd.isChecked():
            lat_text = self.lat_edit.text()
            lon_text = self.lon_edit.text()
            try:
                lat, lon = CoordinateValidator.validate_dd_pair(lat_text, lon_text)
            except ValueError as err:
                logger.warning("Ошибка валидации координат DD: %s", err)
                QMessageBox.warning(
                    self,
                    "Некорректные координаты",
                    f"Ошибка в формате координат:\n{err}",
                )
                return
        else:
            lat_deg = self.lat_deg_edit.text()
            lat_min = self.lat_min_edit.text()
            lat_sec = self.lat_sec_edit.text()
            lat_dir = self.lat_dir_combo.currentText()

            lon_deg = self.lon_deg_edit.text()
            lon_min = self.lon_min_edit.text()
            lon_sec = self.lon_sec_edit.text()
            lon_dir = self.lon_dir_combo.currentText()

            try:
                lat, lon = CoordinateValidator.validate_dms_pair(
                    (lat_deg, lat_min, lat_sec, lat_dir),
                    (lon_deg, lon_min, lon_sec, lon_dir),
                )
            except ValueError as err:
                logger.warning("Ошибка валидации координат DMS: %s", err)
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

