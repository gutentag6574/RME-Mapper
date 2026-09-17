"""Диалоговое окно 'О программе' (AboutDialog) приложения GeoPoint Mapper."""

import logging
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rme_mapper.app_info import (
    APP_NAME,
    APP_VERSION,
    AUTHOR_EMAIL,
    AUTHOR_NAME,
    AUTHOR_TELEGRAM,
    COPYRIGHT_TEXT,
    format_telegram_url,
    get_app_description,
)
from rme_mapper.i18n import tr

logger = logging.getLogger("rme_mapper.ui.about")


class AboutDialog(QDialog):
    """Информационное диалоговое окно со сведениями о версии, описании и авторе программы.

    Работает полностью автономно (оффлайн), не требуя подключения к интернету.
    При наличии корректной ссылки на Telegram позволяет открыть профиль в браузере.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.resize(520, 380)
        self.setModal(True)

        self._setup_ui()
        self.retranslate_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)

        # 1. Заголовок и версия
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        self.title_label = QLabel(APP_NAME, self)
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.title_label)

        self.version_label = QLabel(f"Версия {APP_VERSION}", self)
        version_font = QFont()
        version_font.setPointSize(10)
        version_font.setBold(True)
        self.version_label.setFont(version_font)
        self.version_label.setStyleSheet("color: #4A90E2;")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.version_label)

        layout.addLayout(header_layout)

        # Разделитель
        sep1 = QFrame(self)
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep1)

        # 2. Описание программы
        self.desc_label = QLabel("", self)
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignJustify)
        layout.addWidget(self.desc_label)

        # Разделитель
        sep2 = QFrame(self)
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep2)

        # 3. Сведения об авторе и контакты
        author_layout = QVBoxLayout()
        author_layout.setSpacing(8)

        # Автор и разработчик
        author_box = QHBoxLayout()
        self.author_title_label = QLabel("Автор и разработчик:", self)
        self.author_title_label.setStyleSheet("font-weight: bold;")
        self.author_val_label = QLabel(AUTHOR_NAME, self)
        author_box.addWidget(self.author_title_label)
        author_box.addWidget(self.author_val_label)
        author_box.addStretch()
        author_layout.addLayout(author_box)

        # Telegram
        tg_box = QHBoxLayout()
        self.tg_title_label = QLabel("Telegram:", self)
        self.tg_title_label.setStyleSheet("font-weight: bold;")
        tg_box.addWidget(self.tg_title_label)

        tg_url = format_telegram_url(AUTHOR_TELEGRAM)
        if tg_url:
            self.tg_label = QLabel(f'<a href="{tg_url}">{AUTHOR_TELEGRAM}</a>', self)
            self.tg_label.setOpenExternalLinks(False)
            self.tg_label.linkActivated.connect(self._open_telegram_url)
        else:
            self.tg_label = QLabel(AUTHOR_TELEGRAM, self)

        tg_box.addWidget(self.tg_label)
        tg_box.addStretch()
        author_layout.addLayout(tg_box)

        # Email
        email_box = QHBoxLayout()
        self.email_title_label = QLabel("Электронная почта:", self)
        self.email_title_label.setStyleSheet("font-weight: bold;")
        email_box.addWidget(self.email_title_label)
        self.email_label = QLabel(f'<a href="mailto:{AUTHOR_EMAIL}">{AUTHOR_EMAIL}</a>', self)
        self.email_label.setOpenExternalLinks(True)
        email_box.addWidget(self.email_label)
        email_box.addStretch()
        author_layout.addLayout(email_box)

        # Авторские права
        self.copyright_label = QLabel(COPYRIGHT_TEXT, self)
        self.copyright_label.setStyleSheet("color: #666666; font-size: 11px;")
        author_layout.addWidget(self.copyright_label)

        layout.addLayout(author_layout)

        layout.addStretch()

        # 4. Кнопка закрытия
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.close_btn = button_box.button(QDialogButtonBox.StandardButton.Close)
        if self.close_btn:
            self.close_btn.setText("Закрыть")
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def retranslate_ui(self) -> None:
        """Обновление локализованных надписей диалога при переключении языка."""
        self.setWindowTitle(tr("dialog.about.title", app_name=APP_NAME))
        if hasattr(self, "version_label"):
            self.version_label.setText(tr("dialog.about.version", version=APP_VERSION))
        if hasattr(self, "desc_label"):
            self.desc_label.setText(get_app_description())
        if hasattr(self, "author_title_label"):
            self.author_title_label.setText(tr("dialog.about.author"))
        if hasattr(self, "tg_title_label"):
            self.tg_title_label.setText(tr("dialog.about.telegram"))
        if hasattr(self, "email_title_label"):
            self.email_title_label.setText(tr("dialog.about.email"))
        if hasattr(self, "close_btn") and self.close_btn is not None:
            self.close_btn.setText(tr("dialog.about.close"))

    def _open_telegram_url(self, url_str: str) -> None:
        """Безопасное открытие Telegram ссылки во внешнем браузере."""
        valid_url = format_telegram_url(url_str)
        if valid_url:
            logger.info("Открытие Telegram ссылки: %s", valid_url)
            QDesktopServices.openUrl(QUrl(valid_url))
        else:
            logger.warning("Попытка открытия некорректной ссылки Telegram: %s", url_str)
