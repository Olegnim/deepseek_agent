"""
Инструменты для работы с файловой системой внутри PROJECT_ROOT.
Все пути приходят уже абсолютными (их преобразует safe_path в agent.py).
"""

import os
import re
from pathlib import Path

MAX_READ_BYTES = 500_000          # ~500 КБ на файл
MAX_GREP_RESULTS = 300            # сколько совпадений возвращать
MAX_READ_RANGE_LINES = 500        # максимум строк за один read_range

# Расширения, по которым ищет grep по умолчанию.
# Покрывает PHP, Python, JS/TS, шаблоны, стили, конфиги.
CODE_EXTENSIONS = (
    # PHP
    ".php", ".phtml", ".php3", ".php4", ".php5", ".phps",
    # Python
    ".py", ".pyi",
    # JS / TS
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts",
    # HTML / шаблоны
    ".html", ".htm", ".xhtml",
    ".twig", ".tpl", ".mustache", ".hbs", ".ejs",
    ".blade.php", ".volt",
    # Стили
    ".css", ".scss", ".sass", ".less", ".styl",
    # Конфиги / данные
    ".json", ".jsonc", ".md", ".markdown",
    ".yaml", ".yml", ".toml",
    ".ini", ".env", ".cfg", ".conf",
    ".xml", ".xsd", ".xsl", ".svg",
    ".htaccess", ".sql",
    # Скрипты
    ".sh", ".bash", ".zsh",
    ".ps1", ".psm1", ".bat", ".cmd",
)


def read_file(path: str) -> str:
    """Читает файл целиком (с ограничением по размеру)."""
    p = Path(path)
    if not p.is_file():
        return f"ERROR: файл не найден: {path}"
    size = p.stat().st_size
    if size > MAX_READ_BYTES:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(MAX_READ_BYTES)
        return (
            f"[файл обрезан: показаны первые {MAX_READ_BYTES} из {size} байт. "
            f"Для чтения конкретного участка используй read_range(path, start, end).]\n"
            + head
        )
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def read_range(path: str, start: int = 1, end: int = 200) -> str:
    """Читает строки [start, end] (включительно, 1-based).
    Для больших файлов, где read_file обрезает.

    Максимум MAX_READ_RANGE_LINES строк за раз.
    """
    p = Path(path)
    if not p.is_file():
        return f"ERROR: файл не найден: {path}"

    start = max(1, int(start))
    end = int(end)
    if end < start:
        end = start

    # Защита от слишком большого окна
    if end - start + 1 > MAX_READ_RANGE_LINES:
        end = start + MAX_READ_RANGE_LINES - 1

    lines: list[str] = []
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f, 1):
            if i < start:
                continue
            if i > end:
                break
            lines.append(f"{i:>6}: {line.rstrip()}")

    if not lines:
        return f"(строки {start}-{end} пусты или файл короче)"
    return "\n".join(lines)


def write_file(path: str, content: str) -> str:
    """Записывает файл, создавая при необходимости папки."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return f"Записано {len(content)} символов в {path}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Заменяет первое вхождение old_text на new_text.
    Удобнее, чем write_file, когда нужно точечное изменение."""
    p = Path(path)
    if not p.is_file():
        return f"ERROR: файл не найден: {path}"
    with open(p, "r", encoding="utf-8") as f:
        source = f.read()
    if old_text not in source:
        return f"ERROR: фрагмент для замены не найден в {path}"
    updated = source.replace(old_text, new_text, 1)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(updated)
    return f"Заменено в {path} ({len(old_text)} -> {len(new_text)} символов)"


def list_dir(path: str = ".") -> str:
    """Возвращает список файлов и папок в директории."""
    p = Path(path)
    if not p.is_dir():
        return f"ERROR: папка не найдена: {path}"
    entries = []
    for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        suffix = "/" if item.is_dir() else ""
        entries.append(f"{item.name}{suffix}")
    return "\n".join(entries) if entries else "(пусто)"


def grep(pattern: str, path: str = ".", include: str = "") -> str:
    """Ищет регулярное выражение в файлах проекта.

    include: суффикс расширения ('.php', 'php', '.css').
             Если пусто — ищет по всем CODE_EXTENSIONS.
             Можно указать '*' — тогда ищет по ВСЕМ файлам без фильтра.
    """
    root = Path(path)
    if not root.is_dir():
        return f"ERROR: папка не найдена: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"ERROR: некорректный regex: {e}"

    if include == "*":
        extensions = None  # без фильтра
    elif include:
        extensions = (include,) if include.startswith(".") else (f".{include}",)
    else:
        extensions = CODE_EXTENSIONS

    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in {
                ".git", "node_modules", "vendor", "__pycache__",
                ".venv", "venv", ".agent-cache", ".idea", ".vscode",
                "dist", "build", ".next", ".cache",
            }
        ]
        for fn in filenames:
            if extensions is not None and not fn.endswith(extensions):
                continue
            fp = Path(dirpath) / fn
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = fp.relative_to(root)
                            results.append(f"{rel}:{lineno}: {line.rstrip()}")
                            if len(results) >= MAX_GREP_RESULTS:
                                results.append(
                                    f"... (обрезано, найдено >= {MAX_GREP_RESULTS})"
                                )
                                return "\n".join(results)
            except OSError:
                continue

    return "\n".join(results) if results else "Совпадений не найдено"