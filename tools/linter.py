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
"""

from __future__ import annotations

import os
import shutil
import subprocess
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
    """Имя утилиты, которой нет в PATH, либо None. Первое слово команды."""
    first = (command or "").strip().split()[0] if (command or "").strip() else ""
    if not first:
        return "(пустая команда)"
    # python/python3 — считаем доступными (агент сам запущен на Python).
    if first in {"python", "python3", "py"}:
        return None
    if shutil.which(first) is None:
        return first
    return None


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
    timeout = int(_cfg().get("timeout") or config.shell_timeout())

    try:
        r = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            cwd=str(config.PROJECT_ROOT),
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
