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
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.coordinates.validator import CoordinateValidator
from rme_mapper.i18n import tr
from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.models.map_point import MapPoint
from rme_mapper.models.point_style import (
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
        self.stroke_red: int = 255
        self.stroke_green: int = 255
        self.stroke_blue: int = 255
        self.stroke_width: float = 1.5
        self.opacity: float = 100.0

    def update_style(
        self,
        symbol: str,
        size: float,
        red: int,
        green: int,
        blue: int,
        stroke_red: int = 255,
        stroke_green: int = 255,
        stroke_blue: int = 255,
        stroke_width: float = 1.5,
        opacity: float = 100.0,
    ) -> None:
        """Обновление параметров и перерисовка предпросмотра."""
        self.symbol = symbol
        self.size_val = size
        self.red = red
        self.green = green
        self.blue = blue
        self.stroke_red = stroke_red
        self.stroke_green = stroke_green
        self.stroke_blue = stroke_blue
        self.stroke_width = stroke_width
        self.opacity = opacity
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

        if self.stroke_width > 0:
            pen = QPen(
                QColor(self.stroke_red, self.stroke_green, self.stroke_blue),
                max(1.0, float(self.stroke_width)),
            )
        else:
            pen = QPen(Qt.PenStyle.NoPen)
        painter.setPen(pen)

        alpha = int(self.opacity * 255 / 100.0)
        painter.setBrush(QBrush(QColor(self.red, self.green, self.blue, alpha)))
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
    # Поля расширенной модели (Этап 17)
    object_number: str = ""
    description: str = ""
    category: str = ""
    stroke_red: int = 255
    stroke_green: int = 255
    stroke_blue: int = 255
    stroke_width: float = 1.5
    opacity: float = 100.0
    zone_border_red: int = 30
    zone_border_green: int = 58
    zone_border_blue: int = 138
    zone_border_width: float = 1.5
    zone_border_style: str = "solid"
    group_id: str | None = None

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
            self.object_number,
            self.description,
            self.category,
            self.stroke_red,
            self.stroke_green,
            self.stroke_blue,
            self.stroke_width,
            self.opacity,
            self.zone_border_red,
            self.zone_border_green,
            self.zone_border_blue,
            self.zone_border_width,
            self.zone_border_style,
        )[index]

    def __len__(self) -> int:
        return 27


