"""Главное окно приложения RME-Mapper."""

import logging
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QMainWindow,
    QMenuBar,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.maps.map_canvas import MapCanvas
from rme_mapper.maps.map_config import get_default_geopackage_path
from rme_mapper.models.map_layer import LayerRole, MapLayer
from rme_mapper.services.geopackage_service import GeoPackageService
from rme_mapper.services.layer_service import LayerService

logger = logging.getLogger("rme_mapper.ui.main_window")


class MainWindow(QMainWindow):
    """Главное окно приложения RME-Mapper."""

    DEFAULT_WIDTH = 1400
    DEFAULT_HEIGHT = 850

    def __init__(
        self,
        parent: QWidget | None = None,
        map_path: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("RME Mapper — Географическая привязка координат")
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

        self._map_path = Path(map_path) if map_path else get_default_geopackage_path()
        self._layer_service = LayerService()

        # Словарь чекбоксов слоев: layer_id -> QCheckBox
        self.layer_checkboxes: dict[str, QCheckBox] = {}
        self.loaded_layers: list[MapLayer] = []

        self._setup_ui()
        self.load_map(self._map_path)

    def _setup_ui(self) -> None:
        """Инициализация компонентов интерфейса."""
        self._create_menu_bar()
        self._create_central_layout()
        self._create_status_bar()

    def _create_menu_bar(self) -> None:
        """Создание верхнего меню приложения."""
        menu_bar = self.menuBar()

        # Меню: Файл
        self.file_menu = menu_bar.addMenu("Файл")
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        self.file_menu.addAction(exit_action)

        # Меню: Карта
        self.map_menu = menu_bar.addMenu("Карта")
        fit_action = QAction("Показать всю карту", self)
        fit_action.triggered.connect(lambda: self.map_canvas.fit_to_view())
        self.map_menu.addAction(fit_action)

        # Меню: Координаты
        self.coords_menu = menu_bar.addMenu("Координаты")

        # Меню: Импорт
        self.import_menu = menu_bar.addMenu("Импорт")

        # Меню: Экспорт
        self.export_menu = menu_bar.addMenu("Экспорт")

        # Меню: Настройки
        self.settings_menu = menu_bar.addMenu("Настройки")

    def _create_central_layout(self) -> None:
        """Создание трехпанельной компоновки: Слои/Точки | Карта | Свойства."""
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Левая панель: Слои и Точки
        self.left_panel = self._create_left_panel()
        splitter.addWidget(self.left_panel)

        # Центральная область: Карта Республики Марий Эл (MapCanvas)
        self.center_panel = self._create_center_panel()
        splitter.addWidget(self.center_panel)

        # Правая панель: Свойства
        self.right_panel = self._create_right_panel()
        splitter.addWidget(self.right_panel)

        # Начальные пропорции сплиттера: 280px, 840px, 280px
        splitter.setSizes([280, 840, 280])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        self.setCentralWidget(splitter)

    def _create_left_panel(self) -> QWidget:
        """Создание левой панели с блоком 'Слои' и блоком 'Точки'."""
        panel = QWidget()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # 1. Секция 'Слои'
        layers_title = QLabel("Слои")
        layers_font = QFont()
        layers_font.setBold(True)
        layers_font.setPointSize(11)
        layers_title.setFont(layers_font)
        layout.addWidget(layers_title)

        # Контейнер для чекбоксов слоев
        self.layers_container = QWidget()
        self.layers_container.setObjectName("layersContainer")
        self.layers_layout = QVBoxLayout(self.layers_container)
        self.layers_layout.setContentsMargins(4, 2, 4, 6)
        self.layers_layout.setSpacing(6)
        layout.addWidget(self.layers_container)

        # Разделительная линия
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # 2. Секция 'Точки'
        points_title = QLabel("Точки")
        points_font = QFont()
        points_font.setBold(True)
        points_font.setPointSize(11)
        points_title.setFont(points_font)
        layout.addWidget(points_title)

        self.points_placeholder = QFrame()
        self.points_placeholder.setObjectName("pointsPlaceholder")
        self.points_placeholder.setFrameShape(QFrame.Shape.StyledPanel)
        self.points_placeholder.setFrameShadow(QFrame.Shadow.Sunken)

        placeholder_layout = QVBoxLayout(self.points_placeholder)
        placeholder_label = QLabel("Место под таблицу точек")
        placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_label.setStyleSheet("color: #888888; font-style: italic;")
        placeholder_layout.addWidget(placeholder_label)

        layout.addWidget(self.points_placeholder, stretch=1)
        return panel

    def _create_center_panel(self) -> QWidget:
        """Создание центральной области с MapCanvas."""
        panel = QWidget()
        panel.setObjectName("centerPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Заголовок области карты
        header_layout = QVBoxLayout()
        header_label = QLabel("Карта Республики Марий Эл")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(12)
        header_label.setFont(header_font)
        header_layout.addWidget(header_label)
        layout.addLayout(header_layout)

        # Интерактивный холст карты (MapCanvas)
        self.map_canvas = MapCanvas(panel)
        # Атрибут map_placeholder для обратной совместимости
        self.map_placeholder = self.map_canvas

        layout.addWidget(self.map_canvas, stretch=1)
        return panel

    def _create_right_panel(self) -> QWidget:
        """Создание правой панели: заголовок 'Свойства' и пустое место под настройки."""
        panel = QWidget()
        panel.setObjectName("rightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title_label = QLabel("Свойства")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        self.properties_placeholder = QFrame()
        self.properties_placeholder.setObjectName("propertiesPlaceholder")
        self.properties_placeholder.setFrameShape(QFrame.Shape.StyledPanel)
        self.properties_placeholder.setFrameShadow(QFrame.Shadow.Sunken)

        placeholder_layout = QVBoxLayout(self.properties_placeholder)
        placeholder_label = QLabel("Место под настройки точки")
        placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_label.setStyleSheet("color: #888888; font-style: italic;")
        placeholder_layout.addWidget(placeholder_label)

        layout.addWidget(self.properties_placeholder, stretch=1)
        return panel

    def _create_status_bar(self) -> None:
        """Создание нижней строки состояния."""
        status_bar = QStatusBar(self)
        status_bar.setObjectName("statusBar")
        status_bar.showMessage("Готово")
        self.setStatusBar(status_bar)

    def load_map(self, map_path: Path | str) -> None:
        """Загрузка слоев карты из указанного GeoPackage."""
        path = Path(map_path)
        logger.info("Загрузка карты из: %s", path)

        if not GeoPackageService.exists(path):
            err_msg = f"Не найден файл карты:\n{path}"
            logger.error("Файл карты не найден: %s", path)
            self.map_canvas.set_error(err_msg)
            self.statusBar().showMessage("Ошибка: файл карты не найден")
            return

        try:
            # 1. Обнаруживаем поддерживаемые слои
            discovered_layers = self._layer_service.discover_layers(path)
            logger.info("Обнаружено поддерживаемых слоев: %d", len(discovered_layers))

            if not discovered_layers:
                err_msg = "В GeoPackage не найдено поддерживаемых картографических слоев"
                logger.error(err_msg)
                self.map_canvas.set_error(err_msg)
                self.statusBar().showMessage("Ошибка: поддерживаемые слои не найдены")
                return

            # 2. Очищаем старые чекбоксы в панели слоев
            self._clear_layer_checkboxes()

            successfully_loaded: list[MapLayer] = []
            common_crs = "OGC:CRS84"

            # 3. Загружаем слои по порядку (z_order)
            for layer in discovered_layers:
                try:
                    logger.info("Загрузка слоя '%s' (%s)...", layer.display_name, layer.source_name)
                    gdf = self._layer_service.load_layer_data(path, layer)

                    if gdf.crs:
                        common_crs = gdf.crs.to_string()

                    self.map_canvas.add_layer_item(layer, gdf)
                    successfully_loaded.append(layer)

                    # Добавляем чекбокс в панель слоев
                    self._add_layer_checkbox(layer)

                except Exception as layer_err:
                    logger.exception("Ошибка загрузки слоя '%s': %s", layer.display_name, layer_err)
                    if layer.role == LayerRole.BOUNDARY:
                        # Если упала граница — это критично
                        self.map_canvas.set_error(f"Ошибка чтения границы РМЭ:\n{layer_err}")
                        self.statusBar().showMessage("Ошибка чтения границы карты")
                        return
                    # Для второстепенных слоев (например, дорог) продолжаем работу
                    logger.warning("Слой '%s' пропущен из-за ошибки, продолжаем работу", layer.display_name)

            self.loaded_layers = successfully_loaded

            # 4. Обновляем статусную строку
            status_text = f"Карта загружена | {common_crs} | Слоёв: {len(successfully_loaded)}"
            self.statusBar().showMessage(status_text)
            logger.info("Карта успешно загружена. %s", status_text)

        except Exception as e:
            logger.exception("Критическая ошибка при загрузке карты из %s: %s", path, e)
            self.map_canvas.set_error(f"Ошибка при чтении карты:\n{e}")
            self.statusBar().showMessage("Ошибка загрузки карты")

    def _clear_layer_checkboxes(self) -> None:
        """Очистка всех чекбоксов слоев."""
        for chk in self.layer_checkboxes.values():
            self.layers_layout.removeWidget(chk)
            chk.deleteLater()
        self.layer_checkboxes.clear()

    def _add_layer_checkbox(self, layer: MapLayer) -> None:
        """Создание чекбокса для управления видимостью слоя."""
        chk = QCheckBox(layer.display_name)
        chk.setObjectName(f"chk_{layer.id}")
        chk.setChecked(layer.visible)
        chk.setCursor(Qt.CursorShape.PointingHandCursor)

        # Связываем переключение чекбокса с холстом
        chk.toggled.connect(
            lambda checked, lid=layer.id: self._on_layer_toggled(lid, checked)
        )

        self.layers_layout.addWidget(chk)
        self.layer_checkboxes[layer.id] = chk

    def _on_layer_toggled(self, layer_id: str, visible: bool) -> None:
        """Обработка переключения видимости слоя пользователем."""
        self.map_canvas.set_layer_visibility(layer_id, visible)
