"""Диалоговое окно создания и редактирования пользовательской точки (DD / DMS, стиль, цвет, географическая зона)."""

import logging
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.coordinates.validator import CoordinateValidator
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import PointStyle, PointZoneStyle, StyleValidator
from rme_mapper.services.coordinate_service import CoordinateService
from rme_mapper.services.geodesic_service import GeodesicService

logger = logging.getLogger("rme_mapper.ui.point_dialog")


def decimal_to_dms(val: float) -> tuple[int, int, float]:
    """Разбиение десятичного градуса на градусы, минуты и секунды."""
    abs_val = abs(val)
    deg = int(abs_val)
    rem = (abs_val - deg) * 60.0
    mn = int(rem)
    sec = round((rem - mn) * 60.0, 3)
    if sec >= 60.0:
        sec = 0.0
        mn += 1
    if mn >= 60:
        mn = 0
        deg += 1
    return deg, mn, sec


class MarkerPreviewWidget(QWidget):
    """Виджет интерактивного предпросмотра маркера точки."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.symbol: str = "circle"
        self.size_val: float = 12.0
        self.red: int = 220
        self.green: int = 30
        self.blue: int = 30

    def update_style(self, symbol: str, size: float, red: int, green: int, blue: int) -> None:
        """Обновление параметров и перерисовка предпросмотра."""
        self.symbol = symbol
        self.size_val = size
        self.red = red
        self.green = green
        self.blue = blue
        self.update()

    def paintEvent(self, event: Any) -> None:
        """Отрисовка маркера по центру виджета."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Фоновая рамка предпросмотра
        painter.fillRect(self.rect(), QColor("#F8F9FA"))
        painter.setPen(QPen(QColor("#CCCCCC"), 1))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

        center_x = self.width() / 2.0
        center_y = self.height() / 2.0

        path = MapCanvas._create_marker_path(self.symbol, min(self.size_val, 48.0))

        painter.save()
        painter.translate(center_x, center_y)

        pen = QPen(QColor("#FFFFFF"), 1.5)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(self.red, self.green, self.blue)))
        painter.drawPath(path)
        painter.restore()


@dataclass
class PointDialogData:
    """Результат работы диалога точки."""

    name: str
    latitude: float
    longitude: float
    symbol: str = "circle"
    size: float = 12.0
    red: int = 220
    green: int = 30
    blue: int = 30
    zone_enabled: bool = False
    radius_m: float = 0.0
    zone_red: int = 220
    zone_green: int = 30
    zone_blue: int = 30
    zone_opacity: int = 30

    def __getitem__(self, index: int) -> Any:
        return (
            self.name,
            self.latitude,
            self.longitude,
            self.symbol,
            self.size,
            self.red,
            self.green,
            self.blue,
            self.zone_enabled,
            self.radius_m,
            self.zone_red,
            self.zone_green,
            self.zone_blue,
            self.zone_opacity,
        )[index]

    def __len__(self) -> int:
        return 14


