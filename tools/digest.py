"""Выжимка из вывода инструментов: модель видит главное, всё остальное — в файле.

Зачем: `pytest`, `git log`, сборка или большая веб-страница дают десятки тысяч
символов. Раньше такой результат обрезался «в лоб» — модель теряла и конец
вывода, и сообщения об ошибках в середине. Здесь вместо обрезки:

1. полный вывод сохраняется в `.agent-cache/output/<tool>-<время>.txt`;
2. в контекст уходит выжимка: первые/последние строки + строки с ошибками и
   ключевыми словами запроса, с пометками «сколько строк пропущено»;
3. в конце — путь к полному файлу и подсказка читать его точечно
   (`read_range`, `search_code`).

Бюджет и поведение настраиваются в agent.config.json (секция tools.output):

    "tools": {"output": {"enabled": true, "max_chars": 6000,
                         "head_lines": 25, "tail_lines": 15, "keep_files": 40}}
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import config

DEFAULT_MAX_CHARS = 6000
DEFAULT_HEAD_LINES = 25
DEFAULT_TAIL_LINES = 15
DEFAULT_KEEP_FILES = 40
# Инструменты чтения: они сами ограничивают объём, выжимка им только мешает.
DEFAULT_NO_DIGEST = ("read_file", "read_range", "read_text_file")

# Строки, на которые модель точно должна посмотреть: ошибки, падения, диффы.
_IMPORTANT_RE = re.compile(
    r"(?i)(\berror\b|\bfail(?:ed|ure)?\b|\bfatal\b|\btraceback\b|\bexception\b"
    r"|\bpanic\b|\bwarning\b|\bcritical\b|denied|refused|timed?\s?out"
    r"|not found|undefined|cannot|unable|segmentation|core dumped"
    r"|не удалось|ошибк|исключени|отказано)"
    r"|^\s*(?:FAILED|ERROR|FAIL|E\s{2,}|Traceback|\+\+\+|---|@@)"
)

_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё_][\w./\\:-]{2,}")

# Слова, которые ничего не говорят о содержимом вывода.
_STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those",
    "into", "your", "you", "all", "any", "not", "but", "use", "using",
    "true", "false", "none", "null", "self", "path", "file", "files",
    "dir", "return", "result", "text", "str", "int", "bool", "def", "class",
    "и", "или", "для", "как", "что", "это", "все", "всё", "при", "над",
    "под", "без", "через", "файл", "файла", "файлы", "путь", "строка",
}


def limits() -> dict:
    """Текущий бюджет вывода (tools.output из конфига)."""
    cfg = config.output_settings() or {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "max_chars": int(cfg.get("max_chars") or DEFAULT_MAX_CHARS),
        "head_lines": max(0, int(cfg.get("head_lines") or DEFAULT_HEAD_LINES)),
        "tail_lines": max(0, int(cfg.get("tail_lines") or DEFAULT_TAIL_LINES)),
        "keep_files": max(1, int(cfg.get("keep_files") or DEFAULT_KEEP_FILES)),
    }


# ---------- Ключевые слова ----------

def keywords_from(value, limit: int = 12) -> list[str]:
    """Ключевые слова из запроса/команды/аргументов — для ранжирования строк.

    Принимает строку, список, словарь (аргументы инструмента) — всё, что может
    подсказать, что именно модель ищет: `pytest -k api`, `fetch_url(url, query=…)`.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        parts = [str(v) for v in value.values() if isinstance(v, (str, int, float))]
        text = " ".join(parts)
    elif isinstance(value, (list, tuple, set)):
        text = " ".join(str(v) for v in value)
    else:
        text = str(value)

    words: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(text):
        low = token.lower().strip(".:-/\\")
        if len(low) < 3 or low in _STOP_WORDS or low in seen:
            continue
        seen.add(low)
        words.append(token)
        if len(words) >= limit:
            break
    return words


# ---------- Сохранение полного вывода ----------

def _display_path(path: Path) -> str:
    """Путь для модели: относительный от корня проекта, если он внутри него."""
    try:
        return path.relative_to(Path(config.PROJECT_ROOT)).as_posix()
    except ValueError:
        return str(path)


