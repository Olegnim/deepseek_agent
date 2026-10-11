"""Read-only git-инструменты: статус, дифф, история.

Только чтение — правки в репозиторий агент делает через файловые
инструменты (со снапшотами), а коммиты оставляет человеку.

Все команды выполняются в config.PROJECT_ROOT.
"""

from __future__ import annotations

import subprocess

import config

MAX_OUTPUT = 20000        # символов на команду
TIMEOUT = 30              # сек


def _git(*args: str) -> str:
    """Запускает git-команду в корне проекта и возвращает текстовый результат."""
    root = config.PROJECT_ROOT
    if not root.is_dir():
        return f"ERROR: папка проекта не найдена: {root}"

    cmd = [
        "git", "-c", "core.quotepath=false", "-c", "core.pager=cat",
        "-c", "color.ui=false", *args,
    ]
    try:
        r = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True,
            timeout=TIMEOUT, stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return "ERROR: git не найден в PATH."
    except subprocess.TimeoutExpired:
        return f"ERROR: git не ответил за {TIMEOUT} секунд."

    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()

    if r.returncode != 0 and ("not a git repository" in err.lower()
                              or "not a git repository" in out.lower()):
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
