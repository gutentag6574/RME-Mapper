"""Панель отображения свойств выбранной пользовательской точки."""

import logging
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.i18n import get_translation_service, tr
from rme_mapper.models.map_point import MapPoint
from rme_mapper.services.geodesic_service import GeodesicService

logger = logging.getLogger("rme_mapper.ui.panels.properties_panel")

SYMBOL_DISPLAY_NAMES = {
    "circle": "Круг",
    "square": "Квадрат",
    "triangle": "Треугольник",
}


def get_symbol_display_name(symbol: str) -> str:
    """Получение локализованного названия формы маркера."""
    key = f"shape.{symbol}"
    ts = get_translation_service()
    if ts.has_translation(key):
        return ts.translate(key)
    return SYMBOL_DISPLAY_NAMES.get(symbol, symbol)


class PropertiesPanel(QWidget):
    """Презентационная панель свойств выбранной точки."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("propertiesPanel")

        self._current_point: MapPoint | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.title_label = QLabel()
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)

        self.placeholder = QFrame()
        self.placeholder.setObjectName("propertiesPlaceholder")
        self.placeholder.setFrameShape(QFrame.Shape.StyledPanel)
        self.placeholder.setFrameShadow(QFrame.Shadow.Sunken)

        placeholder_layout = QVBoxLayout(self.placeholder)
        placeholder_layout.setContentsMargins(10, 10, 10, 10)
        placeholder_layout.setSpacing(8)

        # Сообщение, если точка не выбрана
        self.prop_empty_label = QLabel()
        self.prop_empty_label.setObjectName("propEmptyLabel")
        self.prop_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prop_empty_label.setStyleSheet("color: #6B7280; font-size: 12px; padding: 20px 8px;")
        self.prop_empty_label.setWordWrap(True)
        placeholder_layout.addWidget(self.prop_empty_label)

        # Контейнер свойств выбранной точки
        self.prop_container = QWidget()
        self.prop_container.setObjectName("propContainer")
        prop_vbox = QVBoxLayout(self.prop_container)
        prop_vbox.setContentsMargins(0, 0, 0, 0)
        prop_vbox.setSpacing(8)

        # 0. Название точки
        name_form = QFormLayout()
        name_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.prop_name_lbl = QLabel()
        self.prop_name_val = QLabel("—")
        self.prop_name_val.setWordWrap(True)
        self.prop_name_val.setStyleSheet("font-weight: 600; color: #1E293B;")
        name_form.addRow(self.prop_name_lbl, self.prop_name_val)
        prop_vbox.addLayout(name_form)

        # 1. Раздел: Координаты
        self.sec_coords_lbl = QLabel()
        self.sec_coords_lbl.setObjectName("secCoordsLabel")
        self.sec_coords_lbl.setStyleSheet(
            "font-weight: 700; color: #475569; font-size: 11px; "
            "border-bottom: 1px solid #E2E8F0; padding-bottom: 2px;"
        )
        prop_vbox.addWidget(self.sec_coords_lbl)

        coords_form = QFormLayout()
        coords_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        coords_form.setSpacing(4)
        self.prop_lat_lbl = QLabel()
        self.prop_lat_val = QLabel("—")
        coords_form.addRow(self.prop_lat_lbl, self.prop_lat_val)

        self.prop_lon_lbl = QLabel()
        self.prop_lon_val = QLabel("—")
        coords_form.addRow(self.prop_lon_lbl, self.prop_lon_val)
        prop_vbox.addLayout(coords_form)

        # 2. Раздел: Маркер
        self.sec_marker_lbl = QLabel()
        self.sec_marker_lbl.setObjectName("secMarkerLabel")
        self.sec_marker_lbl.setStyleSheet(
            "font-weight: 700; color: #475569; font-size: 11px; "
            "border-bottom: 1px solid #E2E8F0; padding-bottom: 2px;"
        )
        prop_vbox.addWidget(self.sec_marker_lbl)

        marker_form = QFormLayout()
        marker_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        marker_form.setSpacing(4)
        self.prop_shape_lbl = QLabel()
        self.prop_shape_val = QLabel("—")
        marker_form.addRow(self.prop_shape_lbl, self.prop_shape_val)

        self.prop_size_lbl = QLabel()
        self.prop_size_val = QLabel("—")
        marker_form.addRow(self.prop_size_lbl, self.prop_size_val)

        color_row = QHBoxLayout()
        self.prop_color_val = QLabel("—")
        self.prop_color_swatch = QFrame()
        self.prop_color_swatch.setFixedSize(18, 18)
        self.prop_color_swatch.setStyleSheet("border: 1px solid #999; border-radius: 3px;")
        color_row.addWidget(self.prop_color_val)
        color_row.addWidget(self.prop_color_swatch)
        color_row.addStretch()
        self.prop_color_lbl = QLabel()
        marker_form.addRow(self.prop_color_lbl, color_row)
        prop_vbox.addLayout(marker_form)

        # 3. Раздел: Зона
        self.sec_zone_lbl = QLabel()
        self.sec_zone_lbl.setObjectName("secZoneLabel")
        self.sec_zone_lbl.setStyleSheet(
            "font-weight: 700; color: #475569; font-size: 11px; "
            "border-bottom: 1px solid #E2E8F0; padding-bottom: 2px;"
        )
        prop_vbox.addWidget(self.sec_zone_lbl)

        zone_form = QFormLayout()
        zone_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        zone_form.setSpacing(4)
        self.prop_zone_lbl = QLabel()
        self.prop_zone_val = QLabel("—")
        zone_form.addRow(self.prop_zone_lbl, self.prop_zone_val)

        self.prop_zone_radius_lbl = QLabel()
        self.prop_zone_radius_val = QLabel("—")
        zone_form.addRow(self.prop_zone_radius_lbl, self.prop_zone_radius_val)

        zone_color_row = QHBoxLayout()
        self.prop_zone_color_val = QLabel("—")
        self.prop_zone_color_swatch = QFrame()
        self.prop_zone_color_swatch.setFixedSize(18, 18)
        self.prop_zone_color_swatch.setStyleSheet("border: 1px solid #999; border-radius: 3px;")
        zone_color_row.addWidget(self.prop_zone_color_val)
        zone_color_row.addWidget(self.prop_zone_color_swatch)
        zone_color_row.addStretch()
        self.prop_zone_color_lbl = QLabel()
        zone_form.addRow(self.prop_zone_color_lbl, zone_color_row)

        self.prop_zone_opacity_lbl = QLabel()
        self.prop_zone_opacity_val = QLabel("—")
        zone_form.addRow(self.prop_zone_opacity_lbl, self.prop_zone_opacity_val)
        prop_vbox.addLayout(zone_form)

        self.prop_container.setVisible(False)
        placeholder_layout.addWidget(self.prop_container)
        placeholder_layout.addStretch()

        layout.addWidget(self.placeholder, stretch=1)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        """Обновление локализованных меток и динамических значений."""
        self.title_label.setText(tr("panel.properties"))
        self.prop_empty_label.setText(tr("properties.empty_hint"))

        self.sec_coords_lbl.setText(tr("properties.section_coords"))
        self.sec_marker_lbl.setText(tr("properties.section_marker"))
        self.sec_zone_lbl.setText(tr("properties.section_zone"))

        self.prop_name_lbl.setText(f"<b>{tr('properties.name')}</b>")
        self.prop_lat_lbl.setText(f"<b>{tr('properties.latitude')}</b>")
        self.prop_lon_lbl.setText(f"<b>{tr('properties.longitude')}</b>")
        self.prop_shape_lbl.setText(f"<b>{tr('properties.shape')}</b>")
        self.prop_size_lbl.setText(f"<b>{tr('properties.size')}</b>")
        self.prop_color_lbl.setText(f"<b>{tr('properties.color')}</b>")
        self.prop_zone_lbl.setText(f"<b>{tr('properties.zone')}</b>")
        self.prop_zone_radius_lbl.setText(f"<b>{tr('properties.radius')}</b>")
        self.prop_zone_color_lbl.setText(f"<b>{tr('properties.zone_color')}</b>")
        self.prop_zone_opacity_lbl.setText(f"<b>{tr('properties.opacity')}</b>")

        if self._current_point is not None:
            self._render_point_data(self._current_point)

    def update_properties(self, point: MapPoint | None) -> None:
        """Отображение свойств переданной точки."""
        self._current_point = point
        if point is None:
            self.clear()
            return

        self.prop_empty_label.setVisible(False)
        self.prop_container.setVisible(True)
        self._render_point_data(point)

    def _render_point_data(self, point: MapPoint) -> None:
        self.prop_name_val.setText(point.name)
        self.prop_lat_val.setText(f"{point.latitude:.6f}")
        self.prop_lon_val.setText(f"{point.longitude:.6f}")
        self.prop_shape_val.setText(get_symbol_display_name(point.symbol))
        self.prop_size_val.setText(f"{point.size:.1f} px")
        self.prop_color_val.setText(f"RGB({point.red}, {point.green}, {point.blue})")
        self.prop_color_swatch.setStyleSheet(
            f"background-color: rgb({point.red}, {point.green}, {point.blue}); "
            f"border: 1px solid #777; border-radius: 3px;"
        )

        self.prop_zone_val.setText(tr("common.yes") if point.zone_enabled else tr("common.no"))
        if point.zone_enabled:
            self.prop_zone_radius_val.setText(GeodesicService.format_radius(point.radius_m, True))
            self.prop_zone_color_val.setText(f"RGB({point.zone_red}, {point.zone_green}, {point.zone_blue})")
            self.prop_zone_color_swatch.setStyleSheet(
                f"background-color: rgb({point.zone_red}, {point.zone_green}, {point.zone_blue}); "
                f"border: 1px solid #777; border-radius: 3px;"
            )
            self.prop_zone_opacity_val.setText(f"{point.zone_opacity}%")
        else:
            self.prop_zone_radius_val.setText("—")
            self.prop_zone_color_val.setText("—")
            self.prop_zone_color_swatch.setStyleSheet(
                "background-color: transparent; border: 1px solid #ccc; border-radius: 3px;"
            )
            self.prop_zone_opacity_val.setText("—")

    def clear(self) -> None:
        """Очистка панели свойств при отсутствии выбора."""
        self._current_point = None
        self.prop_container.setVisible(False)
        self.prop_empty_label.setVisible(True)
