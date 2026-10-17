"""Инструменты «умного» поиска: локальная обработка вместо простыней в контекст.

Идея: тяжёлую работу (обойти проект, разобрать дерево символов, построить дифф)
делает агент на месте, а модели уходит компактная выжимка. Всё, что не влезло,
сохраняется в `.agent-cache/output` и читается точечно (`read_range`).

Инструменты:
- search_code   — regex-поиск с контекстом, сгруппированный по файлам;
- file_outline  — карта символов файла (классы/функции/методы с номерами строк);
- read_symbol   — тело конкретного символа по имени, без чтения файла целиком;
- diff_files    — сравнение двух файлов (unified diff только с изменениями);
- find_files    — поиск файлов по маске (без вываливания дерева целиком);
- project_map   — структура проекта с ограничением по глубине и объёму.
"""

from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path

import config
from . import digest
from .filesystem import SKIP_DIRS, iter_files, project_outline

DEFAULT_MAX_RESULTS = 60
MAX_OUTLINE_LINES = 200
MAX_SYMBOL_LINES = 250
MAX_DIFF_LINES = 400


# ---------- Регулярные выражения по языкам ----------

# Имя группы 1 — имя символа, группа 2 (необязательная) — «вид» символа.
_SYMBOL_PATTERNS: dict[str, list[tuple[str, str]]] = {
    ".php": [
        (r"^\s*(?:abstract\s+|final\s+|readonly\s+)*class\s+(\w+)", "class"),
        (r"^\s*(?:abstract\s+|final\s+)*interface\s+(\w+)", "interface"),
        (r"^\s*trait\s+(\w+)", "trait"),
        (r"^\s*enum\s+(\w+)", "enum"),
        (r"^\s*(?:public|private|protected|static|abstract|final|\s)*"
         r"function\s+(\w+)", "function"),
    ],
    ".js": [
        (r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)", "class"),
        (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
        (r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*"
         r"(?:async\s*)?(?:\(|function)", "const"),
        (r"^\s*(?:export\s+)?(?:interface|type|enum)\s+(\w+)", "type"),
        (r"^\s*(?:static\s+)?(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{", "method"),
    ],
    ".java": [
        (r"^\s*(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+)*"
         r"(?:class|interface|enum|record)\s+(\w+)", "class"),
        (r"^\s*(?:public|private|protected|static|final|abstract|synchronized"
         r"|native|\s)+[\w<>\[\],.?\s]+\s(\w+)\s*\(", "method"),
    ],
    ".kt": [
        (r"^\s*(?:public|private|protected|internal|open|abstract|sealed|data"
         r"|enum|annotation|\s)*(?:class|interface|object)\s+(\w+)", "class"),
        (r"^\s*(?:public|private|protected|internal|open|override|suspend"
         r"|inline|\s)*fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?(\w+)\s*\(", "fun"),
    ],
    ".swift": [
        (r"^\s*(?:public|private|fileprivate|internal|open|final|\s)*"
         r"(?:class|struct|enum|protocol|extension|actor)\s+(\w+)", "type"),
        (r"^\s*(?:public|private|fileprivate|internal|open|override|static"
         r"|class|mutating|\s)*func\s+(\w+)", "func"),
        (r"^\s*(?:public|private|internal|convenience|required|\s)*init\s*\(", "init"),
    ],
    ".go": [
        (r"^func\s+\([^)]*\)\s*(\w+)\s*\(", "method"),
        (r"^func\s+(\w+)\s*\(", "func"),
        (r"^type\s+(\w+)\s+(?:struct|interface)", "type"),
    ],
    ".rb": [
        (r"^\s*def\s+(?:self\.)?(\w+[?!=]?)", "def"),
        (r"^\s*(?:class|module)\s+(\w+)", "class"),
    ],
    ".rs": [
        (r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)", "fn"),
        (r"^\s*(?:pub\s+)?(?:struct|enum|trait|impl|mod)\s+(\w+)", "type"),
    ],
    ".css": [
        (r"^([.#][\w-]+(?:\s*[,>]\s*[.#]?[\w-]+)*)\s*\{", "selector"),
    ],
}

# Расширения, которые обслуживает одна и та же таблица паттернов.
_PATTERN_ALIASES = {
    ".jsx": ".js", ".ts": ".js", ".tsx": ".js", ".mjs": ".js", ".cjs": ".js",
    ".mts": ".js", ".cts": ".js",
    ".phtml": ".php", ".php3": ".php", ".php4": ".php", ".php5": ".php",
    ".kts": ".kt",
    ".scss": ".css", ".sass": ".css", ".less": ".css",
}

_LANG_NAMES = {
    ".py": "Python", ".pyi": "Python", ".php": "PHP", ".js": "JS/TS",
    ".java": "Java", ".kt": "Kotlin", ".swift": "Swift", ".go": "Go",
    ".rb": "Ruby", ".rs": "Rust", ".css": "CSS", ".html": "HTML",
}

_STR_LITERAL_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def _patterns_for(suffix: str) -> list[tuple[str, str]]:
    key = _PATTERN_ALIASES.get(suffix, suffix)
    return _SYMBOL_PATTERNS.get(key, [])


def _rel(path: Path) -> str:
    """Путь для модели: относительно корня проекта (как у остальных инструментов)."""
    try:
        return path.resolve().relative_to(Path(config.PROJECT_ROOT).resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


# ---------- Поиск по коду ----------

def search_code(pattern: str, path: str = ".", include: str = "",
                context: int = 0, max_results: int = 0, fixed: bool = False,
                ignore_case: bool = False, files_only: bool = False) -> str:
    """Regex-поиск по файлам с контекстом, сгруппированный по файлам.

    В отличие от grep возвращает не плоский список, а сводку: сколько файлов и
    совпадений, где именно, с указанием, сколько осталось за кадром. Вывод
    дополнительно сжимается (tools/digest.py), полный список — в файле.

    fixed=True — искать как обычную подстроку (regex-спецсимволы экранируются).
    """
    root = Path(path)
    if root.is_file():
        files = [root]
    elif root.is_dir():
        cfg = config.search_settings()
        files = iter_files(root, include,
                           max_files=int(cfg.get("max_files") or 0))
    else:
        return f"ERROR: путь не найден: {path}"

    try:
        regex = re.compile(re.escape(pattern) if fixed else pattern,
                            re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        return f"ERROR: некорректный regex: {e}"

    cfg = config.search_settings()
    limit = int(max_results or cfg.get("max_results") or DEFAULT_MAX_RESULTS)
    ctx = max(0, int(context or cfg.get("context") or 0))

    # {файл: [(строка, текст, это_совпадение)]} — контекст собирается сразу,
    # второй проход по файлам не нужен. counts — на случай files_only:
    # держать в памяти все совпадения ради одних счётчиков незачем.
    hits: dict[Path, list[tuple[int, str, bool]]] = {}
    counts: dict[Path, int] = {}
    total = 0
    shown = 0
    for fp in files:
        try:
            lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rows: list[tuple[int, str, bool]] = []
        matched = 0
        for lineno, line in enumerate(lines, 1):
            if not regex.search(line):
                continue
            total += 1
            matched += 1
            if files_only:
                continue
            if shown >= limit:
                continue
            shown += 1
            if ctx:
                for c in range(max(1, lineno - ctx), lineno):
                    rows.append((c, lines[c - 1].rstrip(), False))
            rows.append((lineno, line.rstrip(), True))
            if ctx:
                for c in range(lineno + 1, min(len(lines), lineno + ctx) + 1):
                    rows.append((c, lines[c - 1].rstrip(), False))
        if matched:
            counts[fp] = matched
        if rows:
            hits[fp] = rows

    if not total:
        return (f"Совпадений не найдено: {pattern!r} "
                f"(путь={path}, include={include or 'код'}, "
                f"файлов просмотрено {len(files)}).")

    if files_only:
        out = [f"Файлов с совпадениями: {len(counts)}"]
        for fp, matches in counts.items():
            out.append(f"{_rel(fp)} ({matches})")
        return "\n".join(out)

    out = [f"Найдено {total} совпадений в {len(counts)} файлах "
           f"(показано {shown}, путь={path}, include={include or 'код'})"]
    for fp, rows in hits.items():
        out.append(f"\n{_rel(fp)} ({counts.get(fp, 0)})")
        for lineno, line, is_match in rows:
            mark = " " if is_match else "~"
            out.append(f"  {mark}{lineno:>5}: {line}")

    if shown < total:
        out.append(f"\n[... показано {shown} из {total} совпадений. "
                   "Сузь include/path или увеличь max_results.]")
    return digest.compress("search_code", "\n".join(out),
                           keywords=digest.keywords_from(pattern))


# ---------- Карта символов ----------

def _python_symbols(source: str) -> list[tuple[int, int, int, str]]:
    """(первая строка, последняя строка, уровень вложенности, подпись)."""
    tree = ast.parse(source)
    found: list[tuple[int, int, int, str]] = []

    def walk(node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else "def"
                end = getattr(child, "end_lineno", None) or child.lineno
                doc = (ast.get_docstring(child) or "").strip().splitlines()
                label = f"{kind} {child.name}"
                if doc:
                    label += f" — {doc[0][:70]}"
                found.append((child.lineno, end, depth, label))
                walk(child, depth + 1)

    walk(tree, 0)
    return found


def _regex_symbols(source: str, suffix: str) -> list[tuple[int, int, int, str]]:
    """Символы для не-Python файлов: регулярки по строкам + грубая оценка конца."""
    patterns = _patterns_for(suffix)
    if not patterns:
        return []
    compiled = [(re.compile(p), kind) for p, kind in patterns]
    lines = source.splitlines()
    found: list[tuple[int, int, int, str]] = []
    for i, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith(("//", "*", "#")):
            continue
        for rx, kind in compiled:
            m = rx.match(line)
            if not m:
                continue
            name = m.group(1)
            indent = len(line) - len(line.lstrip())
            end = _guess_end(lines, i, indent, suffix)
            label = f"{kind} {name}".strip()
            found.append((i, end, indent // 2, label))
            break
    return found


def _guess_end(lines: list[str], start: int, indent: int, suffix: str) -> int:
    """Последняя строка блока: по скобкам (brace-языки) или по отступу."""
    if suffix in (".py", ".pyi"):
        last = start
        for i in range(start, len(lines)):
            line = lines[i]
            if not line.strip():
                continue
            if len(line) - len(line.lstrip()) <= indent:
                return last
            last = i + 1
        return len(lines)

    depth = 0
    opened = False
    for i in range(start - 1, len(lines)):
        stripped = _STR_LITERAL_RE.sub('""', lines[i])
        stripped = re.sub(r"//.*$", "", stripped)
        for ch in stripped:
            if ch == "{":
                depth += 1
                opened = True
            elif ch == "}":
                depth -= 1
        if opened and depth <= 0:
            return i + 1
    return len(lines)


def _outline_file(path: Path, max_symbols: int = MAX_OUTLINE_LINES) -> str:
    """Карта одного файла: заголовок + символы с диапазонами строк."""
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        return f"ERROR: не удалось прочитать {path}: {e}"

    suffix = path.suffix.lower()
    total = source.count("\n") + 1
    symbols: list[tuple[int, int, int, str]] = []
    note = ""
    if suffix in (".py", ".pyi"):
        try:
            symbols = _python_symbols(source)
        except SyntaxError as e:
            note = f"\n(!) файл не разбирается как Python: {e.msg} (строка {e.lineno})"
            symbols = _regex_symbols(source, suffix)
    else:
        symbols = _regex_symbols(source, suffix)

    lang = _LANG_NAMES.get(suffix, suffix.lstrip(".") or "?")
    head = f"{_rel(path)} — {lang}, {total} строк, символов: {len(symbols)}"
    if not symbols:
        return (head + f"{note}\n(структура не распознана — читай файл через "
                f"read_file / read_range)")

    rows = []
    for start, end, depth, label in symbols[:max_symbols]:
        rows.append(f"{start:>5}-{end:<5} {'  ' * depth}{label}")
    if len(symbols) > max_symbols:
        rows.append(f"... [ещё {len(symbols) - max_symbols} символов не показано]")
    rows.append('Подсказка: тело символа — read_symbol("имя", "'
                f'{_rel(path)}"), участок — read_range(...).')
    return head + note + "\n" + "\n".join(rows)


def file_outline(path: str = ".", max_symbols: int = MAX_OUTLINE_LINES) -> str:
    """Карта символов файла: классы, функции, методы, с диапазонами строк.

    Для большой папки возвращает структуру проекта (project_map) — читать
    каждый файл по отдельности модель не должна.
    """
    p = Path(path)
    if p.is_file():
        return digest.compress("file_outline", _outline_file(p),
                               keywords=None)
    if not p.is_dir():
        return f"ERROR: путь не найден: {path}"

    files = iter_files(p, "", max_files=60)
    if not files:
        return f"(в {path} нет файлов с кодом)"
    parts = [_outline_file(fp) for fp in files[:15]]
    rest = len(files) - 15
    body = "\n\n".join(parts)
    if rest > 0:
        body += (f"\n\n[... ещё {rest} файлов(а) не показано — зови "
                 "file_outline для конкретного файла]")
    return digest.compress("file_outline", body,
                           keywords=digest.keywords_from(path))


# ---------- Тело символа ----------

_DEF_STRICT = (r"(?i)\b(?:class|interface|trait|enum|struct|protocol|extension"
               r"|function|func|fun|def|fn|module|type|object)\s+{name}\b")
_DEF_LOOSE = (r"(?i)\b(?:const|let|var|static)\s+{name}\b"
              r"|\b{name}\s*\([^;]*\)\s*(?:->|\{)")


def _find_definitions(name: str, files: list[Path]) -> list[tuple[Path, int]]:
    """Где встречается определение символа: [(файл, строка)]."""
    safe = re.escape(name)
    # Плейсхолдер подставляем replace, а не format: в шаблонах есть литералы `{`.
    strict = re.compile(_DEF_STRICT.replace("{name}", safe))
    loose = re.compile(_DEF_LOOSE.replace("{name}", safe))
    strict_hits: list[tuple[Path, int]] = []
    loose_hits: list[tuple[Path, int]] = []
    for fp in files:
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if strict.search(line):
                strict_hits.append((fp, lineno))
            elif loose.search(line):
                loose_hits.append((fp, lineno))
        if len(strict_hits) > 20:
            break
    return strict_hits or loose_hits


def read_symbol(name: str, path: str = ".", max_lines: int = MAX_SYMBOL_LINES) -> str:
    """Возвращает тело символа (класса/функции/метода) по имени.

    Ищет определение в файле или по проекту, затем отдаёт только его тело —
    с номерами строк и обрезкой длинных тел (дальше — read_range).
    """
    if not name.strip():
        return "ERROR: пустое имя символа."

    p = Path(path)
    if p.is_file():
        files = [p]
    elif p.is_dir():
        cfg = config.search_settings()
        files = iter_files(p, "", max_files=int(cfg.get("max_files") or 0))
    else:
        return f"ERROR: путь не найден: {path}"

    hits = _find_definitions(name, files)
    if not hits:
        return (f"ERROR: определение {name!r} не найдено (путь={path}). "
                "Уточни имя или используй search_code.")

    unique_files = {fp for fp, _ in hits}
    if len(unique_files) > 1:
        listing = "\n".join(f"{_rel(fp)}:{ln}" for fp, ln in hits[:20])
        return (f"Определение {name!r} встречается в {len(unique_files)} файлах "
                f"(показаны первые {min(len(hits), 20)}):\n{listing}\n"
                "Уточни path, чтобы получить тело.")

    fp, lineno = hits[0]
    try:
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as e:
        return f"ERROR: не удалось прочитать {fp}: {e}"

    indent = len(lines[lineno - 1]) - len(lines[lineno - 1].lstrip())
    end = _guess_end(lines, lineno, indent, fp.suffix.lower())
    body = lines[lineno - 1:end]
    rel = _rel(fp)
    limit = max(10, int(max_lines))

    rows = [f"{rel}:{lineno}-{end} ({len(body)} строк): {lines[lineno - 1].strip()[:100]}"]
    for offset, line in enumerate(body[:limit], start=lineno):
        rows.append(f"{offset:>6}: {line}")
    if len(body) > limit:
        rows.append(f"[... тело обрезано: показано {limit} из {len(body)} строк. "
                    f"Дальше — read_range(\"{rel}\", {lineno + limit}, {end})]")
    return digest.compress("read_symbol", "\n".join(rows),
                           keywords=digest.keywords_from(name))


# ---------- Сравнение файлов ----------

def diff_files(path_a: str, path_b: str, context: int = 3,
               max_lines: int = MAX_DIFF_LINES) -> str:
    """Unified diff двух файлов: только изменения, без полного содержимого."""
    a, b = Path(path_a), Path(path_b)
    for p in (a, b):
        if not p.is_file():
            return f"ERROR: файл не найден: {p}"

    try:
        a_lines = a.read_text(encoding="utf-8", errors="ignore").splitlines()
        b_lines = b.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as e:
        return f"ERROR: не удалось прочитать файлы: {e}"

    diff = list(difflib.unified_diff(a_lines, b_lines,
                                     fromfile=_rel(a), tofile=_rel(b),
                                     n=max(0, int(context)), lineterm=""))
    if not diff:
        return f"Файлы идентичны: {_rel(a)} == {_rel(b)}"

    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    header = (f"{_rel(a)} -> {_rel(b)}: +{added} / -{removed}, "
              f"{len(diff)} строк диффа")

    # Дифф не рвём на «важные строки»: он читается только целиком подряд,
    # поэтому при нехватке бюджета отрезаем хвост и сохраняем полный текст.
    body = diff[:max(10, int(max_lines))]
    text = header + "\n" + "\n".join(body)
    budget = digest.limits()["max_chars"]
    if len(text) > budget:
        saved = digest.save_output("diff_files", header + "\n" + "\n".join(diff))
        kept: list[str] = []
        used = len(header) + 1
        for line in body:
            if used + len(line) + 1 > budget:
                break
            kept.append(line)
            used += len(line) + 1
        footer = (f"\n[... дифф обрезан: показано {len(kept)} из {len(diff)} строк"
                  + (f". Полный дифф: {saved} — читай read_range(...)" if saved else "")
                  + "]")
        return header + "\n" + "\n".join(kept) + footer
    return text


# ---------- Файлы по маске и структура проекта ----------

def find_files(pattern: str = "*", path: str = ".", max_results: int = 100) -> str:
    """Файлы по glob-маске ('*.py', '**/test_*.py'), без мусорных папок.

    path — папка для поиска; если передан файл, возвращается он сам.
    """
    root = Path(path)
    if root.is_file():
        return _rel(root)
    if not root.is_dir():
        return f"ERROR: путь не найден: {path}"
    if not pattern.strip():
        pattern = "*"

    try:
        matches = sorted(root.glob(pattern))
    except (OSError, ValueError) as e:
        return f"ERROR: некорректная маска {pattern!r}: {e}"

    found = [p for p in matches
             if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)]

    limit = max(1, int(max_results or 100))
    if not found:
        return f"Файлов по маске {pattern!r} не найдено в {path}."
    out = [_rel(p) for p in found[:limit]]
    if len(found) > limit:
        out.append(f"... [ещё {len(found) - limit} файлов — увеличь max_results "
                   "или уточни маску]")
    return "\n".join(out)


def project_map(depth: int = 2, max_entries: int = 150) -> str:
    """Структура проекта с ограничением глубины и количества записей."""
    return project_outline(str(config.PROJECT_ROOT), depth=max(1, int(depth)),
                           max_entries=max(10, int(max_entries)))