def save_output(name: str, text: str) -> str | None:
    """Сохраняет полный вывод в .agent-cache/output и возвращает путь модели.

    Возвращает None, если записать не удалось (тогда compress отдаст обрезку).
    """
    cfg = limits()
    try:
        out_dir = Path(config.cache_dir(config.PROJECT_ROOT)) / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^0-9A-Za-z_.-]+", "-", name or "tool").strip("-")[:40] or "tool"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = out_dir / f"{safe}-{stamp}.txt"
        counter = 1
        while path.exists():
            counter += 1
            path = out_dir / f"{safe}-{stamp}-{counter}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        _cleanup(out_dir, cfg["keep_files"])
        return _display_path(path)
    except OSError:
        return None


def _cleanup(out_dir: Path, keep: int) -> None:
    """Удаляет самые старые сохранённые выводы, оставляя keep штук."""
    try:
        files = sorted((p for p in out_dir.iterdir() if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


# ---------- Выжимка ----------

def _tag(line: str) -> str:
    return "!" if _IMPORTANT_RE.search(line) else " "


def _rank(lines: list[str], keywords: list[str]) -> list[int]:
    """Индексы строк (1-based) с ошибками и ключевыми словами, в порядке файла."""
    lows = [k.lower() for k in keywords]
    picked: list[int] = []
    for i, line in enumerate(lines, 1):
        low = line.lower()
        if not line.strip():
            continue
        if _IMPORTANT_RE.search(line) or any(k in low for k in lows):
            picked.append(i)
    return picked


def compress(name: str, text: str, keywords=None, max_chars: int = 0,
             hint: str = "") -> str:
    """Возвращает текст как есть, если он влезает в бюджет, иначе — выжимку.

    name — имя инструмента (для имени файла с полным выводом),
    keywords — что именно искать в выводе (см. keywords_from),
    max_chars — переопределить бюджет (0 = tools.output.max_chars),
    hint — дополнительная подсказка в конце выжимки.
    """
    if not text:
        return text
    # Уже выжимка (инструмент сжал сам) — второй проход только испортит текст.
    if text.lstrip().startswith("[выжимка из вывода"):
        return text

    cfg = limits()
    limit = int(max_chars) if max_chars else cfg["max_chars"]
    if not cfg["enabled"] or limit <= 0 or len(text) <= limit:
        return text

    lines = text.splitlines()
    total = len(lines)
    saved = save_output(name, text)

    head_n = min(cfg["head_lines"], total)
    tail_n = min(cfg["tail_lines"], total)
    ordered: list[int] = list(range(1, head_n + 1))
    if tail_n:
        ordered += [i for i in range(total - tail_n + 1, total + 1)
                    if i > head_n]
    for idx in _rank(lines, keywords or []):
        if idx not in ordered:
            ordered.append(idx)

    # Бюджет: сначала первые/последние строки (каркас), затем важные вставки.
    chosen: list[int] = []
    budget = limit
    for idx in ordered:
        line = lines[idx - 1]
        cost = len(line) + 8          # 8 символов — префикс номера строки
        if cost > budget:
            continue
        budget -= cost
        chosen.append(idx)
    chosen.sort()

    out: list[str] = []
    header = (f"[выжимка из вывода {name}: {len(chosen)} строк из {total} "
              f"({len(text)} символов, бюджет {limit}). "
              "Строки с '!' — ошибки и совпадения с запросом.]")
    out.append(header)

    prev = 0
    for idx in chosen:
        if idx > prev + 1:
            out.append(f"... [{idx - prev - 1} строк пропущено] ...")
        line = lines[idx - 1]
        out.append(f"{_tag(line)}{idx:>6}: {line}")
        prev = idx
    if prev < total:
        out.append(f"... [{total - prev} строк пропущено] ...")

    if saved:
        out.append("")
        out.append(f"Полный вывод сохранён: {saved} ({total} строк, "
                   f"{len(text)} символов). Читай точечно: "
                   f"read_range(\"{saved}\", старт, конец) или "
                   f"search_code(шаблон, \"{Path(saved).parent.as_posix()}\", \"*\").")
    else:
        out.append("")
        out.append("Полный вывод сохранить не удалось — сузь запрос "
                   "(меньше файлов, другой фильтр, более точный шаблон).")
    if hint:
        out.append(hint)
    return "\n".join(out)


# ---------- Фрагменты (веб-страницы, длинные логи) ----------

_PARA_SPLIT_RE = re.compile(r"\n\s*\n")


def excerpt(text: str, keywords, max_chars: int = 0,
            paragraphs: int = 0, window: int = 0) -> str:
    """Возвращает релевантные фрагменты текста вместо его начала.

    Для веб-страниц: абзацы ранжируются по вхождению ключевых слов запроса,
    лучшие paragraphs отдаются в исходном порядке. Ключевых слов нет — обычная
    выжимка (первые + последние строки).
    """
    if not text:
        return text

    cfg = limits()
    limit = int(max_chars) if max_chars else cfg["max_chars"]
    if limit <= 0 or len(text) <= limit:
        return text

    words = [k.lower() for k in (keywords or []) if str(k).strip()]
    if not words:
        return compress("excerpt", text, keywords=None, max_chars=limit)

    paras = [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]
    if not paras:
        return compress("excerpt", text, keywords=words, max_chars=limit)

    def score(para: str) -> int:
        low = para.lower()
        return sum(low.count(w) for w in words)

    scored = [(score(p), i, p) for i, p in enumerate(paras)]
    best = [(s, i, p) for s, i, p in scored if s > 0]
    if not best:
        # Совпадений нет — отдаём начало текста с честной пометкой.
        clipped = text[:limit].rstrip()
        return (clipped
                + f"\n\n[... в тексте нет слов {', '.join(words[:6])}; "
                  f"показано начало, всего {len(text)} символов. "
                  "Уточни запрос или используй другой URL.]")

    top = int(paragraphs or config.web_settings().get("excerpt_paragraphs") or 8)
    chosen = sorted(best, key=lambda t: t[0], reverse=True)[:top]
    chosen.sort(key=lambda t: t[1])          # обратно в порядок страницы

    picked: list[str] = []
    used = 0
    for _, idx, para in chosen:
        prefix = f"[абзац {idx + 1}] "
        if used + len(para) > limit and picked:
            break
        picked.append(prefix + para)
        used += len(para)
    if not picked:                            # один абзац больше бюджета
        picked.append(f"[абзац {chosen[0][1] + 1}] " + chosen[0][2][:limit])

    body = "\n\n".join(picked)
    saved = save_output("web", text)
    tail = (f"\n\n[фрагменты по словам: {', '.join(words[:6])} — "
            f"{len(picked)} из {len(paras)} абзацев")
    if saved:
        tail += f"; полный текст: {saved} — читай read_range(...) точечно"
    tail += "]"
    return body + tail


def compress_result(name: str, text: str, args: dict | None = None,
                    hint: str = "") -> str:
    """Сжатие результата инструмента с ключевыми словами из его аргументов.

    Единая точка входа для agent.py (все инструменты, включая MCP) и для
    самих инструментов (run_shell, fetch_url). Инструменты чтения
    (`tools.output.no_digest`, по умолчанию read_file/read_range) не сжимаются:
    они уже ограничены своими лимитами, и модель явно попросила содержимое.
    """
    if not should_digest(name):
        return text
    keywords = keywords_from(args or {})
    return compress(name, text, keywords=keywords, hint=hint)


def should_digest(name: str) -> bool:
    """Применять ли выжимку к результату инструмента.

    Кроме прямого имени учитывается «короткое» имя MCP-инструмента
    (`filesystem__read_file` → `read_file`), чтобы чтение файлов через MCP
    вело себя так же, как встроенное.
    """
    skip = {item.rsplit("__", 1)[-1] for item in no_digest_tools()}
    return name.rsplit("__", 1)[-1] not in skip


def no_digest_tools() -> set[str]:
    """Инструменты, к которым выжимка не применяется (tools.output.no_digest)."""
    raw = (config.output_settings() or {}).get("no_digest")
    if raw is None:
        return set(DEFAULT_NO_DIGEST)
    if isinstance(raw, str):
        return {raw}
    return {str(item) for item in raw}
