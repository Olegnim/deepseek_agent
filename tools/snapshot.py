"""Снапшоты файлов перед правкой. Заменяет git на alpha-этапе.

Каталог снапшотов и лимит берутся из agent.config.json
(paths.backup_dir и snapshots.max_backups).
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import config

# Корень проекта задаёт agent.py после разбора флага -p.
_project_root: Path | None = None


def set_project_root(path: str | Path | None) -> None:
    """Сообщает модулю актуальный корень проекта."""
    global _project_root
    _project_root = Path(path).resolve() if path else None


def _root() -> Path:
    return _project_root or Path(config.PROJECT_ROOT)


def _backup_dir() -> Path:
    return config.backup_dir(_root())


def snapshot_file(path: str) -> str:
    """Копирует файл в <backup_dir>/<timestamp>/<относительный путь>."""
    src = Path(path)
    if not src.is_file():
        return f"(snapshot: файл {path} не существует, пропускаю)"

    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    dest_dir = _backup_dir() / ts
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Сохраняем относительный путь, чтобы структура была видна
    try:
        rel = src.resolve().relative_to(_root())
    except ValueError:
        rel = Path(src.name)

    dest = dest_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)

    _cleanup_old()
    return f"snapshot -> {dest}"


def snapshot_dir(path: str = ".") -> str:
    """Zip-архив всей папки. Тяжелее, но полезен перед массовыми правками."""
    import zipfile

    src = Path(path)
    if not src.is_dir():
        return f"(snapshot: папка {path} не найдена)"

    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    backup_dir = _backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive = backup_dir / f"{ts}.zip"

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src.rglob("*"):
            if f.is_file() and ".agent-cache" not in f.parts and ".git" not in f.parts:
                zf.write(f, f.relative_to(src))

    _cleanup_old()
    return f"snapshot -> {archive}"


def _cleanup_old() -> None:
    """Оставляет только последние max_backups снапшотов."""
    backup_dir = _backup_dir()
    if not backup_dir.is_dir():
        return
    items = sorted(backup_dir.iterdir(), key=lambda p: p.name)
    for old in items[:-config.max_backups()]:
        if old.is_dir():
            shutil.rmtree(old, ignore_errors=True)
        else:
            old.unlink(missing_ok=True)
