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
# Покрывает PHP, Python, JS/TS, Java/Kotlin, Swift, шаблоны, стили, конфиги.
CODE_EXTENSIONS = (
    # PHP
    ".php", ".phtml", ".php3", ".php4", ".php5", ".phps",
    # Python
    ".py", ".pyi",
    # JS / TS
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts",
    # Java / Kotlin / JVM
    ".java", ".kt", ".kts", ".gradle", ".gradle.kts",
    # Swift / Objective-C
    ".swift", ".m", ".mm", ".h",
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
    # Бинарные изображения бесполезно отдавать текстом — их передаёт read_image.
    from .vision import is_image_file
    if is_image_file(str(p)):
        return (f"Это изображение ({p.name}): текстом оно не читается. "
                "Вызови read_image с тем же путём, чтобы показать его модели.")
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


def edit_file(path: str, old_text: str, new_text: str,
              replace_all: bool = False) -> str:
    """Заменяет old_text на new_text.

    replace_all=False (по умолчанию) — только первое вхождение.
    Переводы строк в файле сохраняются (CRLF/LF), сравнение идёт
    по нормализованному тексту, поэтому фрагмент из модели с \\n
    найдётся и в файле с \\r\\n.
    """
    p = Path(path)
    if not p.is_file():
        return f"ERROR: файл не найден: {path}"
    if not old_text:
        return "ERROR: old_text пуст."

    with open(p, "r", encoding="utf-8", newline="") as f:
        source = f.read()

    eol = "\r\n" if "\r\n" in source else "\n"
    norm_source = source.replace("\r\n", "\n")
    norm_old = old_text.replace("\r\n", "\n")
    norm_new = new_text.replace("\r\n", "\n")

    found = norm_source.count(norm_old)
    if found == 0:
        return (f"ERROR: фрагмент для замены не найден в {path}. "
                "Прочитай файл заново (read_file/read_range) и скопируй "
                "текст точно, включая отступы.")

    updated = norm_source.replace(norm_old, norm_new, -1 if replace_all else 1)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(updated.replace("\n", eol))

    replaced = found if replace_all else 1
    note = f" (всего вхождений: {found})" if found > 1 and not replace_all else ""
    return (f"Заменено в {path}: {replaced} шт. "
            f"({len(old_text)} -> {len(new_text)} символов){note}")


# Папки, которые не показываем в обзоре структуры проекта.
SKIP_DIRS = {
    ".git", "node_modules", "vendor", "__pycache__", ".venv", "venv",
    ".agent-cache", ".idea", ".vscode", "dist", "build", ".next",
    ".cache", ".mypy_cache", ".pytest_cache", "coverage", ".tox",
    "target", ".gradle", "Pods", "DerivedData", ".ruff_cache",
}


def project_outline(root: str = ".", depth: int = 2,
                    max_entries: int = 120) -> str:
    """Короткий обзор структуры проекта для системного промпта.

    Показывает папки и файлы до глубины depth, пропуская мусорные каталоги.
    Вывод ограничен max_entries строками, чтобы не раздувать контекст.
    """
    base = Path(root)
    if not base.is_dir():
        return "(не удалось прочитать структуру проекта)"

    lines: list[str] = []

    def walk(directory: Path, level: int, prefix: str) -> None:
        if len(lines) >= max_entries:
            return
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda x: (x.is_file(), x.name.lower()),
            )
        except OSError:
            return
        for item in entries:
            if len(lines) >= max_entries:
                return
            if item.name in SKIP_DIRS or item.name.startswith(".agent-cache"):
                continue
            if item.is_dir():
                lines.append(f"{prefix}{item.name}/")
                if level < depth:
                    walk(item, level + 1, prefix + "  ")
            else:
                lines.append(f"{prefix}{item.name}")

    walk(base, 1, "")
    if not lines:
        return "(проект пуст)"
    if len(lines) >= max_entries:
        lines.append(f"... (обрезано на {max_entries} записях, "
                     f"полный список — list_dir)")
    return "\n".join(lines)


def list_dir(path: str = ".") -> str:
    """Возвращает список файлов и папок в директории."""
    p = Path(path)
    if p.is_file():
        return f"{path} — это файл, а не папка (читай его через read_file)"
    if not p.is_dir():
        return f"ERROR: путь не найден: {path}"
    entries = []
    for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        suffix = "/" if item.is_dir() else ""
        entries.append(f"{item.name}{suffix}")
    return "\n".join(entries) if entries else "(пусто)"


def extensions_for(include: str) -> tuple[str, ...] | None:
    """Фильтр расширений по аргументу include.

    '' (пусто) — CODE_EXTENSIONS, '*' — без фильтра, '.php'/'php' — одно
    расширение. Пустая строка и '*' различаются: первый — «только код»,
    второй — «все файлы, включая .txt/.log».
    """
    if include == "*":
        return None
    if include:
        return (include,) if include.startswith(".") else (f".{include}",)
    return CODE_EXTENSIONS


def iter_files(root: Path, include: str = "", max_files: int = 0) -> list[Path]:
    """Файлы проекта под root с фильтром по расширению, без мусорных папок.

    Общий обход для grep и инструментов поиска (tools/search.py): одна и та же
    логика пропуска каталогов, чтобы результаты не расходились.
    """
    extensions = extensions_for(include)
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if extensions is not None and not fn.endswith(extensions):
                continue
            files.append(Path(dirpath) / fn)
            if max_files and len(files) >= max_files:
                return files
    return files


def grep(pattern: str, path: str = ".", include: str = "") -> str:
    """Ищет регулярное выражение в файлах проекта.

    path — папка (обходится рекурсивно) или один файл; для файла include
    игнорируется, ищется только в нём.
    include: суффикс расширения ('.php', 'php', '.css').
             Если пусто — ищет по всем CODE_EXTENSIONS.
             Можно указать '*' — тогда ищет по ВСЕМ файлам без фильтра.
    """
    root = Path(path)
    if root.is_file():
        files, base = [root], root.parent
    elif root.is_dir():
        files, base = iter_files(root, include), root
    else:
        return f"ERROR: путь не найден: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"ERROR: некорректный regex: {e}"

    results = []
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    if regex.search(line):
                        rel = fp.relative_to(base)
                        results.append(f"{rel}:{lineno}: {line.rstrip()}")
                        if len(results) >= MAX_GREP_RESULTS:
                            results.append(
                                f"... (обрезано, найдено >= {MAX_GREP_RESULTS})"
                            )
                            return "\n".join(results)
        except OSError:
            continue

    return "\n".join(results) if results else "Совпадений не найдено"