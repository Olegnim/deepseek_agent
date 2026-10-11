"""Тесты снапшотов правок и очистки кэша.

Снапшот — страховка на случай неудачной правки, поэтому проверяется и путь
восстановления (структура каталога), и лимит `snapshots.max_backups`, и то,
что очистка кэша не трогает файлы проекта.
"""

from __future__ import annotations

import config
from tools import cache
from tools import snapshot


# ---------- Снапшоты ----------

def test_snapshot_copies_file_with_relative_path(project):
    target = project / "src" / "file.php"
    target.parent.mkdir()
    target.write_text("<?php echo 1;\n", encoding="utf-8")

    result = snapshot.snapshot_file(str(target))

    copies = list((project / ".agent-cache" / "backups").rglob("file.php"))
    assert len(copies) == 1
    assert copies[0].read_bytes() == target.read_bytes()
    assert "snapshot ->" in result


def test_snapshot_of_missing_file_is_skipped(project):
    assert "не существует" in snapshot.snapshot_file(str(project / "нет.php"))


def test_snapshot_of_file_outside_project_uses_name(project, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("данные", encoding="utf-8")

    snapshot.snapshot_file(str(outside))

    assert list((project / ".agent-cache" / "backups").rglob("outside.txt"))


def test_max_backups_limits_history(project, monkeypatch):
    monkeypatch.setattr(config, "MAX_BACKUPS", 2)
    backup_root = project / ".agent-cache" / "backups"
    for i in range(5):
        stamp = backup_root / f"2026-01-01-00000{i}"
        stamp.mkdir(parents=True)
        (stamp / "old.txt").write_text("старое", encoding="utf-8")

    snapshot._cleanup_old()

    kept = sorted(p.name for p in backup_root.iterdir())
    assert kept == ["2026-01-01-000003", "2026-01-01-000004"]


def test_snapshot_dir_excludes_cache_and_git(project):
    (project / "src").mkdir()
    (project / "src" / "a.txt").write_text("a", encoding="utf-8")
    (project / ".agent-cache").mkdir()
    (project / ".agent-cache" / "junk.txt").write_text("junk", encoding="utf-8")

    result = snapshot.snapshot_dir(str(project))

    assert result.endswith(".zip")
    import zipfile
    with zipfile.ZipFile(result.split("-> ")[1]) as zf:
        names = zf.namelist()
    assert "src/a.txt" in names
    assert not any("junk" in name for name in names)


# ---------- Кэш ----------

def _fill_cache(project):
    (project / ".agent-cache" / "backups" / "2026-01-01-000000").mkdir(parents=True)
    (project / ".agent-cache" / "backups" / "2026-01-01-000000" / "a.txt").write_text(
        "x" * 2048, encoding="utf-8")
    (project / ".agent-cache" / "logs").mkdir(parents=True)
    (project / ".agent-cache" / "logs" / "session.log").write_text("log", encoding="utf-8")
    (project / ".agent-cache" / "history.txt").write_text("history", encoding="utf-8")


def test_cache_overview_counts_parts(project):
    _fill_cache(project)

    info = cache.cache_overview(project)

    assert info["backups"]["count"] == 1
    assert info["logs"]["count"] == 1
    assert info["history"]["count"] == 1
    assert info["total_items"] == 3
    assert info["total_bytes"] >= 2048
    assert "снапшоты:" in cache.format_overview(info)


def test_cache_overview_on_empty_project(project):
    info = cache.cache_overview(project)

    assert info["total_items"] == 0
    assert cache.has_cache(project) is False


def test_clear_cache_keeps_project_files(project):
    _fill_cache(project)
    (project / "important.txt").write_text("не трогать", encoding="utf-8")

    report = cache.clear_cache(project)

    assert "Кэш очищен" in report
    assert (project / "important.txt").read_text(encoding="utf-8") == "не трогать"
    assert not (project / ".agent-cache" / "backups").exists()
    assert not (project / ".agent-cache" / "logs").exists()
    assert not (project / ".agent-cache" / "history.txt").exists()


def test_clear_cache_with_single_part(project):
    _fill_cache(project)

    cache.clear_cache(project, parts=("logs",))

    assert not (project / ".agent-cache" / "logs").exists()
    assert (project / ".agent-cache" / "backups").is_dir()
    assert (project / ".agent-cache" / "history.txt").is_file()


def test_clear_empty_cache_reports_nothing_to_do(project):
    assert cache.clear_cache(project) == "Кэш пуст — очищать нечего."


def test_human_size():
    assert cache.human_size(0) == "0 Б"
    assert cache.human_size(2048) == "2,0 КБ"
    assert cache.human_size(3 * 1024 * 1024) == "3,0 МБ"
