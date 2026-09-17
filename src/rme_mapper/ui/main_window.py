"""Главное окно приложения RME-Mapper."""

import logging
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
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
from rme_mapper.services.geopackage_service import GeoPackageService

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
        """Создание трехпанельной компоновки: Точки | Карта | Свойства."""
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Левая панель: Точки
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
        """Создание левой панели: заголовок 'Точки' и пустое место под таблицу точек."""
        panel = QWidget()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title_label = QLabel("Точки")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

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
        # Сохраняем атрибут map_placeholder для обратной совместимости
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
        """Загрузка векторного слоя карты из указанного пути GeoPackage."""
        path = Path(map_path)
        logger.info("Запрос загрузки карты из %s", path)

        if not GeoPackageService.exists(path):
            err_msg = (
                f"Не найден файл карты:\n"
                f"{path}"
            )
            logger.error("Файл карты не существует: %s", path)
            self.map_canvas.set_error(err_msg)
            self.statusBar().showMessage("Ошибка: файл карты не найден")
            return

        try:
            layers = GeoPackageService.list_layers(path)
            logger.info("Найдено слоев в %s: %d", path.name, len(layers))

            boundary_layer = GeoPackageService.find_boundary_layer(path)
            if not boundary_layer:
                layer_names = [l[0] for l in layers]
                err_msg = (
                    f"Не найден слой границы Республики Марий Эл.\n"
                    f"Обнаруженные слои: {', '.join(layer_names)}"
                )
                logger.error(err_msg)
                self.map_canvas.set_error(err_msg)
                self.statusBar().showMessage("Ошибка: слой границы не найден")
                return

            logger.info("Загрузка слоя границы: %s", boundary_layer)
            gdf = GeoPackageService.read_layer(path, boundary_layer)

            # Отображаем на холсте
            self.map_canvas.load_geodataframe(gdf)

            # Определяем CRS
            crs_name = gdf.crs.to_string() if gdf.crs else "Неизвестный CRS"
            status_text = f"Карта загружена | {crs_name}"
            self.statusBar().showMessage(status_text)
            logger.info("Карта успешно загружена. Статус: %s", status_text)

        except Exception as e:
            logger.exception("Исключение при загрузке карты из %s: %s", path, e)
            self.map_canvas.set_error(f"Ошибка при чтении карты:\n{e}")
            self.statusBar().showMessage("Ошибка загрузки карты")