class PointDialog(QDialog):
    """Универсальный диалог создания (CREATE) и редактирования (EDIT) точки."""

    def __init__(
        self,
        parent: QWidget | None = None,
        boundary_geometry: Any = None,
        default_name: str = "",
        point: MapPoint | None = None,
        mode: str = "CREATE",
        map_name: str | None = None,
        map_extent: dict[str, float] | tuple[float, float, float, float] | list[float] | None = None,
        map_crs: str = "OGC:CRS84",
        initial_lat: float | None = None,
        initial_lon: float | None = None,
        categories: list[str] | None = None,
        groups: list[Any] | None = None,
        current_group_id: str | None = None,
        group_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._boundary_geometry = boundary_geometry
        self._point = point
        self.mode = "EDIT" if point is not None else mode.upper()
        self._parsed_data: PointDialogData | None = None
        self._map_name = map_name
        self._map_extent = map_extent
        self._map_crs = map_crs
        self._default_name = default_name
        self._categories = list(categories or [])
        self._groups = list(groups or [])
        self._initial_group_id = current_group_id if current_group_id is not None else group_id

        self.setModal(True)
        self.resize(520, 580)

        self._setup_ui(default_name)
        if self._point:
            self._populate_fields_from_point(self._point)
        elif initial_lat is not None and initial_lon is not None:
            self._populate_initial_coordinates(initial_lat, initial_lon)

        self.retranslate_ui()

    def _setup_ui(self, default_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.tab_widget = QTabWidget(self)
        self.tab_widget.setObjectName("pointDialogTabs")

        # -------------------------------------------------------------
        # Вкладка 1: Основное
        # -------------------------------------------------------------
        self.tab_main = QWidget()
        tab_main_layout = QVBoxLayout(self.tab_main)
        tab_main_layout.setSpacing(10)

        main_form = QFormLayout()
        main_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 1.1 Название (обязательное)
        self.name_label = QLabel("Название:", self)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("pointNameEdit")
        self.name_edit.setPlaceholderText(default_name or "Название (опционально)")
        main_form.addRow(self.name_label, self.name_edit)

        # 1.2 Номер объекта (опциональное, <=100 символов)
        self.num_label = QLabel("Номер объекта:", self)
        self.num_edit = QLineEdit(self)
        self.num_edit.setObjectName("pointNumEdit")
        self.num_edit.setMaxLength(100)
        self.num_edit.setPlaceholderText("Например: А-102 или № 15")
        main_form.addRow(self.num_label, self.num_edit)

        # 1.3 Категория (editable QComboBox, <=200 символов)
        self.cat_label = QLabel("Категория:", self)
        self.cat_combo = QComboBox(self)
        self.cat_combo.setObjectName("pointCategoryCombo")
        self.cat_combo.setEditable(True)
        if self.cat_combo.lineEdit():
            self.cat_combo.lineEdit().setMaxLength(200)
            self.cat_combo.lineEdit().setPlaceholderText("Категория объекта")
        for cat in self._categories:
            if cat and self.cat_combo.findText(cat) == -1:
                self.cat_combo.addItem(cat)
        main_form.addRow(self.cat_label, self.cat_combo)

        # 1.35 Группа (QComboBox: "Без группы", затем группы)
        self.group_label = QLabel(tr("properties.group"), self)
        self.group_combo = QComboBox(self)
        self.group_combo.setObjectName("pointGroupCombo")
        self.group_combo.addItem(tr("groups.ungrouped"), None)
        for g in self._groups:
            self.group_combo.addItem(g.name, g.id)
        if self._initial_group_id:
            idx = self.group_combo.findData(self._initial_group_id)
            if idx != -1:
                self.group_combo.setCurrentIndex(idx)
        main_form.addRow(self.group_label, self.group_combo)

        # 1.4 Описание (QTextEdit, <=8192 символов)
        self.desc_label = QLabel("Описание:", self)
        self.desc_edit = QTextEdit(self)
        self.desc_edit.setObjectName("pointDescEdit")
        self.desc_edit.setPlaceholderText("Подробное описание или примечания...")
        self.desc_edit.setMaximumHeight(140)
        main_form.addRow(self.desc_label, self.desc_edit)

        tab_main_layout.addLayout(main_form)
        tab_main_layout.addStretch()
        self.tab_widget.addTab(self.tab_main, "Основное")

        # -------------------------------------------------------------
        # Вкладка 2: Координаты
        # -------------------------------------------------------------
        self.tab_coords = QWidget()
        tab_coords_layout = QVBoxLayout(self.tab_coords)
        tab_coords_layout.setSpacing(10)

        self.format_group_box = QGroupBox("Формат координат", self)
        format_layout = QHBoxLayout(self.format_group_box)
        self.rb_dd = QRadioButton("Десятичные градусы (DD)", self.format_group_box)
        self.rb_dd.setObjectName("rbFormatDD")
        self.rb_dd.setChecked(True)

        self.rb_dms = QRadioButton("Градусы / минуты / секунды (DMS)", self.format_group_box)
        self.rb_dms.setObjectName("rbFormatDMS")

        format_layout.addWidget(self.rb_dd)
        format_layout.addWidget(self.rb_dms)
        tab_coords_layout.addWidget(self.format_group_box)

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
        self.lat_dd_label = QLabel("Широта (DD):")
        dd_form.addRow(self.lat_dd_label, self.lat_edit)

        self.lon_edit = QLineEdit(dd_widget)
        self.lon_edit.setObjectName("pointLonEdit")
        self.lon_edit.setPlaceholderText("Пример: 47.886 или 47,886")
        self.lon_dd_label = QLabel("Долгота (DD):")
        dd_form.addRow(self.lon_dd_label, self.lon_edit)

        self.dd_hint = QLabel("Диапазон: широта [-90; 90], долгота [-180; 180]", dd_widget)
        self.dd_hint.setStyleSheet("color: #777777; font-size: 11px;")

        dd_layout.addLayout(dd_form)
        dd_layout.addWidget(self.dd_hint)
        self.stack_widget.addWidget(dd_widget)

        # --- Страница 1: Режим DMS ---
        dms_widget = QWidget(self.stack_widget)
        dms_layout = QVBoxLayout(dms_widget)
        dms_layout.setContentsMargins(0, 0, 0, 0)

        dms_grid = QGridLayout()
        dms_grid.setSpacing(6)

        dms_grid.addWidget(QLabel(""), 0, 0)
        self.dms_deg_hdr = QLabel("Градусы")
        self.dms_min_hdr = QLabel("Минуты")
        self.dms_sec_hdr = QLabel("Секунды")
        self.dms_dir_hdr = QLabel("Напр.")
        dms_grid.addWidget(self.dms_deg_hdr, 0, 1)
        dms_grid.addWidget(self.dms_min_hdr, 0, 2)
        dms_grid.addWidget(self.dms_sec_hdr, 0, 3)
        dms_grid.addWidget(self.dms_dir_hdr, 0, 4)

        # Широта (DMS)
        self.dms_lat_hdr = QLabel("Широта:")
        dms_grid.addWidget(self.dms_lat_hdr, 1, 0)
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
        self.dms_lon_hdr = QLabel("Долгота:")
        dms_grid.addWidget(self.dms_lon_hdr, 2, 0)
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

        self.dms_hint = QLabel(
            "Широта: 0..90° [N/S], Долгота: 0..180° [E/W].",
            dms_widget,
        )
        self.dms_hint.setStyleSheet("color: #777777; font-size: 11px;")

        dms_layout.addLayout(dms_grid)
        dms_layout.addWidget(self.dms_hint)
        self.stack_widget.addWidget(dms_widget)

        tab_coords_layout.addWidget(self.stack_widget)
        tab_coords_layout.addStretch()
        self.rb_dd.toggled.connect(self._on_format_changed)
        self.tab_widget.addTab(self.tab_coords, "Координаты")

        # -------------------------------------------------------------
        # Вкладка 3: Оформление (Маркер + Зона)
        # -------------------------------------------------------------
        self.tab_style = QWidget()
        tab_style_layout = QVBoxLayout(self.tab_style)
        tab_style_layout.setSpacing(10)

        # 3.1 Блок стиля маркера
        self.style_box = QGroupBox("Стиль маркера", self.tab_style)
        style_main_layout = QHBoxLayout(self.style_box)

        style_form = QFormLayout()
        style_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.symbol_combo = QComboBox(self.style_box)
        self.symbol_combo.setObjectName("pointSymbolCombo")
        self.symbol_combo.addItem("Круг", "circle")
        self.symbol_combo.addItem("Квадрат", "square")
        self.symbol_combo.addItem("Треугольник", "triangle")
        self.symbol_combo.currentIndexChanged.connect(self._on_style_input_changed)
        self.shape_label = QLabel("Форма:")
        style_form.addRow(self.shape_label, self.symbol_combo)

        self.size_spin = QDoubleSpinBox(self.style_box)
        self.size_spin.setObjectName("pointSizeSpin")
        self.size_spin.setRange(4.0, 50.0)
        self.size_spin.setValue(12.0)
        self.size_spin.setSingleStep(1.0)
        self.size_spin.setDecimals(1)
        self.size_spin.valueChanged.connect(self._on_style_input_changed)
        self.size_label = QLabel("Размер (px):")
        style_form.addRow(self.size_label, self.size_spin)

        # Заливка RGB
        rgb_layout = QHBoxLayout()
        rgb_layout.setSpacing(4)
        rgb_layout.addWidget(QLabel("R:"))
        self.r_edit = QLineEdit(self.style_box)
        self.r_edit.setObjectName("pointREdit")
        self.r_edit.setText("220")
        self.r_edit.setMaximumWidth(42)
        self.r_edit.textChanged.connect(self._on_style_input_changed)
        rgb_layout.addWidget(self.r_edit)

        rgb_layout.addWidget(QLabel("G:"))
        self.g_edit = QLineEdit(self.style_box)
        self.g_edit.setObjectName("pointGEdit")
        self.g_edit.setText("30")
        self.g_edit.setMaximumWidth(42)
        self.g_edit.textChanged.connect(self._on_style_input_changed)
        rgb_layout.addWidget(self.g_edit)

        rgb_layout.addWidget(QLabel("B:"))
        self.b_edit = QLineEdit(self.style_box)
        self.b_edit.setObjectName("pointBEdit")
        self.b_edit.setText("30")
        self.b_edit.setMaximumWidth(42)
        self.b_edit.textChanged.connect(self._on_style_input_changed)
        rgb_layout.addWidget(self.b_edit)

        self.btn_pick_color = QPushButton("Выбрать...", self.style_box)
        self.btn_pick_color.setObjectName("btnPickColor")
        self.btn_pick_color.clicked.connect(self._open_color_dialog)
        rgb_layout.addWidget(self.btn_pick_color)

        self.color_label = QLabel("Цвет заливки:")
        style_form.addRow(self.color_label, rgb_layout)

        # Непрозрачность маркера (0..100%)
        marker_op_layout = QHBoxLayout()
        self.marker_opacity_slider = QSlider(Qt.Orientation.Horizontal, self.style_box)
        self.marker_opacity_slider.setObjectName("pointMarkerOpacitySlider")
        self.marker_opacity_slider.setRange(0, 100)
        self.marker_opacity_slider.setValue(100)
        marker_op_layout.addWidget(self.marker_opacity_slider, stretch=1)

        self.marker_opacity_spin = QSpinBox(self.style_box)
        self.marker_opacity_spin.setObjectName("pointMarkerOpacitySpin")
        self.marker_opacity_spin.setRange(0, 100)
        self.marker_opacity_spin.setValue(100)
        self.marker_opacity_spin.setSuffix("%")
        marker_op_layout.addWidget(self.marker_opacity_spin)

        self.marker_opacity_slider.valueChanged.connect(self.marker_opacity_spin.setValue)
        self.marker_opacity_spin.valueChanged.connect(self.marker_opacity_slider.setValue)
        self.marker_opacity_spin.valueChanged.connect(self._on_style_input_changed)

        self.marker_opacity_label = QLabel("Непрозрачность:")
        style_form.addRow(self.marker_opacity_label, marker_op_layout)

        # Обводка маркера: цвет RGB
        stroke_rgb_layout = QHBoxLayout()
        stroke_rgb_layout.setSpacing(4)
        stroke_rgb_layout.addWidget(QLabel("R:"))
        self.stroke_r_edit = QLineEdit(self.style_box)
        self.stroke_r_edit.setObjectName("pointStrokeREdit")
        self.stroke_r_edit.setText("255")
        self.stroke_r_edit.setMaximumWidth(42)
        self.stroke_r_edit.textChanged.connect(self._on_style_input_changed)
        stroke_rgb_layout.addWidget(self.stroke_r_edit)

        stroke_rgb_layout.addWidget(QLabel("G:"))
        self.stroke_g_edit = QLineEdit(self.style_box)
        self.stroke_g_edit.setObjectName("pointStrokeGEdit")
        self.stroke_g_edit.setText("255")
        self.stroke_g_edit.setMaximumWidth(42)
        self.stroke_g_edit.textChanged.connect(self._on_style_input_changed)
        stroke_rgb_layout.addWidget(self.stroke_g_edit)

        stroke_rgb_layout.addWidget(QLabel("B:"))
        self.stroke_b_edit = QLineEdit(self.style_box)
        self.stroke_b_edit.setObjectName("pointStrokeBEdit")
        self.stroke_b_edit.setText("255")
        self.stroke_b_edit.setMaximumWidth(42)
        self.stroke_b_edit.textChanged.connect(self._on_style_input_changed)
        stroke_rgb_layout.addWidget(self.stroke_b_edit)

        self.btn_pick_stroke_color = QPushButton("Выбрать...", self.style_box)
        self.btn_pick_stroke_color.setObjectName("btnPickStrokeColor")
        self.btn_pick_stroke_color.clicked.connect(self._open_stroke_color_dialog)
        stroke_rgb_layout.addWidget(self.btn_pick_stroke_color)

        self.stroke_color_label = QLabel("Цвет обводки:")
        style_form.addRow(self.stroke_color_label, stroke_rgb_layout)

        # Толщина обводки (0..10 px)
        self.stroke_width_spin = QDoubleSpinBox(self.style_box)
        self.stroke_width_spin.setObjectName("pointStrokeWidthSpin")
        self.stroke_width_spin.setRange(0.0, 10.0)
        self.stroke_width_spin.setValue(1.5)
        self.stroke_width_spin.setSingleStep(0.5)
        self.stroke_width_spin.setDecimals(1)
        self.stroke_width_spin.setSuffix(" px")
        self.stroke_width_spin.valueChanged.connect(self._on_style_input_changed)
        self.stroke_width_label = QLabel("Толщина обводки:")
        style_form.addRow(self.stroke_width_label, self.stroke_width_spin)

        style_main_layout.addLayout(style_form, stretch=1)

        preview_box = QVBoxLayout()
        preview_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label = QLabel("Превью:")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_box.addWidget(self.preview_label)

        self.preview_widget = MarkerPreviewWidget(self.style_box)
        self.preview_widget.setObjectName("markerPreviewWidget")
        preview_box.addWidget(self.preview_widget)
        style_main_layout.addLayout(preview_box)

        tab_style_layout.addWidget(self.style_box)

        # 3.2 Блок географической зоны радиуса
        self.zone_group = QGroupBox("Географическая зона", self.tab_style)
        zone_box_layout = QVBoxLayout(self.zone_group)
        zone_box_layout.setSpacing(6)

        self.zone_chk = QCheckBox("Показывать зону", self.zone_group)
        self.zone_chk.setObjectName("pointZoneEnableChk")
        zone_box_layout.addWidget(self.zone_chk)

        self.zone_container = QWidget(self.zone_group)
        zone_form = QFormLayout(self.zone_container)
        zone_form.setContentsMargins(0, 0, 0, 0)
        zone_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Радиус
        radius_layout = QHBoxLayout()
        self.zone_radius_edit = QLineEdit(self.zone_container)
        self.zone_radius_edit.setObjectName("pointZoneRadiusEdit")
        self.zone_radius_edit.setPlaceholderText("Например: 10 или 500")
        radius_layout.addWidget(self.zone_radius_edit, stretch=1)

        self.zone_unit_combo = QComboBox(self.zone_container)
        self.zone_unit_combo.setObjectName("pointZoneRadiusUnitCombo")
        self.zone_unit_combo.addItem("км", "km")
        self.zone_unit_combo.addItem("м", "m")
        radius_layout.addWidget(self.zone_unit_combo)
        self.radius_label = QLabel("Радиус:")
        zone_form.addRow(self.radius_label, radius_layout)

        # Цвет заливки зоны
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

        self.btn_pick_zone_color = QPushButton("Выбрать...", self.zone_container)
        self.btn_pick_zone_color.setObjectName("btnPickZoneColor")
        self.btn_pick_zone_color.clicked.connect(self._open_zone_color_dialog)
        zone_rgb_layout.addWidget(self.btn_pick_zone_color)

        self.zone_color_label = QLabel("Цвет заливки зоны:")
        zone_form.addRow(self.zone_color_label, zone_rgb_layout)

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

        self.zone_opacity_slider.valueChanged.connect(self.zone_opacity_spin.setValue)
        self.zone_opacity_spin.valueChanged.connect(self.zone_opacity_slider.setValue)

        self.zone_opacity_label = QLabel("Непрозрачность зоны:")
        zone_form.addRow(self.zone_opacity_label, opacity_layout)

        # Граница зоны: цвет RGB
        zone_border_rgb_layout = QHBoxLayout()
        zone_border_rgb_layout.setSpacing(4)
        zone_border_rgb_layout.addWidget(QLabel("R:"))
        self.zone_border_r_edit = QLineEdit(self.zone_container)
        self.zone_border_r_edit.setObjectName("pointZoneBorderREdit")
        self.zone_border_r_edit.setText("30")
        self.zone_border_r_edit.setMaximumWidth(42)
        zone_border_rgb_layout.addWidget(self.zone_border_r_edit)

        zone_border_rgb_layout.addWidget(QLabel("G:"))
        self.zone_border_g_edit = QLineEdit(self.zone_container)
        self.zone_border_g_edit.setObjectName("pointZoneBorderGEdit")
        self.zone_border_g_edit.setText("58")
        self.zone_border_g_edit.setMaximumWidth(42)
        zone_border_rgb_layout.addWidget(self.zone_border_g_edit)

        zone_border_rgb_layout.addWidget(QLabel("B:"))
        self.zone_border_b_edit = QLineEdit(self.zone_container)
        self.zone_border_b_edit.setObjectName("pointZoneBorderBEdit")
        self.zone_border_b_edit.setText("138")
        self.zone_border_b_edit.setMaximumWidth(42)
        zone_border_rgb_layout.addWidget(self.zone_border_b_edit)

        self.btn_pick_zone_border_color = QPushButton("Выбрать...", self.zone_container)
        self.btn_pick_zone_border_color.setObjectName("btnPickZoneBorderColor")
        self.btn_pick_zone_border_color.clicked.connect(self._open_zone_border_color_dialog)
        zone_border_rgb_layout.addWidget(self.btn_pick_zone_border_color)

        self.zone_border_color_label = QLabel("Цвет границы зоны:")
        zone_form.addRow(self.zone_border_color_label, zone_border_rgb_layout)

        # Толщина границы зоны (0..10 px)
        self.zone_border_width_spin = QDoubleSpinBox(self.zone_container)
        self.zone_border_width_spin.setObjectName("pointZoneBorderWidthSpin")
        self.zone_border_width_spin.setRange(0.0, 10.0)
        self.zone_border_width_spin.setValue(1.5)
        self.zone_border_width_spin.setSingleStep(0.5)
        self.zone_border_width_spin.setDecimals(1)
        self.zone_border_width_spin.setSuffix(" px")
        self.zone_border_width_label = QLabel("Толщина границы:")
        zone_form.addRow(self.zone_border_width_label, self.zone_border_width_spin)

        # Стиль границы зоны (solid, dash, dot)
        self.zone_border_style_combo = QComboBox(self.zone_container)
        self.zone_border_style_combo.setObjectName("pointZoneBorderStyleCombo")
        self.zone_border_style_combo.addItem("Сплошная", "solid")
        self.zone_border_style_combo.addItem("Штриховая", "dash")
        self.zone_border_style_combo.addItem("Точечная", "dot")
        self.zone_border_style_label = QLabel("Стиль границы:")
        zone_form.addRow(self.zone_border_style_label, self.zone_border_style_combo)

        zone_box_layout.addWidget(self.zone_container)
        tab_style_layout.addWidget(self.zone_group)

        self.zone_container.setEnabled(False)
        self.zone_chk.toggled.connect(self.zone_container.setEnabled)
        self.tab_widget.addTab(self.tab_style, "Оформление")

        layout.addWidget(self.tab_widget)

        # Псевдонимы атрибутов для тестов и обратной совместимости
        self.zone_enabled_chk = self.zone_chk
        self.radius_edit = self.zone_radius_edit
        self.unit_combo = self.zone_unit_combo
        self.opacity_slider = self.zone_opacity_slider
        self.opacity_spin = self.zone_opacity_spin

        # Кнопки диалога
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_cancel.setObjectName("btnAddPointCancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_add = QPushButton("Сохранить" if self.mode == "EDIT" else "Добавить", self)
        self.btn_add.setObjectName("btnAddPointSubmit")
        self.btn_add.setDefault(True)
        self.btn_add.clicked.connect(self._validate_and_submit)
        btn_layout.addWidget(self.btn_add)

        layout.addLayout(btn_layout)

    def retranslate_ui(self) -> None:
        """Обновление локализованных текстов диалога."""
        if self.mode == "EDIT":
            self.setWindowTitle(tr("dialog.point.title_edit"))
        else:
            self.setWindowTitle(tr("dialog.point.title_add"))

        # Вкладки
        if hasattr(self, "tab_widget"):
            self.tab_widget.setTabText(0, tr("tab.main"))
            self.tab_widget.setTabText(1, tr("tab.coordinates"))
            self.tab_widget.setTabText(2, tr("tab.style"))

        # Вкладка 1: Основное
        if hasattr(self, "name_label"):
            self.name_label.setText(tr("dialog.point.name"))
        if hasattr(self, "name_edit"):
            self.name_edit.setPlaceholderText(self._default_name or tr("dialog.point.name_placeholder"))
        if hasattr(self, "num_label"):
            self.num_label.setText(tr("dialog.point.object_number"))
        if hasattr(self, "num_edit"):
            self.num_edit.setPlaceholderText(tr("dialog.point.object_number_placeholder"))
        if hasattr(self, "cat_label"):
            self.cat_label.setText(tr("dialog.point.category"))
        if hasattr(self, "cat_combo") and self.cat_combo.lineEdit():
            self.cat_combo.lineEdit().setPlaceholderText(tr("dialog.point.category_placeholder"))
        if hasattr(self, "group_label"):
            self.group_label.setText(tr("properties.group"))
        if hasattr(self, "group_combo") and self.group_combo.count() > 0:
            self.group_combo.setItemText(0, tr("groups.ungrouped"))
        if hasattr(self, "desc_label"):
            self.desc_label.setText(tr("dialog.point.description"))
        if hasattr(self, "desc_edit"):
            self.desc_edit.setPlaceholderText(tr("dialog.point.description_placeholder"))

        # Вкладка 2: Координаты
        if hasattr(self, "format_group_box"):
            self.format_group_box.setTitle(tr("dialog.point.format"))
        if hasattr(self, "rb_dd"):
            self.rb_dd.setText(tr("dialog.point.format_dd"))
        if hasattr(self, "rb_dms"):
            self.rb_dms.setText(tr("dialog.point.format_dms"))
        if hasattr(self, "lat_dd_label"):
            self.lat_dd_label.setText(tr("dialog.point.lat_dd"))
        if hasattr(self, "lon_dd_label"):
            self.lon_dd_label.setText(tr("dialog.point.lon_dd"))
        if hasattr(self, "dd_hint"):
            self.dd_hint.setText(tr("dialog.point.dd_hint"))
        if hasattr(self, "dms_deg_hdr"):
            self.dms_deg_hdr.setText(tr("dialog.point.degrees"))
        if hasattr(self, "dms_min_hdr"):
            self.dms_min_hdr.setText(tr("dialog.point.minutes"))
        if hasattr(self, "dms_sec_hdr"):
            self.dms_sec_hdr.setText(tr("dialog.point.seconds"))
        if hasattr(self, "dms_dir_hdr"):
            self.dms_dir_hdr.setText(tr("dialog.point.direction"))
        if hasattr(self, "dms_lat_hdr"):
            self.dms_lat_hdr.setText(tr("dialog.point.lat_dms"))
        if hasattr(self, "dms_lon_hdr"):
            self.dms_lon_hdr.setText(tr("dialog.point.lon_dms"))
        if hasattr(self, "dms_hint"):
            self.dms_hint.setText(tr("dialog.point.dms_hint"))

        # Вкладка 3: Оформление
        if hasattr(self, "style_box"):
            self.style_box.setTitle(tr("dialog.point.style_box"))
        if hasattr(self, "shape_label"):
            self.shape_label.setText(tr("dialog.point.shape"))
        if hasattr(self, "symbol_combo"):
            cur_idx = self.symbol_combo.currentIndex()
            self.symbol_combo.setItemText(0, tr("shape.circle"))
            self.symbol_combo.setItemText(1, tr("shape.square"))
            self.symbol_combo.setItemText(2, tr("shape.triangle"))
            self.symbol_combo.setCurrentIndex(cur_idx)

        if hasattr(self, "size_label"):
            self.size_label.setText(tr("dialog.point.size"))
        if hasattr(self, "color_label"):
            self.color_label.setText(tr("dialog.point.color"))
        if hasattr(self, "btn_pick_color"):
            self.btn_pick_color.setText(tr("dialog.point.choose_color"))
        if hasattr(self, "marker_opacity_label"):
            self.marker_opacity_label.setText(tr("dialog.point.opacity"))
        if hasattr(self, "stroke_color_label"):
            self.stroke_color_label.setText(tr("dialog.point.stroke_color"))
        if hasattr(self, "stroke_width_label"):
            self.stroke_width_label.setText(tr("dialog.point.stroke_width"))
        if hasattr(self, "btn_pick_stroke_color"):
            self.btn_pick_stroke_color.setText(tr("dialog.point.choose_color"))
        if hasattr(self, "preview_label"):
            self.preview_label.setText(tr("dialog.point.preview"))

        if hasattr(self, "zone_group"):
            self.zone_group.setTitle(tr("dialog.point.zone_box"))
        if hasattr(self, "zone_chk"):
            self.zone_chk.setText(tr("dialog.point.show_zone"))
        if hasattr(self, "radius_label"):
            self.radius_label.setText(tr("dialog.point.radius"))
        if hasattr(self, "zone_radius_edit"):
            self.zone_radius_edit.setPlaceholderText(tr("dialog.point.radius_placeholder"))

        if hasattr(self, "zone_unit_combo"):
            cur_u_idx = self.zone_unit_combo.currentIndex()
            self.zone_unit_combo.setItemText(0, tr("unit.km"))
            self.zone_unit_combo.setItemText(1, tr("unit.m"))
            self.zone_unit_combo.setCurrentIndex(cur_u_idx)

        if hasattr(self, "zone_color_label"):
            self.zone_color_label.setText(tr("dialog.point.zone_color"))
        if hasattr(self, "btn_pick_zone_color"):
            self.btn_pick_zone_color.setText(tr("dialog.point.choose_color"))
        if hasattr(self, "zone_opacity_label"):
            self.zone_opacity_label.setText(tr("dialog.point.opacity"))
        if hasattr(self, "zone_border_color_label"):
            self.zone_border_color_label.setText(tr("dialog.point.zone_border_color"))
        if hasattr(self, "zone_border_width_label"):
            self.zone_border_width_label.setText(tr("dialog.point.zone_border_width"))
        if hasattr(self, "zone_border_style_label"):
            self.zone_border_style_label.setText(tr("dialog.point.zone_border_style"))
        if hasattr(self, "zone_border_style_combo"):
            cur_b_idx = self.zone_border_style_combo.currentIndex()
            self.zone_border_style_combo.setItemText(0, tr("border_style.solid"))
            self.zone_border_style_combo.setItemText(1, tr("border_style.dash"))
            self.zone_border_style_combo.setItemText(2, tr("border_style.dot"))
            self.zone_border_style_combo.setCurrentIndex(cur_b_idx)
        if hasattr(self, "btn_pick_zone_border_color"):
            self.btn_pick_zone_border_color.setText(tr("dialog.point.choose_color"))

        if hasattr(self, "btn_add"):
            self.btn_add.setText(tr("dialog.point.btn_save") if self.mode == "EDIT" else tr("dialog.point.btn_add"))
        if hasattr(self, "btn_cancel"):
            self.btn_cancel.setText(tr("dialog.point.btn_cancel"))

    def _populate_fields_from_point(self, point: MapPoint) -> None:
        """Предзаполнение полей диалога при редактировании существующей точки."""
        self.name_edit.setText(point.name)
        self.num_edit.setText(point.object_number)
        self.cat_combo.setCurrentText(point.category)
        if hasattr(self, "group_combo"):
            idx = self.group_combo.findData(point.group_id)
            if idx != -1:
                self.group_combo.setCurrentIndex(idx)
            else:
                self.group_combo.setCurrentIndex(0)
        self.desc_edit.setPlainText(point.description)

        # Заполнение DD полей
        self.lat_edit.setText(f"{point.latitude:.6f}".rstrip("0").rstrip("."))
        self.lon_edit.setText(f"{point.longitude:.6f}".rstrip("0").rstrip("."))

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
        self.marker_opacity_spin.setValue(int(point.opacity))

        self.stroke_r_edit.setText(str(point.stroke_red))
        self.stroke_g_edit.setText(str(point.stroke_green))
        self.stroke_b_edit.setText(str(point.stroke_blue))
        self.stroke_width_spin.setValue(point.stroke_width)

        # Зона радиуса
        self.zone_chk.setChecked(point.zone_enabled)
        self.zone_container.setEnabled(point.zone_enabled)

        if point.radius_m >= 1000.0:
            self.zone_unit_combo.setCurrentIndex(0)  # km
            km_val = point.radius_m / 1000.0
            if km_val.is_integer():
                self.zone_radius_edit.setText(str(int(km_val)))
            else:
                self.zone_radius_edit.setText(f"{km_val:.2f}".rstrip("0").rstrip("."))
        elif point.radius_m > 0:
            self.zone_unit_combo.setCurrentIndex(1)  # m
            if point.radius_m.is_integer():
                self.zone_radius_edit.setText(str(int(point.radius_m)))
            else:
                self.zone_radius_edit.setText(f"{point.radius_m:.1f}".rstrip("0").rstrip("."))

        self.zone_r_edit.setText(str(point.zone_red))
        self.zone_g_edit.setText(str(point.zone_green))
        self.zone_b_edit.setText(str(point.zone_blue))
        self.zone_opacity_slider.setValue(point.zone_opacity)
        self.zone_opacity_spin.setValue(point.zone_opacity)

        self.zone_border_r_edit.setText(str(point.zone_border_red))
        self.zone_border_g_edit.setText(str(point.zone_border_green))
        self.zone_border_b_edit.setText(str(point.zone_border_blue))
        self.zone_border_width_spin.setValue(point.zone_border_width)
        b_idx = self.zone_border_style_combo.findData(point.zone_border_style)
        if b_idx >= 0:
            self.zone_border_style_combo.setCurrentIndex(b_idx)

        self._on_style_input_changed()

    def _populate_initial_coordinates(self, lat: float, lon: float) -> None:
        """Предзаполнение полей координат (DD и DMS) при создании точки кликом по карте."""
        self.lat_edit.setText(f"{lat:.6f}")
        self.lon_edit.setText(f"{lon:.6f}")

        lat_deg, lat_min, lat_sec = decimal_to_dms(lat)
        self.lat_deg_edit.setText(str(lat_deg))
        self.lat_min_edit.setText(str(lat_min))
        self.lat_sec_edit.setText(f"{lat_sec:.2f}".rstrip("0").rstrip("."))
        self.lat_dir_combo.setCurrentText("N" if lat >= 0 else "S")

        lon_deg, lon_min, lon_sec = decimal_to_dms(lon)
        self.lon_deg_edit.setText(str(lon_deg))
        self.lon_min_edit.setText(str(lon_min))
        self.lon_sec_edit.setText(f"{lon_sec:.2f}".rstrip("0").rstrip("."))
        self.lon_dir_combo.setCurrentText("E" if lon >= 0 else "W")

    def _on_format_changed(self, is_dd: bool) -> None:
        """Переключение страниц стека между DD (0) и DMS (1)."""
        if is_dd:
            self.stack_widget.setCurrentIndex(0)
            self._sync_dms_to_dd()
        else:
            self.stack_widget.setCurrentIndex(1)
            self._sync_dd_to_dms()

    def _sync_dd_to_dms(self) -> None:
        """Конвертация и перенос значений из полей DD в поля DMS."""
        lat_text = self.lat_edit.text()
        lon_text = self.lon_edit.text()
        if not lat_text and not lon_text:
            return

        try:
            lat_f, lon_f = CoordinateValidator.validate_dd_pair(lat_text, lon_text)
            lat_deg, lat_min, lat_sec = decimal_to_dms(lat_f)
            self.lat_deg_edit.setText(str(lat_deg))
            self.lat_min_edit.setText(str(lat_min))
            self.lat_sec_edit.setText(f"{lat_sec:.2f}".rstrip("0").rstrip("."))
            self.lat_dir_combo.setCurrentText("N" if lat_f >= 0 else "S")

            lon_deg, lon_min, lon_sec = decimal_to_dms(lon_f)
            self.lon_deg_edit.setText(str(lon_deg))
            self.lon_min_edit.setText(str(lon_min))
            self.lon_sec_edit.setText(f"{lon_sec:.2f}".rstrip("0").rstrip("."))
            self.lon_dir_combo.setCurrentText("E" if lon_f >= 0 else "W")
        except Exception:
            pass

    def _sync_dms_to_dd(self) -> None:
        """Конвертация и перенос значений из полей DMS в поля DD."""
        try:
            lat_deg = self.lat_deg_edit.text()
            lat_min = self.lat_min_edit.text()
            lat_sec = self.lat_sec_edit.text()
            lat_dir = self.lat_dir_combo.currentText()

            lon_deg = self.lon_deg_edit.text()
            lon_min = self.lon_min_edit.text()
            lon_sec = self.lon_sec_edit.text()
            lon_dir = self.lon_dir_combo.currentText()

            lat_f, lon_f = CoordinateValidator.validate_dms_pair(
                (lat_deg, lat_min, lat_sec, lat_dir),
                (lon_deg, lon_min, lon_sec, lon_dir),
            )
            self.lat_edit.setText(f"{lat_f:.6f}".rstrip("0").rstrip("."))
            self.lon_edit.setText(f"{lon_f:.6f}".rstrip("0").rstrip("."))
        except Exception:
            pass

    def _on_style_input_changed(self) -> None:
        """Обновление интерактивного виджета предпросмотра при изменении стиля маркера."""
        symbol = self.symbol_combo.currentData() or "circle"
        size = self.size_spin.value()
        try:
            r = int(self.r_edit.text().strip())
            g = int(self.g_edit.text().strip())
            b = int(self.b_edit.text().strip())
            s_r = int(self.stroke_r_edit.text().strip())
            s_g = int(self.stroke_g_edit.text().strip())
            s_b = int(self.stroke_b_edit.text().strip())
            s_w = self.stroke_width_spin.value()
            op = float(self.marker_opacity_spin.value())
            if 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255:
                self.preview_widget.update_style(
                    symbol=symbol,
                    size=size,
                    red=r,
                    green=g,
                    blue=b,
                    stroke_red=s_r,
                    stroke_green=s_g,
                    stroke_blue=s_b,
                    stroke_width=s_w,
                    opacity=op,
                )
        except Exception:
            pass

    def _open_color_dialog(self) -> None:
        """Открытие диалога выбора цвета заливки маркера QColorDialog."""
        try:
            cur_r = int(self.r_edit.text().strip())
            cur_g = int(self.g_edit.text().strip())
            cur_b = int(self.b_edit.text().strip())
            initial_color = QColor(cur_r, cur_g, cur_b)
        except Exception:
            initial_color = QColor(220, 30, 30)

        color = QColorDialog.getColor(initial_color, self, tr("dialog.point.choose_color"))
        if color.isValid():
            self.r_edit.setText(str(color.red()))
            self.g_edit.setText(str(color.green()))
            self.b_edit.setText(str(color.blue()))
            self._on_style_input_changed()

    def _open_stroke_color_dialog(self) -> None:
        """Открытие диалога выбора цвета обводки маркера."""
        try:
            cur_r = int(self.stroke_r_edit.text().strip())
            cur_g = int(self.stroke_g_edit.text().strip())
            cur_b = int(self.stroke_b_edit.text().strip())
            initial_color = QColor(cur_r, cur_g, cur_b)
        except Exception:
            initial_color = QColor(255, 255, 255)

        color = QColorDialog.getColor(initial_color, self, tr("dialog.point.choose_color"))
        if color.isValid():
            self.stroke_r_edit.setText(str(color.red()))
            self.stroke_g_edit.setText(str(color.green()))
            self.stroke_b_edit.setText(str(color.blue()))
            self._on_style_input_changed()

    def _open_zone_color_dialog(self) -> None:
        """Открытие диалога выбора цвета заливки зоны QColorDialog."""
        try:
            cur_r = int(self.zone_r_edit.text().strip())
            cur_g = int(self.zone_g_edit.text().strip())
            cur_b = int(self.zone_b_edit.text().strip())
            initial_color = QColor(cur_r, cur_g, cur_b)
        except Exception:
            initial_color = QColor(220, 30, 30)

        color = QColorDialog.getColor(initial_color, self, tr("dialog.point.choose_color"))
        if color.isValid():
            self.zone_r_edit.setText(str(color.red()))
            self.zone_g_edit.setText(str(color.green()))
            self.zone_b_edit.setText(str(color.blue()))

    def _open_zone_border_color_dialog(self) -> None:
        """Открытие диалога выбора цвета границы зоны."""
        try:
            cur_r = int(self.zone_border_r_edit.text().strip())
            cur_g = int(self.zone_border_g_edit.text().strip())
            cur_b = int(self.zone_border_b_edit.text().strip())
            initial_color = QColor(cur_r, cur_g, cur_b)
        except Exception:
            initial_color = QColor(30, 58, 138)

        color = QColorDialog.getColor(initial_color, self, tr("dialog.point.choose_color"))
        if color.isValid():
            self.zone_border_r_edit.setText(str(color.red()))
            self.zone_border_g_edit.setText(str(color.green()))
            self.zone_border_b_edit.setText(str(color.blue()))

    def _validate_and_submit(self) -> None:
        """Проверка ввода координат, стиля, зоны, расширенной модели и проверка выхода центра за границы."""
        # 1. Валидация координат
        if self.rb_dd.isChecked():
            lat_text = self.lat_edit.text()
            lon_text = self.lon_edit.text()
            try:
                lat, lon = CoordinateValidator.validate_dd_pair(lat_text, lon_text)
            except ValueError as err:
                logger.warning("Ошибка валидации координат DD: %s", err)
                QMessageBox.warning(self, tr("common.warning"), str(err))
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
                QMessageBox.warning(self, tr("common.warning"), str(err))
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
            QMessageBox.warning(self, tr("common.warning"), str(err))
            return

        try:
            stroke_r, stroke_g, stroke_b = StyleValidator.validate_rgb(
                self.stroke_r_edit.text(),
                self.stroke_g_edit.text(),
                self.stroke_b_edit.text(),
            )
            stroke_w = validate_stroke_width(self.stroke_width_spin.value())
            marker_op = StyleValidator.validate_opacity(self.marker_opacity_spin.value())
        except ValueError as err:
            logger.warning("Ошибка валидации обводки/непрозрачности маркера: %s", err)
            QMessageBox.warning(self, tr("common.warning"), str(err))
            return

        # 3. Валидация зоны радиуса (Этап 7 и 17)
        zone_enabled = self.zone_chk.isChecked()
        if zone_enabled:
            raw_radius = self.zone_radius_edit.text()
            unit = self.zone_unit_combo.currentData() or self.zone_unit_combo.currentText()
            try:
                parsed_radius = GeodesicService.parse_radius(raw_radius, unit)
                radius_m = StyleValidator.validate_radius(parsed_radius, enabled=True)
            except ValueError as err:
                logger.warning("Ошибка валидации радиуса зоны: %s", err)
                QMessageBox.warning(self, tr("common.warning"), str(err))
                return

            try:
                z_r, z_g, z_b = StyleValidator.validate_rgb(
                    self.zone_r_edit.text(),
                    self.zone_g_edit.text(),
                    self.zone_b_edit.text(),
                )
            except ValueError as err:
                logger.warning("Ошибка валидации цвета зоны: %s", err)
                QMessageBox.warning(self, tr("common.warning"), str(err))
                return

            try:
                opacity = StyleValidator.validate_opacity(self.zone_opacity_spin.value())
            except ValueError as err:
                logger.warning("Ошибка валидации прозрачности зоны: %s", err)
                QMessageBox.warning(self, tr("common.warning"), str(err))
                return

            try:
                zb_r, zb_g, zb_b = StyleValidator.validate_rgb(
                    self.zone_border_r_edit.text(),
                    self.zone_border_g_edit.text(),
                    self.zone_border_b_edit.text(),
                )
                zb_w = validate_border_width(self.zone_border_width_spin.value())
                zb_style = validate_border_style(self.zone_border_style_combo.currentData() or "solid")
            except ValueError as err:
                logger.warning("Ошибка валидации границы зоны: %s", err)
                QMessageBox.warning(self, tr("common.warning"), str(err))
                return
        else:
            radius_m = 0.0
            z_r, z_g, z_b = 220, 30, 30
            opacity = 30
            zb_r, zb_g, zb_b = 30, 58, 138
            zb_w = 1.5
            zb_style = "solid"

        # 4. Валидация полей расширенной модели объекта (Этап 17)
        name = self.name_edit.text().strip()
        try:
            obj_number = validate_object_number(self.num_edit.text().strip())
            category = validate_category(self.cat_combo.currentText().strip())
            description = validate_description(self.desc_edit.toPlainText())
        except ValueError as err:
            logger.warning("Ошибка валидации расширенных свойств объекта: %s", err)
            QMessageBox.warning(self, tr("common.warning"), str(err))
            return

        # 5. Проверка выхода центра точки за пределы рабочей области карты
        is_inside = True
        if self._boundary_geometry is not None:
            is_inside = CoordinateService.is_point_inside_boundary(
                longitude=lon,
                latitude=lat,
                boundary_geometry=self._boundary_geometry,
            )
        elif self._map_extent is not None:
            mx, my = CoordinateService.transform_xy(lon, lat, "EPSG:4326", self._map_crs)
            is_inside = CoordinateService.is_point_inside_extent(mx, my, self._map_extent)

        if not is_inside:
            logger.info("Точка (%s, %s) вне рабочей области карты", lon, lat)
            map_name_str = self._map_name or "—"
            warn_msg = tr("msg.outside_map_warning", name=map_name_str)
            reply = QMessageBox.question(
                self,
                tr("msg.point_outside_title"),
                warn_msg,
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
            object_number=obj_number,
            description=description,
            category=category,
            stroke_red=stroke_r,
            stroke_green=stroke_g,
            stroke_blue=stroke_b,
            stroke_width=stroke_w,
            opacity=float(marker_op),
            zone_border_red=zb_r,
            zone_border_green=zb_g,
            zone_border_blue=zb_b,
            zone_border_width=zb_w,
            zone_border_style=zb_style,
            group_id=self.group_combo.currentData() if hasattr(self, "group_combo") else None,
        )
        super().accept()

    def accept(self) -> None:
        """Переопределение accept для выполнения полной валидации перед закрытием."""
        self._validate_and_submit()

    def get_point_data(self) -> PointDialogData | None:
        """Возвращает проверенные данные точки после успешного завершения."""
        return self._parsed_data

    get_data = get_point_data

    @property
    def group_id_result(self) -> str | None:
        """ID выбранной группы."""
        if hasattr(self, "group_combo"):
            idx = self.group_combo.currentIndex()
            if idx >= 0:
                return self.group_combo.itemData(idx)
        return None


# Псевдоним для обратной совместимости с тестами Этапов 4 и 5
AddPointDialog = PointDialog
