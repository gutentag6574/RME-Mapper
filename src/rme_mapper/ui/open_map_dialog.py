"""Универсальный диалог открытия карты и импорта слоев GeoPackage (OpenMapDialog)."""
from __future__ import annotations


import logging
from pathlib import Path
from typing import Any
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
import pyproj
from rme_mapper.i18n import tr

from rme_mapper.backends import MapDataBackend, get_backend, BackendFactory, get_raster_backend
from rme_mapper.maps.map_config import get_project_root
from rme_mapper.models.map_profile import MapProfile
from rme_mapper.services.geopackage_service import GeoPackageService
from rme_mapper.services.map_catalog_service import MapCatalogService

logger = logging.getLogger("rme_mapper.ui.open_map_dialog")


def _format_crs_string(raw_crs: Any) -> str:
    """Форматирование CRS в читаемую строку."""
    if not raw_crs:
        return "OGC:CRS84"
    try:
        parsed = pyproj.CRS.from_user_input(raw_crs)
        epsg = parsed.to_epsg()
        if epsg:
            return f"EPSG:{epsg} ({parsed.name})"
        to_str = parsed.to_string()
        if to_str:
            return f"{to_str} ({parsed.name})"
        return parsed.name
    except Exception:
        return str(raw_crs)


def _extract_clean_crs(raw_crs: Any, formatted_crs: str) -> str:
    """Извлечь валидную строку CRS без отображаемого суффикса ' (name)'."""
    for candidate in (raw_crs, formatted_crs):
        if not candidate:
            continue
        text = str(candidate).strip()
        if not text:
            continue
        try:
            parsed = pyproj.CRS.from_user_input(text)
            epsg = parsed.to_epsg()
            if epsg:
                return f"EPSG:{epsg}"
            auth = parsed.to_authority()
            if auth and len(auth) == 2:
                return f"{auth[0]}:{auth[1]}"
            return parsed.to_string() or text
        except Exception:
            if " (" in text and text.endswith(")"):
                stripped = text.rsplit(" (", 1)[0].strip()
                try:
                    parsed = pyproj.CRS.from_user_input(stripped)
                    epsg = parsed.to_epsg()
                    if epsg:
                        return f"EPSG:{epsg}"
                    auth = parsed.to_authority()
                    if auth and len(auth) == 2:
                        return f"{auth[0]}:{auth[1]}"
                    return parsed.to_string() or stripped
                except Exception:
                    pass
    return "OGC:CRS84"


def _get_default_layer_style(geometry_type: str, is_boundary: bool = False) -> dict[str, Any]:
    """Генерация приятного стиля по умолчанию на основе типа геометрии слоя."""
    geom = (geometry_type or "").lower()
    if is_boundary:
        return {
            "border_color": "#2A5B84",
            "fill_color": "#DCEEF8",
            "border_width": 1.5,
        }
    if "polygon" in geom:
        return {
            "border_color": "#4A5568",
            "fill_color": "#E2E8F0",
            "border_width": 0.5,
        }
    if "line" in geom:
        return {
            "border_color": "#C2593F",
            "fill_color": None,
            "border_width": 1.0,
        }
    if "point" in geom:
        return {
            "border_color": "#1E40AF",
            "fill_color": "#3B82F6",
            "border_width": 1.0,
            "point_radius": 4.0,
        }
    return {
        "border_color": "#475569",
        "fill_color": None,
        "border_width": 1.0,
    }


