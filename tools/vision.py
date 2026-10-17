"""Передача изображений модели (DeepSeek Vision).

Документация: https://api-docs.deepseek.com/guides/vision

Модель `deepseek-flash` принимает картинки вместе с текстом: можно попросить
описать изображение, прочитать текст со скриншота, разобрать график. Формат
определяется по содержимому файла (а не по расширению), поддерживаются
JPEG, PNG, GIF и WebP.

Инструмент `read_image` отдаёт список контент-блоков в формате Chat
Completions (`image_url` с base64 data URL). Агент складывает их в отдельное
user-сообщение: по документации изображения допустимы только в user-сообщениях
(в system/assistant — ошибка 400).

Ограничения API, которые соблюдает модуль:
  * тело запроса — до 48 МиБ, одно изображение inline — до 32 МиБ;
  * ссылка http(s) — до 8192 символов (здесь используется base64, без ссылок);
  * обрезание по размеру — `vision.max_bytes` в agent.config.json.
"""

from __future__ import annotations

import base64
from pathlib import Path

import config

# Форматы из документации: JPEG, PNG, GIF, WebP.
MAGIC_JPEG = b"\xff\xd8\xff"
MAGIC_PNG = b"\x89PNG\r\n\x1a\n"
MAGIC_GIF = (b"GIF87a", b"GIF89a")
MAGIC_RIFF = b"RIFF"
MAGIC_WEBP = b"WEBP"

DETAIL_VALUES = ("low", "high", "original", "auto")


def detect_image_mime(data: bytes) -> str:
    """MIME-тип изображения по первым байтам ("" — это не картинка).

    Формат определяется по содержимому файла, как и в API: переименованный
    .png с текстом внутри изображением не считается.
    """
    if data.startswith(MAGIC_JPEG):
        return "image/jpeg"
    if data.startswith(MAGIC_PNG):
        return "image/png"
    if data.startswith(MAGIC_GIF):
        return "image/gif"
    if data[:4] == MAGIC_RIFF and data[8:12] == MAGIC_WEBP:
        return "image/webp"
    return ""


def is_image_file(path: str) -> bool:
    """Похож ли файл на изображение (читает только первые 12 байт)."""
    try:
        with open(path, "rb") as f:
            return bool(detect_image_mime(f.read(12)))
    except OSError:
        return False


def image_part(data: bytes, mime: str, detail: str = "") -> dict:
    """Контент-блок `image_url` с inline base64 (самый простой способ по докам)."""
    encoded = base64.b64encode(data).decode("ascii")
    image_url: dict = {"url": f"data:{mime};base64,{encoded}"}
    if detail in DETAIL_VALUES and detail != "auto":
        image_url["detail"] = detail
    return {"type": "image_url", "image_url": image_url}


def read_image(path: str, detail: str = "") -> list[dict] | str:
    """Готовит изображение к отправке модели.

    Возвращает список контент-блоков (текст + image_url) или строку с ошибкой.
    Ошибка возвращается строкой, как и у остальных инструментов агента.
    """
    settings = config.vision_settings()
    p = Path(path)
    if not p.is_file():
        return f"ERROR: файл не найден: {path}"

    max_bytes = int(settings.get("max_bytes") or 0)
    size = p.stat().st_size
    if max_bytes > 0 and size > max_bytes:
        return (f"ERROR: изображение {path} весит {_human_size(size)} — больше "
                f"лимита {_human_size(max_bytes)} (vision.max_bytes в "
                "agent.config.json). Уменьши картинку или загрузи её через "
                "Files API DeepSeek.")

    try:
        data = p.read_bytes()
    except OSError as e:
        return f"ERROR: не удалось прочитать {path}: {e}"

    mime = detect_image_mime(data)
    if not mime:
        return (f"ERROR: {path} — не изображение. Поддерживаются JPEG, PNG, GIF "
                "и WebP; формат определяется по содержимому файла.")

    level = (detail or settings.get("detail") or "auto").strip().lower()
    if level not in DETAIL_VALUES:
        level = "auto"

    return [
        {
            "type": "text",
            "text": (f"Изображение {p.name} ({mime}, {_human_size(size)}) "
                     f"передано модели отдельным сообщением."),
        },
        image_part(data, mime, level),
    ]


def _human_size(size: int) -> str:
    """Размер файла для сообщения модели: 512 Б, 245 КБ, 3.4 МБ."""
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size // 1024} КБ"
    return f"{size / (1024 * 1024):.1f} МБ"