class PointDialog(QDialog):
    """Универсальный диалог создания (CREATE) и редактирования (EDIT) точки."""

    def __init__(
        self,
        parent: QWidget | None = None,
        boundary_geometry: Any = None,
        default_name: str = "",
        point: MapPoint | None = None,
        mode: str = "CREATE",
    ) -> None:
        super().__init__(parent)
        self._boundary_geometry = boundary_geometry
        self._point = point
        self.mode = "EDIT" if point is not None else mode.upper()
        self._parsed_data: PointDialogData | None = None

        if self.mode == "EDIT":
            self.setWindowTitle("Редактировать точку")
        else:
            self.setWindowTitle("Добавить точку")

        self.setModal(True)
        self.resize(500, 540)

        self._setup_ui(default_name)
        if self._point:
            self._populate_fields_from_point(self._point)

    def _setup_ui(self, default_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # 1. Поле названия точки
        name_layout = QHBoxLayout()
        name_label = QLabel("Название:", self)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("pointNameEdit")
        self.name_edit.setPlaceholderText(default_name or "Название (опционально)")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)

        # 2. Выбор формата координат
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

        dms_grid = QGridLayout()
        dms_grid.setSpacing(6)

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
            "Широта: 0..90° [N/S], Долгота: 0..180° [E/W]. Поддерживаются 15.2 и 15,2.",
            dms_widget,
        )
        dms_hint.setStyleSheet("color: #777777; font-size: 11px;")

        dms_layout.addLayout(dms_grid)
        dms_layout.addWidget(dms_hint)
        self.stack_widget.addWidget(dms_widget)

        layout.addWidget(self.stack_widget)
        self.rb_dd.toggled.connect(self._on_format_changed)

        # 3. Блок стиля маркера
        style_box = QGroupBox("Стиль маркера", self)
        style_main_layout = QHBoxLayout(style_box)

        style_form = QFormLayout()
        style_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.symbol_combo = QComboBox(style_box)
        self.symbol_combo.setObjectName("pointSymbolCombo")
        self.symbol_combo.addItem("Круг", "circle")
        self.symbol_combo.addItem("Квадрат", "square")
        self.symbol_combo.addItem("Треугольник", "triangle")
        self.symbol_combo.currentIndexChanged.connect(self._on_style_input_changed)
        style_form.addRow("Форма:", self.symbol_combo)

        self.size_spin = QDoubleSpinBox(style_box)
        self.size_spin.setObjectName("pointSizeSpin")
        self.size_spin.setRange(4.0, 50.0)
        self.size_spin.setValue(12.0)
        self.size_spin.setSingleStep(1.0)
        self.size_spin.setDecimals(1)
        self.size_spin.valueChanged.connect(self._on_style_input_changed)
        style_form.addRow("Размер (px):", self.size_spin)

        rgb_layout = QHBoxLayout()
        rgb_layout.setSpacing(4)

        rgb_layout.addWidget(QLabel("R:"))
        self.r_edit = QLineEdit(style_box)
        self.r_edit.setObjectName("pointREdit")
        self.r_edit.setText("220")
        self.r_edit.setMaximumWidth(42)
        self.r_edit.textChanged.connect(self._on_style_input_changed)
        rgb_layout.addWidget(self.r_edit)

        rgb_layout.addWidget(QLabel("G:"))
        self.g_edit = QLineEdit(style_box)
        self.g_edit.setObjectName("pointGEdit")
        self.g_edit.setText("30")
        self.g_edit.setMaximumWidth(42)
        self.g_edit.textChanged.connect(self._on_style_input_changed)
        rgb_layout.addWidget(self.g_edit)

        rgb_layout.addWidget(QLabel("B:"))
        self.b_edit = QLineEdit(style_box)
        self.b_edit.setObjectName("pointBEdit")
        self.b_edit.setText("30")
        self.b_edit.setMaximumWidth(42)
        self.b_edit.textChanged.connect(self._on_style_input_changed)
        rgb_layout.addWidget(self.b_edit)

        self.btn_pick_color = QPushButton("Выбрать цвет...", style_box)
        self.btn_pick_color.setObjectName("btnPickColor")
        self.btn_pick_color.clicked.connect(self._open_color_dialog)
        rgb_layout.addWidget(self.btn_pick_color)

        style_form.addRow("Цвет (RGB):", rgb_layout)
        style_main_layout.addLayout(style_form, stretch=1)

        preview_box = QVBoxLayout()
        preview_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_label = QLabel("Превью:")
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_box.addWidget(preview_label)

        self.preview_widget = MarkerPreviewWidget(style_box)
        self.preview_widget.setObjectName("markerPreviewWidget")
        preview_box.addWidget(self.preview_widget)
        style_main_layout.addLayout(preview_box)

        layout.addWidget(style_box)

        # 4. Блок географической зоны радиуса (Этап 7)
        zone_box = QGroupBox("Зона вокруг точки", self)
        zone_box_layout = QVBoxLayout(zone_box)
        zone_box_layout.setSpacing(6)

        # Чекбокс включения зоны
        self.zone_chk = QCheckBox("Показывать зону", zone_box)
        self.zone_chk.setObjectName("pointZoneEnableChk")
        zone_box_layout.addWidget(self.zone_chk)

        # Контейнер настроек параметров зоны
        self.zone_container = QWidget(zone_box)
        zone_form = QFormLayout(self.zone_container)
        zone_form.setContentsMargins(0, 0, 0, 0)
        zone_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Поле ввода радиуса и выбор единиц
        radius_layout = QHBoxLayout()
        self.zone_radius_edit = QLineEdit(self.zone_container)
        self.zone_radius_edit.setObjectName("pointZoneRadiusEdit")
        self.zone_radius_edit.setPlaceholderText("Например: 10 или 500")
        radius_layout.addWidget(self.zone_radius_edit, stretch=1)

        self.zone_unit_combo = QComboBox(self.zone_container)
        self.zone_unit_combo.setObjectName("pointZoneRadiusUnitCombo")
        self.zone_unit_combo.addItems(["км", "м"])
        radius_layout.addWidget(self.zone_unit_combo)
        zone_form.addRow("Радиус:", radius_layout)

        # Цвет зоны
        zone_rgb_layout = QHBoxLayout()
        zone_rgb_layout.setSpacing(4)

        zone_rgb_layout.addWidget(QLabel("R:"))
        self.zone_r_edit = QLineEdit(self.zone_container)
        self.zone_r_edit.setObjectName("pointZoneREdit")
        self.zone_r_edit.setText("220")
        self.zone_r_edit.setMaximumWidth(42)
        zone_rgb_layout.addWidget(self.zone_r_edit)

        zone_rgb_layout.addWidget(QLabel("G:"))
        self.zone_g_edit = QLineEdit(self.zone_container)
        self.zone_g_edit.setObjectName("pointZoneGEdit")
        self.zone_g_edit.setText("30")
        self.zone_g_edit.setMaximumWidth(42)
        zone_rgb_layout.addWidget(self.zone_g_edit)

        zone_rgb_layout.addWidget(QLabel("B:"))
        self.zone_b_edit = QLineEdit(self.zone_container)
        self.zone_b_edit.setObjectName("pointZoneBEdit")
        self.zone_b_edit.setText("30")
        self.zone_b_edit.setMaximumWidth(42)
        zone_rgb_layout.addWidget(self.zone_b_edit)

        self.btn_pick_zone_color = QPushButton("Выбрать цвет...", self.zone_container)
        self.btn_pick_zone_color.setObjectName("btnPickZoneColor")
        self.btn_pick_zone_color.clicked.connect(self._open_zone_color_dialog)
        zone_rgb_layout.addWidget(self.btn_pick_zone_color)
        zone_form.addRow("Цвет зоны:", zone_rgb_layout)

        # Прозрачность зоны (0..100%)
        opacity_layout = QHBoxLayout()
        self.zone_opacity_slider = QSlider(Qt.Orientation.Horizontal, self.zone_container)
        self.zone_opacity_slider.setObjectName("pointZoneOpacitySlider")
        self.zone_opacity_slider.setRange(0, 100)
        self.zone_opacity_slider.setValue(30)
        opacity_layout.addWidget(self.zone_opacity_slider, stretch=1)

        self.zone_opacity_spin = QSpinBox(self.zone_container)
        self.zone_opacity_spin.setObjectName("pointZoneOpacitySpin")
        self.zone_opacity_spin.setRange(0, 100)
        self.zone_opacity_spin.setValue(30)
        self.zone_opacity_spin.setSuffix("%")
        opacity_layout.addWidget(self.zone_opacity_spin)

        # Связка слайдера и спинбокса
        self.zone_opacity_slider.valueChanged.connect(self.zone_opacity_spin.setValue)
        self.zone_opacity_spin.valueChanged.connect(self.zone_opacity_slider.setValue)

        zone_form.addRow("Непрозрачность:", opacity_layout)

        zone_box_layout.addWidget(self.zone_container)
        layout.addWidget(zone_box)

        # Управление доступностью полей зоны по чекбоксу
        self.zone_container.setEnabled(False)
        self.zone_chk.toggled.connect(self.zone_container.setEnabled)

        # Псевдонимы атрибутов для тестов и обратной совместимости
        self.zone_group = zone_box
        self.zone_enabled_chk = self.zone_chk
        self.radius_edit = self.zone_radius_edit
        self.unit_combo = self.zone_unit_combo
        self.opacity_slider = self.zone_opacity_slider
        self.opacity_spin = self.zone_opacity_spin

        # Кнопки диалога
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        submit_text = "Сохранить" if self.mode == "EDIT" else "Добавить"
        self.btn_add = QPushButton(submit_text, self)
        self.btn_add.setObjectName("btnAddPointSubmit")
        self.btn_add.setDefault(True)
        self.btn_add.clicked.connect(self._validate_and_submit)
        btn_layout.addWidget(self.btn_add)

        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_cancel.setObjectName("btnAddPointCancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

        # Первоначальное обновление превью
        self._on_style_input_changed()

    def _populate_fields_from_point(self, point: MapPoint) -> None:
        """Заполнение полей диалога данными существующей точки."""
        self.name_edit.setText(point.name)
        self.lat_edit.setText(f"{point.latitude:.6f}")
        self.lon_edit.setText(f"{point.longitude:.6f}")

        # Заполнение DMS полей
        lat_deg, lat_min, lat_sec = decimal_to_dms(point.latitude)
        self.lat_deg_edit.setText(str(lat_deg))
        self.lat_min_edit.setText(str(lat_min))
        self.lat_sec_edit.setText(f"{lat_sec:.2f}".rstrip("0").rstrip("."))
        self.lat_dir_combo.setCurrentText("N" if point.latitude >= 0 else "S")

        lon_deg, lon_min, lon_sec = decimal_to_dms(point.longitude)
        self.lon_deg_edit.setText(str(lon_deg))
        self.lon_min_edit.setText(str(lon_min))
        self.lon_sec_edit.setText(f"{lon_sec:.2f}".rstrip("0").rstrip("."))
        self.lon_dir_combo.setCurrentText("E" if point.longitude >= 0 else "W")

        # Маркер
        idx = self.symbol_combo.findData(point.symbol)
        if idx >= 0:
            self.symbol_combo.setCurrentIndex(idx)

        self.size_spin.setValue(point.size)
        self.r_edit.setText(str(point.red))
        self.g_edit.setText(str(point.green))
        self.b_edit.setText(str(point.blue))

        # Зона радиуса
        self.zone_chk.setChecked(point.zone_enabled)
        self.zone_container.setEnabled(point.zone_enabled)

        if point.radius_m >= 1000.0:
            self.zone_unit_combo.setCurrentText("км")
            km_val = point.radius_m / 1000.0
            if km_val.is_integer():
                self.zone_radius_edit.setText(str(int(km_val)))
            else:
                self.zone_radius_edit.setText(f"{km_val:.2f}".rstrip("0").rstrip("."))
        elif point.radius_m > 0:
            self.zone_unit_combo.setCurrentText("м")
            if point.radius_m.is_integer():
                self.zone_radius_edit.setText(str(int(point.radius_m)))
            else:
                self.zone_radius_edit.setText(f"{point.radius_m:.1f}".rstrip("0").rstrip("."))

        self.zone_r_edit.setText(str(point.zone_red))
        self.zone_g_edit.setText(str(point.zone_green))
        self.zone_b_edit.setText(str(point.zone_blue))
        self.zone_opacity_slider.setValue(point.zone_opacity)
        self.zone_opacity_spin.setValue(point.zone_opacity)

        self._on_style_input_changed()

    def _on_format_changed(self, is_dd_checked: bool) -> None:
        """Переключение отображаемой формы ввода координат (DD или DMS)."""
        if is_dd_checked:
            self.stack_widget.setCurrentIndex(0)
        else:
            self.stack_widget.setCurrentIndex(1)

    def _on_style_input_changed(self) -> None:
        """Реактивное обновление виджета превью маркера."""
        symbol = self.symbol_combo.currentData() or "circle"
        size = self.size_spin.value()

        try:
            r = int(self.r_edit.text().strip())
            g = int(self.g_edit.text().strip())
            b = int(self.b_edit.text().strip())
            if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                self.preview_widget.update_style(symbol, size, r, g, b)
        except Exception:
            pass

    def _open_color_dialog(self) -> None:
        """Открытие диалога выбора цвета маркера QColorDialog."""
        try:
            cur_r = int(self.r_edit.text().strip())
            cur_g = int(self.g_edit.text().strip())
            cur_b = int(self.b_edit.text().strip())
            initial_color = QColor(cur_r, cur_g, cur_b)
        except Exception:
            initial_color = QColor(220, 30, 30)

        color = QColorDialog.getColor(initial_color, self, "Выбор цвета маркера")
        if color.isValid():
            self.r_edit.setText(str(color.red()))
            self.g_edit.setText(str(color.green()))
            self.b_edit.setText(str(color.blue()))
            self._on_style_input_changed()

    def _open_zone_color_dialog(self) -> None:
        """Открытие диалога выбора цвета зоны QColorDialog."""
        try:
            cur_r = int(self.zone_r_edit.text().strip())
            cur_g = int(self.zone_g_edit.text().strip())
            cur_b = int(self.zone_b_edit.text().strip())
            initial_color = QColor(cur_r, cur_g, cur_b)
        except Exception:
            initial_color = QColor(220, 30, 30)

        color = QColorDialog.getColor(initial_color, self, "Выбор цвета зоны")
        if color.isValid():
            self.zone_r_edit.setText(str(color.red()))
            self.zone_g_edit.setText(str(color.green()))
            self.zone_b_edit.setText(str(color.blue()))

    def _validate_and_submit(self) -> None:
        """Проверка ввода координат, стиля, зоны и проверка выхода центра за пределы РМЭ."""
        # 1. Валидация координат
        if self.rb_dd.isChecked():
            lat_text = self.lat_edit.text()
            lon_text = self.lon_edit.text()
            try:
                lat, lon = CoordinateValidator.validate_dd_pair(lat_text, lon_text)
            except ValueError as err:
                logger.warning("Ошибка валидации координат DD: %s", err)
                QMessageBox.warning(self, "Некорректные координаты", f"Ошибка в формате координат:\n{err}")
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
                QMessageBox.warning(self, "Некорректные координаты", f"Ошибка в формате координат:\n{err}")
                return

        # 2. Валидация стиля маркера
        symbol = self.symbol_combo.currentData() or "circle"
        size = self.size_spin.value()
        r_text = self.r_edit.text()
        g_text = self.g_edit.text()
        b_text = self.b_edit.text()

        try:
            style = StyleValidator.validate_style(symbol, size, r_text, g_text, b_text)
        except ValueError as err:
            logger.warning("Ошибка валидации стиля маркера: %s", err)
            QMessageBox.warning(self, "Некорректный стиль маркера", str(err))
            return

        # 3. Валидация зоны радиуса (Этап 7)
        zone_enabled = self.zone_chk.isChecked()
        if zone_enabled:
            raw_radius = self.zone_radius_edit.text()
            unit = self.zone_unit_combo.currentText()
            try:
                parsed_radius = GeodesicService.parse_radius(raw_radius, unit)
                radius_m = StyleValidator.validate_radius(parsed_radius, enabled=True)
            except ValueError as err:
                logger.warning("Ошибка валидации радиуса зоны: %s", err)
                QMessageBox.warning(self, "Некорректный радиус", str(err))
                return

            try:
                z_r, z_g, z_b = StyleValidator.validate_rgb(
                    self.zone_r_edit.text(),
                    self.zone_g_edit.text(),
                    self.zone_b_edit.text(),
                )
            except ValueError as err:
                logger.warning("Ошибка валидации цвета зоны: %s", err)
                QMessageBox.warning(self, "Некорректный цвет зоны", str(err))
                return

            try:
                opacity = StyleValidator.validate_opacity(self.zone_opacity_spin.value())
            except ValueError as err:
                logger.warning("Ошибка валидации прозрачности зоны: %s", err)
                QMessageBox.warning(self, "Некорректная прозрачность", str(err))
                return
        else:
            radius_m = 0.0
            z_r, z_g, z_b = 220, 30, 30
            opacity = 30

        name = self.name_edit.text().strip()

        # 4. Проверка выхода центра точки за границу РМЭ
        if self._boundary_geometry is not None:
            is_inside = CoordinateService.is_point_inside_boundary(
                longitude=lon,
                latitude=lat,
                boundary_geometry=self._boundary_geometry,
            )
            if not is_inside:
                logger.info("Точка (%s, %s) вне границы РМЭ", lon, lat)
                reply = QMessageBox.question(
                    self,
                    "Предупреждение",
                    "Координата находится за пределами Республики Марий Эл.\nСохранить точку?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        self._parsed_data = PointDialogData(
            name=name,
            latitude=lat,
            longitude=lon,
            symbol=style.symbol,
            size=style.size,
            red=style.red,
            green=style.green,
            blue=style.blue,
            zone_enabled=zone_enabled,
            radius_m=radius_m,
            zone_red=z_r,
            zone_green=z_g,
            zone_blue=z_b,
            zone_opacity=opacity,
        )
        self.accept()

    def get_point_data(self) -> PointDialogData | None:
        """Возвращает проверенные данные точки после успешного завершения."""
        return self._parsed_data


# Псевдоним для обратной совместимости с тестами Этапов 4 и 5
AddPointDialog = PointDialog
