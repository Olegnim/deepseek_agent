"""Автолинтер: быстрая проверка синтаксиса файла после правки.

После write_file / edit_file агент автоматически прогоняет проверку
синтаксиса подходящей утилитой: php -l, node --check, python -m py_compile
и т.п. Это снимает с модели рутину «не забыть проверить» и делает проверку
детерминированной, а не зависящей от того, вспомнит ли её языковая модель.

Правила задаются в agent.config.json (секция "lint") и могут быть переопределены
в проекте через <project>/.agent.config.json:

    "lint": {
      "enabled": true,
      "timeout": 30,
      "rules": [
        {"ext": [".php"],         "command": "php -l {file}",   "label": "php -l"},
        {"ext": [".js", ".mjs"],  "command": "node --check {file}", "label": "node --check"},
        {"ext": [".py"],          "command": "python -m py_compile {file}", "label": "py_compile"}
      ]
    }

В команда подставляется {file} — путь к проверяемому файлу (в кавычках).
Синтаксис `${...}` здесь НЕ используется специально: он занят подстановками
в config.py, поэтому плейсхолдер файла — `{file}`.

Если правило для расширения не найдено или утилита отсутствует в PATH —
проверка молча пропускается (lint_file возвращает None / пояснение).

Кроссплатформенность: Python-правила выполняются интерпретатором самого агента
(`config.python_exe()`, он же `sys.executable`), потому что на macOS и
Debian/Ubuntu команды `python` может не быть, а `py` есть только на Windows.
Байткод линта уходит в системный временный каталог (`PYTHONPYCACHEPREFIX`),
а не в `__pycache__` проекта.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import config

MAX_DETAIL = 1500      # сколько символов вывода утилиты отдавать модели
LINT_TOOLS = {"write_file", "edit_file"}


def _cfg() -> dict:
    return config.lint_settings()


def lint_enabled() -> bool:
    """Включён ли автолинт и есть ли хоть одно правило."""
    cfg = _cfg()
    return bool(cfg.get("enabled", True)) and bool(cfg.get("rules"))


def _rule_exts(rule: dict) -> list[str]:
    exts = rule.get("ext") or []
    if isinstance(exts, str):
        exts = [exts]
    return [str(e).lower() for e in exts]


def find_rule(path: str | os.PathLike) -> dict | None:
    """Возвращает первое правило, подходящее под расширение файла."""
    suffix = Path(path).suffix.lower()
    if not suffix:
        return None
    for rule in _cfg().get("rules") or []:
        if suffix in _rule_exts(rule):
            return rule
    return None


def _display_path(p: Path) -> str:
    """Путь относительно корня проекта (если внутри него), иначе абсолютный."""
    root = Path(config.PROJECT_ROOT)
    try:
        return str(p.resolve().relative_to(root))
    except ValueError:
        return str(p)


def _missing_tool(command: str) -> str | None:
    """Имя утилиты, которой нет в PATH, либо None. Первое слово команды.

    Первое слово разбирается с учётом кавычек (`config.split_command`),
    иначе правило с путём (`"C:/Program Files/Python/python.exe" -m …`)
    выглядело как отсутствующая утилита и проверка молча пропускалась.
    """
    program, _ = config.split_command(command)
    if not program:
        return "(пустая команда)"
    # python/python3/py — считаем доступными: линт идёт через sys.executable
    # (см. _resolve_interpreter), который есть всегда.
    if config.is_python_command(command):
        return None
    if shutil.which(program) is None:
        return program
    return None


def _resolve_interpreter(command: str) -> str:
    """Заменяет ведущий python/python3/py на путь к текущему интерпретатору.

    На Debian/Ubuntu и macOS команды `python` может не быть (только `python3`),
    а `py` есть только на Windows. Подстановка sys.executable гарантирует, что
    проверка пойдёт тем же интерпретатором, что и агент, на любой ОС.

    Служебный флаг `py -3` / `py -3.11` (выбор версии в launcher-е Windows)
    отбрасывается: у нас уже конкретный интерпретатор.
    """
    if not config.is_python_command(command):
        return command
    _, rest = config.split_command(command)
    rest_parts = rest.split()
    if rest_parts and re.fullmatch(r"-3(\.\d+)?", rest_parts[0]):
        rest = " ".join(rest_parts[1:])
    return f'"{config.python_exe()}" {rest}'.rstrip()


def manual_command(rule: dict) -> str:
    """Команда правила без {file} — для подсказок модели (`:doctor`, промпт).

    Python-команды показываются с реальным интерпретатором: `python -m ...`
    на macOS/Linux просто не запустится.
    """
    template = " ".join(str(rule.get("command") or "").replace("{file}", "").split())
    return _resolve_interpreter(template)


def _command_env(command: str) -> dict | None:
    """Дополнительные переменные окружения для команды.

    Для Python-команд байткод складывается в системный временный каталог,
    а не в `__pycache__` проекта: автолинт не должен мусорить в чужом
    репозитории (и не засоряет счётчик .agent-cache).
    """
    if not config.is_python_command(command):
        return None
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = str(
        Path(tempfile.gettempdir()) / "deepseek-agent-pycache"
    )
    return env


def lint_file(path: str | os.PathLike) -> str | None:
    """Проверяет один файл.

    Возвращает:
      * строку-отчёт («линт .php: OK» / «линт .php: ОШИБКА ...»);
      * строку-пояснение, если утилита не найдена;
      * None, если правило не задано или автолинт выключен.
    """
    if not lint_enabled():
        return None

    p = Path(path)
    if not p.is_file():
        return None

    rule = find_rule(p)
    if not rule:
        return None

    template = str(rule.get("command") or "").strip()
    if not template:
        return None
    label = rule.get("label") or template.split()[0]

    missing = _missing_tool(template)
    if missing:
        return f"линт {label}: пропущен — утилита «{missing}» не найдена в PATH"

    command = template.replace("{file}", f'"{_display_path(p)}"')
    command = _resolve_interpreter(command)
    timeout = int(_cfg().get("timeout") or config.shell_timeout())

    try:
        r = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            errors="replace",       # не падать на выводе утилит в другой кодировке
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            cwd=str(config.PROJECT_ROOT),
            env=_command_env(command),
        )
    except subprocess.TimeoutExpired:
        return f"линт {label}: таймаут {timeout} с — проверка прервана"
    except Exception as e:  # noqa: BLE001 — линтер не должен ронять агента
        return f"линт {label}: {type(e).__name__}: {e}"

    detail = "\n".join(
        part.strip() for part in (r.stdout or "", r.stderr or "") if part.strip()
    ).strip()

    if r.returncode == 0:
        return f"линт {label}: OK"

    if len(detail) > MAX_DETAIL:
        detail = detail[:MAX_DETAIL] + "\n... (вывод обрезан)"
    return f"линт {label}: ОШИБКА (exit={r.returncode})\n{detail or '(нет вывода)'}"


def lint_result(tool_name: str, args: dict, result: str) -> str:
    """Дополняет результат write_file/edit_file отчётом автолинта.

    Вызывается из agent.execute_tool. Если правило не подошло или правка
    не удалась — возвращает результат без изменений.
    """
    if tool_name not in LINT_TOOLS:
        return result
    if not result or result.startswith("ERROR"):
        return result
    path = args.get("path")
    if not path:
        return result

    report = lint_file(path)
    return f"{result}\n{report}" if report else result


def describe_rules() -> list[str]:
    """Список правил в виде строк для системного промпта (`:doctor`, `:config`)."""
    lines: list[str] = []
    for rule in _cfg().get("rules") or []:
        exts = _rule_exts(rule)
        if not exts:
            continue
        command = str(rule.get("command") or "").strip()
        if not command:
            continue
        missing = _missing_tool(command)
        mark = f"  (нет утилиты «{missing}»)" if missing else ""
        lines.append(f"- {', '.join(exts)} -> `{command}`{mark}")
    return lines
