"""Read-only git-инструменты: статус, дифф, история.

Только чтение — правки в репозиторий агент делает через файловые
инструменты (со снапшотами), а коммиты оставляет человеку.

Все команды выполняются в config.PROJECT_ROOT.
"""

from __future__ import annotations

import os
import subprocess

import config

MAX_OUTPUT = 20000        # символов на команду
TIMEOUT = 30              # сек

# Признаки «это не git-репозиторий» в выводе git. Git локализует сообщения,
# поэтому проверяем и русский вариант: на macOS/Linux с ru_RU.UTF-8 вывод
# приходит как «fatal: не найден git репозиторий».
_NOT_REPO_MARKERS = (
    "not a git repository",
    "не найден git репозиторий",
    "не является git-репозиторием",
)


def _git(*args: str) -> str:
    """Запускает git-команду в корне проекта и возвращает текстовый результат."""
    root = config.PROJECT_ROOT
    if not root.is_dir():
        return f"ERROR: папка проекта не найдена: {root}"

    cmd = [
        "git", "-c", "core.quotepath=false", "-c", "core.pager=cat",
        "-c", "color.ui=false", *args,
    ]
    # Вывод git всегда UTF-8 (core.quotepath=false уже задан), а консоль
    # Windows по умолчанию cp866/cp1251 — без явного encoding дифф с русским
    # текстом превращался бы в мусор. LC_ALL/LANG — стабильно английские
    # служебные сообщения (их проще распознавать), на Windows тоже работают.
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    env.setdefault("LANG", "C")
    try:
        r = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=TIMEOUT, stdin=subprocess.DEVNULL, env=env,
        )
    except FileNotFoundError:
        return "ERROR: git не найден в PATH."
    except subprocess.TimeoutExpired:
        return f"ERROR: git не ответил за {TIMEOUT} секунд."

    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()

    haystack = f"{out}\n{err}".lower()
    if r.returncode != 0 and any(m in haystack for m in _NOT_REPO_MARKERS):
        return f"ERROR: {root} — не git-репозиторий."

    body = out or "(пусто)"
    if err:
        body += f"\nSTDERR: {err}"
    if r.returncode != 0:
        body = f"exit={r.returncode}\n{body}"
    if len(body) > MAX_OUTPUT:
        body = body[:MAX_OUTPUT] + f"\n... (обрезано, всего {len(body)} символов)"
    return body


def git_status() -> str:
    """`git status` в кратком виде: ветка + изменённые/новые файлы."""
    return _git("status", "--short", "--branch")


def git_diff(path: str = "", staged: bool = False) -> str:
    """`git diff`. staged=True — изменения в индексе (--cached).

    path — ограничить дифф одним файлом или папкой (относительно проекта).
    """
    args = ["diff"]
    if staged:
        args.append("--cached")
    if path:
        args += ["--", path]
    return _git(*args)


def git_log(limit: int = 10) -> str:
    """Последние коммиты в одну строку: `git log --oneline`."""
    try:
        count = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        count = 10
    return _git("log", f"-n{count}", "--oneline", "--decorate")
