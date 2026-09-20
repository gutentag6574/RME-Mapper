"""Единый источник сведений о приложении GeoPoint Mapper, версии и метаданных сборки."""

from typing import Final

# Основные сведения о приложении
APP_NAME: Final[str] = "GeoPoint Mapper"
APP_VERSION: Final[str] = "0.12.0"

APP_DESCRIPTION_RU: Final[str] = (
    "Универсальное настольное приложение для работы "
    "с географически привязанными картами, координатами "
    "и геодезическими зонами."
)

APP_DESCRIPTION_EN: Final[str] = (
    "Universal desktop application for working "
    "with georeferenced maps, coordinates, "
    "and geodesic zones."
)

APP_DESCRIPTION: Final[str] = APP_DESCRIPTION_RU


def get_app_description(lang: str | None = None) -> str:
    """Получение локализованного описания приложения."""
    if lang == "en":
        return APP_DESCRIPTION_EN
    if lang == "ru":
        return APP_DESCRIPTION_RU
    try:
        from rme_mapper.i18n import get_language
        if get_language() == "en":
            return APP_DESCRIPTION_EN
    except Exception:
        pass
    return APP_DESCRIPTION_RU


# Сведения об авторе и разработчике
AUTHOR_NAME: Final[str] = "Кульдеев Вадим Алексеевич"
AUTHOR_TELEGRAM: Final[str] = "@enotis03"
AUTHOR_EMAIL: Final[str] = "zingeevruslan@gmail.com"

COPYRIGHT_YEAR: Final[str] = "2026"

# Метаданные для будущей сборки исполняемых файлов (Windows Version Info)
PRODUCT_NAME: Final[str] = "GeoPoint Mapper"
FILE_DESCRIPTION: Final[str] = "GeoPoint Mapper — настольное ГИС-приложение"
COMPANY_NAME: Final[str] = "Кульдеев Вадим Алексеевич"
COPYRIGHT_TEXT: Final[str] = f"© {COPYRIGHT_YEAR} {AUTHOR_NAME}"
PRODUCT_VERSION: Final[str] = APP_VERSION
FILE_VERSION: Final[str] = APP_VERSION


def format_telegram_url(raw_telegram: str | None = None) -> str | None:
    """Формирование безопасного URL для открытия профиля Telegram.

    Правила:
    - Для плейсхолдера 'Указать Telegram' или пустой строки возвращает None (ссылка не активна).
    - Для '@username' формирует 'https://t.me/username'.
    - Для 'https://t.me/username' или 'http://t.me/username' возвращает валидный URL напрямую.
    - Для чистого 't.me/username' добавляет префикс схемы https://.

    Возвращает:
        str | None: Валидный URL либо None, если ссылка некорректна или является плейсхолдером.
    """
    val = (raw_telegram if raw_telegram is not None else AUTHOR_TELEGRAM).strip()

    # Проверка на плейсхолдер или пустую строку
    if not val or val.lower() == "указать telegram":
        return None

    if val.startswith("@"):
        username = val[1:].strip()
        if username:
            return f"https://t.me/{username}"
        return None

    if val.startswith("https://t.me/") or val.startswith("http://t.me/"):
        return val

    if val.startswith("t.me/"):
        return f"https://{val}"

    # Если введено имя пользователя без @ и без пробелов/слешей
    if " " not in val and "/" not in val and "\\" not in val:
        return f"https://t.me/{val}"

    return None