class OpenMapDialog(QDialog):
    """Диалог выбора и импорта карты из файла GeoPackage (*.gpkg) или каталога профилей."""

    def __init__(
        self,
        parent: QWidget | None = None,
        catalog_service: MapCatalogService | None = None,
        initial_file_path: Path | str | None = None,
        backend: MapDataBackend | None = None,
        initial_dir: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Открыть карту — GeoPoint Mapper")
        self.resize(680, 560)
        self.setModal(True)

        self._catalog_service = catalog_service or MapCatalogService()
        self._backend: MapDataBackend = backend or get_backend()
        self._initial_file_path = Path(initial_file_path) if initial_file_path else None
        self._initial_dir = Path(initial_dir) if initial_dir else None


        # Выбранный профиль в результате закрытия
        self._selected_profile: MapProfile | None = None

        # Структура слоев выбранного GeoPackage / GeoTIFF: list of dict
        self._inspected_layers: list[dict[str, Any]] = []
        self._inspected_crs_str: str = "OGC:CRS84"
        self._inspected_crs_raw: Any = None
        self._current_gpkg_path: Path | None = None
        self._is_raster: bool = False
        self._raster_info: dict[str, Any] = {}

        self._setup_ui()
        self.retranslate_ui()

        # Если был передан начальный файл, сразу исследуем его
        if self._initial_file_path and self._initial_file_path.exists():
            self._set_file_path(self._initial_file_path)

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # 1. Переключатель источника
        self.mode_group = QGroupBox("Источник карты", self)
        mode_layout = QHBoxLayout(self.mode_group)
        self.rb_file = QRadioButton("Файл GeoPackage (*.gpkg)", self.mode_group)
        self.rb_file.setObjectName("rbModeFile")
        self.rb_file.setChecked(True)
        self.rb_file.toggled.connect(self._on_mode_changed)

        self.rb_catalog = QRadioButton("Каталог профилей", self.mode_group)
        self.rb_catalog.setObjectName("rbModeCatalog")
        self.rb_catalog.toggled.connect(self._on_mode_changed)

        mode_layout.addWidget(self.rb_file)
        mode_layout.addWidget(self.rb_catalog)
        main_layout.addWidget(self.mode_group)

        # 2. Стек страниц: 0 = Файл, 1 = Каталог
        self.stack = QStackedWidget(self)

        # --- Страница 0: Прямое открытие GeoPackage ---
        page_file = QWidget(self.stack)
        page_file_layout = QVBoxLayout(page_file)
        page_file_layout.setContentsMargins(0, 0, 0, 0)
        page_file_layout.setSpacing(10)

        # Выбор файла
        file_row = QHBoxLayout()
        self.file_lbl = QLabel("Файл:", page_file)
        self.file_path_edit = QLineEdit(page_file)
        self.file_path_edit.setObjectName("filePathEdit")
        self.file_path_edit.setPlaceholderText("Укажите путь к файлу *.gpkg...")
        self.file_path_edit.setReadOnly(True)

        self.btn_browse = QPushButton("Обзор...", page_file)
        self.btn_browse.setObjectName("btnBrowseMapFile")
        self.btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse.clicked.connect(self._on_browse_clicked)

        file_row.addWidget(self.file_lbl)
        file_row.addWidget(self.file_path_edit, stretch=1)
        file_row.addWidget(self.btn_browse)
        page_file_layout.addLayout(file_row)

        # Информация о CRS
        self.crs_info_label = QLabel("CRS: —", page_file)
        self.crs_info_label.setObjectName("crsInfoLabel")
        self.crs_info_label.setStyleSheet("color: #334155; font-weight: 500;")
        page_file_layout.addWidget(self.crs_info_label)

        # Таблица слоев
        self.layers_box = QGroupBox("Слои GeoPackage для отображения", page_file)
        layers_layout = QVBoxLayout(self.layers_box)

        # Панель кнопок "Выбрать все" / "Снять все"
        tbl_btn_row = QHBoxLayout()
        self.btn_sel_all = QPushButton("Выбрать все", self.layers_box)
        self.btn_sel_all.clicked.connect(self._select_all_layers)
        self.btn_desel_all = QPushButton("Снять все", self.layers_box)
        self.btn_desel_all.clicked.connect(self._deselect_all_layers)
        tbl_btn_row.addWidget(self.btn_sel_all)
        tbl_btn_row.addWidget(self.btn_desel_all)
        tbl_btn_row.addStretch()
        layers_layout.addLayout(tbl_btn_row)

        self.layers_table = QTableWidget(0, 4, self.layers_box)
        self.layers_table.setObjectName("layersTable")
        self.layers_table.setHorizontalHeaderLabels(["", "Слой", "Тип геометрии", "Объектов"])
        self.layers_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.layers_table.verticalHeader().setVisible(False)
        self.layers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.layers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.layers_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.layers_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layers_layout.addWidget(self.layers_table)

        # Выбор рабочей границы
        boundary_row = QHBoxLayout()
        self.boundary_lbl = QLabel("Рабочая граница (опционально):", self.layers_box)
        self.boundary_combo = QComboBox(self.layers_box)
        self.boundary_combo.setObjectName("boundaryCombo")
        self.boundary_combo.addItem("— Не использовать границу —", None)
        boundary_row.addWidget(self.boundary_lbl)
        boundary_row.addWidget(self.boundary_combo, stretch=1)
        layers_layout.addLayout(boundary_row)

        page_file_layout.addWidget(self.layers_box, stretch=1)
        self.stack.addWidget(page_file)

        # --- Страница 1: Каталог профилей ---
        page_catalog = QWidget(self.stack)
        page_cat_layout = QVBoxLayout(page_catalog)
        page_cat_layout.setContentsMargins(0, 0, 0, 0)
        page_cat_layout.setSpacing(10)

        self.cat_lbl = QLabel("Доступные профили карт:", page_catalog)
        page_cat_layout.addWidget(self.cat_lbl)


        self.catalog_combo = QComboBox(page_catalog)
        self.catalog_combo.setObjectName("catalogCombo")
        self.catalog_combo.currentIndexChanged.connect(self._on_catalog_profile_changed)
        page_cat_layout.addWidget(self.catalog_combo)

        self.cat_info_label = QLabel("", page_catalog)
        self.cat_info_label.setWordWrap(True)
        self.cat_info_label.setStyleSheet("color: #475569; padding: 10px; background: #F1F5F9; border-radius: 6px;")
        page_cat_layout.addWidget(self.cat_info_label, stretch=1)

        self.stack.addWidget(page_catalog)
        main_layout.addWidget(self.stack, stretch=1)

        # 3. Нижние кнопки: "Открыть карту" и "Отмена"
        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_cancel = QPushButton("Отмена", self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_open = QPushButton("Открыть карту", self)
        self.btn_open.setObjectName("btnOpenMapConfirm")
        self.btn_open.setDefault(True)
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open.setStyleSheet(
            """
            QPushButton#btnOpenMapConfirm {
                background-color: #2563EB;
                color: #FFFFFF;
                font-weight: bold;
                padding: 6px 18px;
                border-radius: 4px;
            }
            QPushButton#btnOpenMapConfirm:hover {
                background-color: #1D4ED8;
            }
            """
        )
        self.btn_open.clicked.connect(self._on_accept_clicked)
        btn_box.addWidget(self.btn_open)

        main_layout.addLayout(btn_box)

        # Заполняем профили каталога
        self._populate_catalog_profiles()

    def retranslate_ui(self) -> None:
        """Обновление локализованных текстов диалога открытия карты."""
        from rme_mapper.i18n import tr

        self.setWindowTitle(tr("dialog.map.title"))
        if hasattr(self, "mode_group"):
            self.mode_group.setTitle(tr("dialog.map.source_group"))
        if hasattr(self, "rb_file"):
            self.rb_file.setText(tr("dialog.map.source_file"))
        if hasattr(self, "rb_catalog"):
            self.rb_catalog.setText(tr("dialog.map.source_catalog"))
        if hasattr(self, "file_lbl"):
            self.file_lbl.setText(tr("dialog.map.file"))
        if hasattr(self, "file_path_edit"):
            self.file_path_edit.setPlaceholderText(tr("dialog.map.file_placeholder"))
        if hasattr(self, "btn_browse"):
            self.btn_browse.setText(tr("dialog.map.browse"))
        if hasattr(self, "crs_info_label"):
            crs_disp = getattr(self, "_inspected_crs_str", "—")
            self.crs_info_label.setText(tr("dialog.map.crs_info", crs=crs_disp))
        if hasattr(self, "layers_box"):
            self.layers_box.setTitle(tr("dialog.map.layers_box"))
        if hasattr(self, "btn_sel_all"):
            self.btn_sel_all.setText(tr("common.select_all"))
        if hasattr(self, "btn_desel_all"):
            self.btn_desel_all.setText(tr("common.deselect_all"))
        if hasattr(self, "layers_table"):
            self.layers_table.setHorizontalHeaderLabels([
                "",
                tr("dialog.map.col_name"),
                tr("dialog.map.col_geom"),
                tr("dialog.map.col_features"),
            ])
        if hasattr(self, "boundary_lbl"):
            self.boundary_lbl.setText(tr("dialog.map.working_boundary"))
        if hasattr(self, "boundary_combo") and self.boundary_combo.count() > 0:
            self.boundary_combo.setItemText(0, tr("dialog.map.no_boundary"))
        if hasattr(self, "cat_lbl"):
            self.cat_lbl.setText(tr("dialog.map.catalog_profiles"))
        if hasattr(self, "btn_cancel"):
            self.btn_cancel.setText(tr("common.cancel"))
        if hasattr(self, "btn_open"):
            self.btn_open.setText(tr("dialog.map.btn_open"))

    def _on_mode_changed(self) -> None:

        """Переключение между выбором файла и каталогом."""
        if self.rb_file.isChecked():
            self.stack.setCurrentIndex(0)
        else:
            self.stack.setCurrentIndex(1)

    def _on_browse_clicked(self) -> None:
        """Диалог выбора файла GeoPackage или GeoTIFF на диске."""
        root_dir = (
            str(self._initial_dir)
            if (self._initial_dir and self._initial_dir.is_dir())
            else str(get_project_root())
        )
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("dialog.map.select_file_title"),
            root_dir,
            tr("dialog.map.filter_all_maps"),
        )
        if file_path:
            self._set_file_path(Path(file_path))

    def _launch_georeference_dialog(self, path: Path) -> None:
        """Запуск интерактивного диалога геопривязки изображения."""
        from uuid import uuid4
        from rme_mapper.ui.georeference_dialog import GeoreferenceDialog
        from rme_mapper.models.map_profile import MapProfile

        try:
            dlg = GeoreferenceDialog(path, parent=self)
        except Exception as exc:
            QMessageBox.critical(self, tr("dialog.georef.title"), str(exc))
            return
        path = dlg.image_path
        if dlg.exec() == QDialog.DialogCode.Accepted:
            affine = dlg.get_affine_transform()
            cps = [p.to_dict() for p in dlg.get_control_points()]
            crs_val = dlg.get_crs()
            extent_dict = dlg.get_extent()
            profile = MapProfile(
                id=f"georef_{uuid4().hex[:8]}",
                name=path.stem,
                source_type="georeferenced_image",
                source_path=str(path.resolve()),
                base_dir=path.parent,
                crs=crs_val,
                boundary_layer=None,
                boundary_required=False,
                extent=extent_dict,
                affine_transform=list(affine),
                control_points=cps,
                transformation_type="affine",
                layers=[{
                    "id": "raster_base",
                    "name": "raster",
                    "source_name": "raster",
                    "display_name": path.stem,
                    "geometry_type": "raster",
                    "visible": True,
                    "crs": crs_val,
                }],
            )
            self._selected_profile = profile
            self.accept()

    def _set_file_path(self, path: Path) -> None:
        """Исследование структуры файла карты (GeoPackage, GeoTIFF или растровые изображения) и обновление интерфейса."""
        from rme_mapper.i18n import tr

        if not path.is_file():
            QMessageBox.warning(
                self,
                tr("dialog.error_title"),
                tr("dialog.open_map.file_not_exists", path=path),
            )
            return

        # Clear previous selection before inspecting another file.
        self._selected_profile = None
        self._inspected_layers = []
        self._is_raster = False
        self._raster_info = {}
        self.layers_table.setRowCount(0)
        from rme_mapper.services.georeference_service import GeoreferenceService, WORLD_FILE_EXTENSIONS
        if path.suffix.lower() in WORLD_FILE_EXTENSIONS | {".png", ".jpg", ".jpeg"}:
            try:
                binding = GeoreferenceService.read_world_file(path)
            except Exception as exc:
                QMessageBox.critical(self, tr("dialog.georef.title"), str(exc))
                return
            if binding:
                self._launch_georeference_dialog(path)
                return

        self._current_gpkg_path = path
        self.file_path_edit.setText(str(path))
        ext = path.suffix.lower()

        # -------------------------------------------------------------
        # 1. Обработка обычных изображений без привязки (*.png, *.jpg, *.jpeg)
        # -------------------------------------------------------------
        if ext in (".png", ".jpg", ".jpeg"):
            ret = QMessageBox.question(
                self,
                tr("msg.georef_offer_title") or "Геопривязка изображения",
                (tr("msg.georef_offer_prompt") or "Файл «{name}» не содержит географической привязки.\n\nЖелаете геопривязать изображение вручную по контрольным точкам?").format(name=path.name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret == QMessageBox.StandardButton.Yes:
                self._launch_georeference_dialog(path)
            return

        # -------------------------------------------------------------
        # 2. Обработка растровой карты GeoTIFF (*.tif, *.tiff)
        # -------------------------------------------------------------
        if ext in (".tif", ".tiff"):
            if not BackendFactory.supports_geotiff():
                QMessageBox.critical(
                    self,
                    "Ошибка",
                    tr("msg.geotiff_backend_unavailable") or "Поддержка GeoTIFF недоступна в этой сборке.",
                )
                return

            rb = get_raster_backend()
            try:
                info = rb.inspect_raster(path)
            except Exception as e:
                logger.exception("Ошибка инспекции GeoTIFF %s: %s", path, e)
                QMessageBox.critical(self, "Ошибка чтения GeoTIFF", f"Не удалось прочитать файл:\n{path}\n\n{e}")
                return

            # Проверка наличия CRS и геопривязки в GeoTIFF; если отсутствуют, проверяем world-файл
            if not info.get("crs") or not info.get("is_valid_georef"):
                try:
                    binding = GeoreferenceService.read_world_file(path)
                except Exception as exc:
                    QMessageBox.critical(self, tr("dialog.georef.title"), str(exc))
                    return
                if binding:
                    self._launch_georeference_dialog(path)
                    return
                ret = QMessageBox.question(
                    self,
                    tr("msg.georef_offer_title") or "Геопривязка изображения",
                    (tr("msg.georef_offer_prompt") or "Файл «{name}» не содержит географической привязки.\n\nЖелаете геопривязать изображение вручную по контрольным точкам?").format(name=path.name),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if ret == QMessageBox.StandardButton.Yes:
                    self._launch_georeference_dialog(path)
                return

            self._is_raster = True
            self._raster_info = info
            self._inspected_crs_raw = info["crs"]
            self._inspected_crs_str = _format_crs_string(info["crs"])

            # Отображение расширенной информации о растре
            nd_val = info.get("nodata")
            nd_disp = str(nd_val) if nd_val is not None else "—"
            self.crs_info_label.setText(
                f"Тип: GeoTIFF | Размер: {info['width']} × {info['height']} px | Каналы: {info['band_count']} | CRS: {self._inspected_crs_str} | NoData: {nd_disp}"
            )

            # Таблица слоев для растра (1 слой)
            self._inspected_layers = [{
                "name": "raster",
                "geometry_type": "Растр",
                "features_count": 1,
                "crs": info["crs"],
            }]
            self.layers_table.setRowCount(0)
            self.layers_table.insertRow(0)

            chk = QCheckBox()
            chk.setChecked(True)
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.layers_table.setCellWidget(0, 0, chk_widget)

            name_item = QTableWidgetItem(path.stem)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.layers_table.setItem(0, 1, name_item)

            geom_item = QTableWidgetItem("Растр")
            geom_item.setFlags(geom_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.layers_table.setItem(0, 2, geom_item)

            cnt_item = QTableWidgetItem(f"{info['width']} × {info['height']}")
            cnt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cnt_item.setFlags(cnt_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.layers_table.setItem(0, 3, cnt_item)

            self.boundary_combo.clear()
            self.boundary_combo.addItem("— Не используется для растра —", None)
            self.boundary_combo.setEnabled(False)
            return

        # -------------------------------------------------------------
        # 2. Обработка векторной карты GeoPackage (*.gpkg)
        # -------------------------------------------------------------
        self._is_raster = False
        self._raster_info.clear()
        self.boundary_combo.setEnabled(True)

        try:
            raw_layers = self._backend.list_layers(path)
        except Exception as e:
            logger.exception("Ошибка чтения слоев из %s: %s", path, e)
            QMessageBox.critical(self, "Ошибка чтения GeoPackage", f"Не удалось прочитать слои из файла:\n{path}\n\n{e}")
            return

        self._inspected_layers.clear()
        self.layers_table.setRowCount(0)
        self.boundary_combo.clear()
        self.boundary_combo.addItem("— Не использовать границу —", None)

        found_crs_raw = None
        polygon_layers: list[str] = []

        for name, geom_type in raw_layers:
            try:
                meta = self._backend.get_layer_metadata(path, name)
                feat_cnt = meta.get("features_count", 0)
                crs_val = meta.get("crs")
                if crs_val and not found_crs_raw:
                    found_crs_raw = crs_val
            except Exception:
                feat_cnt = 0
                crs_val = None

            layer_info = {
                "name": name,
                "geometry_type": geom_type,
                "features_count": feat_cnt,
                "crs": crs_val,
            }
            self._inspected_layers.append(layer_info)

            # Добавляем строку в таблицу
            row = self.layers_table.rowCount()
            self.layers_table.insertRow(row)

            chk = QCheckBox()
            chk.setChecked(True)
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self.layers_table.setCellWidget(row, 0, chk_widget)

            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.layers_table.setItem(row, 1, name_item)

            geom_item = QTableWidgetItem(geom_type)
            geom_item.setFlags(geom_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.layers_table.setItem(row, 2, geom_item)

            cnt_item = QTableWidgetItem(str(feat_cnt))
            cnt_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cnt_item.setFlags(cnt_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.layers_table.setItem(row, 3, cnt_item)

            if "polygon" in (geom_type or "").lower():
                polygon_layers.append(name)
                self.boundary_combo.addItem(f"{name} ({feat_cnt} полигонов)", name)

        # Отображение CRS
        self._inspected_crs_raw = found_crs_raw
        self._inspected_crs_str = _format_crs_string(found_crs_raw)
        self.crs_info_label.setText(f"CRS карты: {self._inspected_crs_str}")

        # Автоматический выбор слоя границы, если найден подходящий
        try:
            suggested_bnd = self._backend.find_boundary_layer(path)
            if suggested_bnd:
                for idx in range(self.boundary_combo.count()):
                    if self.boundary_combo.itemData(idx) == suggested_bnd:
                        self.boundary_combo.setCurrentIndex(idx)
                        break
        except Exception:
            pass

    def _select_all_layers(self) -> None:
        """Отметить все слои для отображения."""
        for row in range(self.layers_table.rowCount()):
            chk_widget = self.layers_table.cellWidget(row, 0)
            if chk_widget:
                chk = chk_widget.findChild(QCheckBox)
                if chk:
                    chk.setChecked(True)

    def _deselect_all_layers(self) -> None:
        """Снять выбор со всех слоев."""
        for row in range(self.layers_table.rowCount()):
            chk_widget = self.layers_table.cellWidget(row, 0)
            if chk_widget:
                chk = chk_widget.findChild(QCheckBox)
                if chk:
                    chk.setChecked(False)

    def _populate_catalog_profiles(self) -> None:
        """Заполнение выпадающего списка профилей из MapCatalogService."""
        self.catalog_combo.clear()
        profiles = self._catalog_service.discover_profiles()
        if not profiles:
            self.catalog_combo.addItem("Профили не найдены", None)
            self.cat_info_label.setText("В каталоге карт профили не найдены.")
            return

        for prof in profiles:
            self.catalog_combo.addItem(f"{prof.name} ({prof.id})", prof)

        self._on_catalog_profile_changed()

    def _on_catalog_profile_changed(self) -> None:
        """Обновление описания выбранного профиля каталога."""
        prof: MapProfile | None = self.catalog_combo.currentData()
        if not prof:
            self.cat_info_label.setText("")
            return

        layers_names = [l.get("display_name") or l.get("name") or l.get("source_name") for l in prof.layers]
        info_lines = [
            f"<b>Название:</b> {prof.name}",
            f"<b>Идентификатор:</b> {prof.id}",
            f"<b>Источник:</b> {prof.source_path}",
            f"<b>CRS:</b> {prof.crs or 'Не указан'}",
            f"<b>Слои ({len(prof.layers)}):</b> {', '.join(str(n) for n in layers_names if n)}",
        ]
        if prof.boundary_layer:
            info_lines.append(f"<b>Рабочая граница:</b> {prof.boundary_layer}")
        if prof.description:
            info_lines.append(f"<b>Описание:</b> {prof.description}")

        self.cat_info_label.setText("<br>".join(info_lines))

    def _on_accept_clicked(self) -> None:
        """Валидация выбора и формирование MapProfile."""
        from rme_mapper.i18n import tr

        if self.rb_file.isChecked():
            if not self._current_gpkg_path or not self._current_gpkg_path.is_file():
                QMessageBox.warning(self, "Файл не выбран", "Пожалуйста, выберите файл карты.")
                return

            if self._is_raster:
                # Проверяем выбран ли растровый слой
                chk_widget = self.layers_table.cellWidget(0, 0)
                if chk_widget:
                    chk = chk_widget.findChild(QCheckBox)
                    if chk and not chk.isChecked():
                        QMessageBox.warning(
                            self,
                            "Слои не выбраны",
                            "Выберите растровый слой для отображения на карте.",
                        )
                        return

                runtime_id = f"runtime_{uuid.uuid4().hex[:8]}"
                clean_crs = self._raster_info.get("crs") or "OGC:CRS84"

                self._selected_profile = MapProfile(
                    id=runtime_id,
                    name=self._current_gpkg_path.stem,
                    description=f"Пользовательская растровая карта из файла {self._current_gpkg_path.name}",
                    source_type="geotiff",
                    source_path=str(self._current_gpkg_path.resolve()),
                    base_dir=self._current_gpkg_path.parent,
                    crs=clean_crs,
                    boundary_layer=None,
                    boundary_required=False,
                    extent=self._raster_info.get("extent"),
                    layers=[{
                        "id": "raster_base",
                        "name": "raster",
                        "source_name": "raster",
                        "display_name": tr("layer.raster") or "Растр",
                        "geometry_type": "raster",
                        "role": "raster",
                        "visible": True,
                        "style": {"border_color": "#000000", "fill_color": None, "border_width": 0.0},
                        "z_order": 5,
                    }],
                )
                self.accept()
                return

            # Проверяем, какие слои выбраны (GeoPackage)
            selected_layer_names: list[str] = []
            for row in range(self.layers_table.rowCount()):
                chk_widget = self.layers_table.cellWidget(row, 0)
                if chk_widget:
                    chk = chk_widget.findChild(QCheckBox)
                    if chk and chk.isChecked():
                        item = self.layers_table.item(row, 1)
                        if item:
                            selected_layer_names.append(item.text())

            if not selected_layer_names:
                QMessageBox.warning(
                    self,
                    tr("dialog.open_map.no_layers_title"),
                    tr("dialog.open_map.no_layers_msg"),
                )
                return

            chosen_boundary = self.boundary_combo.currentData()

            # Формируем конфигурацию слоев для runtime-профиля
            profile_layers: list[dict[str, Any]] = []
            for idx, l_info in enumerate(self._inspected_layers):
                name = l_info["name"]
                if name not in selected_layer_names:
                    continue

                is_bnd = (chosen_boundary is not None and name == chosen_boundary)
                geom_type = l_info["geometry_type"]
                style = _get_default_layer_style(geom_type, is_boundary=is_bnd)

                layer_cfg: dict[str, Any] = {
                    "id": f"layer_{name}",
                    "name": name,
                    "source_name": name,
                    "display_name": name,
                    "geometry_type": geom_type,
                    "role": "boundary" if is_bnd else "other",
                    "visible": True,
                    "style": style,
                    "z_order": 10 if is_bnd else (20 + idx),
                }
                profile_layers.append(layer_cfg)

            # Формируем runtime-профиль
            runtime_id = f"runtime_{uuid.uuid4().hex[:8]}"
            clean_crs = _extract_clean_crs(self._inspected_crs_raw, self._inspected_crs_str)

            self._selected_profile = MapProfile(
                id=runtime_id,
                name=self._current_gpkg_path.stem,
                description=f"Пользовательская карта из файла {self._current_gpkg_path.name}",
                source_type="geopackage",
                source_path=str(self._current_gpkg_path.resolve()),
                base_dir=self._current_gpkg_path.parent,
                crs=clean_crs,
                boundary_layer=chosen_boundary,
                boundary_required=False,
                layers=profile_layers,
            )
            self.accept()

        else:
            # Выбор профиля из каталога
            prof = self.catalog_combo.currentData()
            if not isinstance(prof, MapProfile):
                QMessageBox.warning(self, "Профиль не выбран", "Пожалуйста, выберите профиль карты из каталога.")
                return

            self._selected_profile = prof
            self.accept()

    def load_file(self, path: Path) -> None:
        """Публичный метод загрузки файла GeoPackage в диалог для тестирования/скриптов."""
        self._set_file_path(Path(path))

    def build_profile(self) -> MapProfile | None:
        """Сформировать профиль карты на основе текущего состояния диалога."""
        self._on_accept_clicked()
        return self._selected_profile

    def get_map_profile(self) -> MapProfile | None:
        """Получение сформированного или выбранного профиля карты."""
        return self._selected_profile
