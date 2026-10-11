"""Кэш агента в проекте: подсчёт размера и очистка.

В `.agent-cache/` копятся снапшоты правок (`backups/`), логи сессий (`logs/`)
и история ввода (`history.txt`). Со временем это тысячи файлов и мегабайты:
grep/read_file по ним замедляются, а модель может случайно втянуть их в контекст.
Здесь собраны две операции: посмотреть объём (`cache_overview`) и убрать
лишнее (`clear_cache`).

Что удаляем и что нет:
- `backups/` — снапшоты правок (откат `:restore` станет недоступен для удалённых);
- `logs/`    — логи сессий;
- `history.txt` — история команд REPL.
Файлы самого проекта не трогаются никогда.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import config

# Части кэша, которые умеет чистить clear_cache.
PARTS = ("backups", "logs", "history")
HISTORY_FILE = "history.txt"


def _base(project_root: str | Path | None = None) -> Path:
    return Path(config.cache_dir(project_root)).resolve()


def human_size(num_bytes: int) -> str:
    """Человекочитаемый размер: 0 Б, 12,4 КБ, 3,1 МБ."""
    size = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            text = f"{size:.0f}" if unit == "Б" else f"{size:.1f}"
            return f"{text} {unit}".replace(".", ",")
        size /= 1024
    return f"{size:.1f} ГБ"


def _dir_stat(path: Path) -> dict:
    """Количество файлов и суммарный размер папки (без ошибок на занятых файлах)."""
    count = 0
    size = 0
    if not path.is_dir():
        return {"count": 0, "bytes": 0}
    for item in path.rglob("*"):
        try:
            if item.is_file():
                count += 1
                size += item.stat().st_size
        except OSError:
            continue
    return {"count": count, "bytes": size}


def cache_overview(project_root: str | Path | None = None) -> dict:
    """Сводка по кэшу: что лежит в `.agent-cache` и сколько занимает."""
    base = _base(project_root)
    full = Path(project_root or config.PROJECT_ROOT).resolve()

    if base == full:                     # защита: не считаем содержимым весь проект
        return _empty(base)

    info = {
        "dir": base,
        "backups": _dir_stat(base / "backups"),
        "logs": _dir_stat(base / "logs"),
        "history": {"count": 0, "bytes": 0},
        "other": {"count": 0, "bytes": 0},
    }

    history = base / HISTORY_FILE
    if history.is_file():
        try:
            info["history"] = {"count": 1, "bytes": history.stat().st_size}
        except OSError:
            pass

    if base.is_dir():
        for item in base.iterdir():
            if item.name in ("backups", "logs") or item.name == HISTORY_FILE:
                continue
            if item.is_dir():
                info["other"] = _merge(info["other"], _dir_stat(item))

    info["total_bytes"] = sum(
        info[key]["bytes"] for key in ("backups", "logs", "history", "other")
    )
    info["total_items"] = sum(
        info[key]["count"] for key in ("backups", "logs", "history", "other")
    )
    return info


def _empty(base: Path) -> dict:
    zero = {"count": 0, "bytes": 0}
    return {
        "dir": base, "backups": dict(zero), "logs": dict(zero),
        "history": dict(zero), "other": dict(zero),
        "total_bytes": 0, "total_items": 0,
    }


def _merge(a: dict, b: dict) -> dict:
    return {"count": a["count"] + b["count"], "bytes": a["bytes"] + b["bytes"]}


def format_overview(info: dict) -> str:
    """Многострочный человекочитаемый отчёт о кэше."""
    lines = [f"папка:          {info['dir']}",
             f"снапшоты:       {info['backups']['count']} шт., "
             f"{human_size(info['backups']['bytes'])}",
             f"логи сессий:    {info['logs']['count']} шт., "
             f"{human_size(info['logs']['bytes'])}",
             f"история ввода:  {'есть' if info['history']['count'] else 'нет'}, "
             f"{human_size(info['history']['bytes'])}"]
    if info["other"]["count"]:
        lines.append(f"прочее:         {info['other']['count']} шт., "
                     f"{human_size(info['other']['bytes'])}")
    lines.append(f"итого:          {info['total_items']} файлов, "
                 f"{human_size(info['total_bytes'])}")
    return "\n".join(lines)


def has_cache(project_root: str | Path | None = None) -> bool:
    """Есть ли что чистить (файлы в backups/logs/history)."""
    info = cache_overview(project_root)
    return bool(info["backups"]["count"] or info["logs"]["count"]
                or info["history"]["count"])


def clear_cache(project_root: str | Path | None = None,
                parts: tuple[str, ...] = PARTS) -> str:
    """Удаляет выбранные части кэша и возвращает отчёт.

    parts — набор из 'backups', 'logs', 'history'.
    """
    base = _base(project_root)
    full = Path(project_root or config.PROJECT_ROOT).resolve()

    if not base.is_dir():
        return "Кэш пуст — очищать нечего."
    if base == full:
        return ("ERROR: папка кэша совпадает с корнем проекта — очистка отменена "
                "(проверьте paths.backup_dir).")

    before = cache_overview(project_root)
    removed: list[str] = []

    for name in parts:
        if name == "history":
            target = base / HISTORY_FILE
            if target.is_file():
                _remove_file(target)
                removed.append(f"история ввода ({human_size(before['history']['bytes'])})")
            continue

        target = (base / name).resolve()
        if not str(target).startswith(str(base)):     # страховка от странных путей
            continue
        if target.is_dir():
            stat = before[name]
            shutil.rmtree(target, ignore_errors=True)
            if not target.exists():
                removed.append(f"{name} ({stat['count']} шт., {human_size(stat['bytes'])})")
            else:
                removed.append(f"{name} — не удалось удалить полностью")

    if not removed:
        return "Нечего удалять: кэш уже пуст."

    freed = before["total_bytes"] - cache_overview(project_root)["total_bytes"]
    return (f"Кэш очищен: удалено {', '.join(removed)}; "
            f"освобождено {human_size(max(freed, 0))}.")


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
