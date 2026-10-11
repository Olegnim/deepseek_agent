"""Тесты моста к VS Code (Python-сторона).

HTTP-сервер не поднимается: проверяются поиск дескриптора, разбор порога
доверия к нему (битый JSON, мусорный порт), песочница путей и сообщения,
которые видит пользователь, когда редактор закрыт.
"""

from __future__ import annotations

import json

import config
from tools import vscode as vscode_tools


def _write_bridge(project, info) -> None:
    cache = project / ".agent-cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "vscode-bridge.json").write_text(
        info if isinstance(info, str) else json.dumps(info), encoding="utf-8")


def test_bridge_file_lives_in_project_cache(project):
    assert vscode_tools.bridge_file(project) == project / ".agent-cache" / "vscode-bridge.json"


def test_bridge_info_without_file(project):
    assert vscode_tools.bridge_info(project) is None
    assert vscode_tools.available(force=True) is False


def test_bridge_info_ignores_broken_descriptor(project):
    _write_bridge(project, "{ это не json")

    assert vscode_tools.bridge_info(project) is None


def test_bridge_info_requires_valid_port(project):
    for bad_port in ("не число", 0, 70000, None):
        _write_bridge(project, {"port": bad_port, "token": "t"})
        assert vscode_tools.bridge_info(project) is None

    _write_bridge(project, {"port": 61234, "token": "t", "workspace": str(project)})
    assert vscode_tools.bridge_info(project)["port"] == 61234


def test_available_is_false_when_nothing_listens(project):
    """Файл есть, но сервер не отвечает — считаем мост мёртвым, без исключений."""
    _write_bridge(project, {"port": 59998, "token": "t"})

    assert vscode_tools.available(force=True) is False


def test_disabled_integration_hides_everything(project, apply_config):
    _write_bridge(project, {"port": 61234, "token": "t"})
    apply_config({"vscode": {"enabled": False}})

    assert vscode_tools.available(force=True) is False
    assert vscode_tools.auto_open("a.txt") == ""
    assert "выключена" in vscode_tools.vscode_status()


def test_paths_outside_project_are_blocked(project, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    assert vscode_tools.vscode_open(str(outside)).startswith("VS Code: не удалось")
    assert vscode_tools.vscode_diff(str(outside)).startswith("VS Code: не удалось")


def test_tools_report_missing_bridge(project):
    assert "мост не найден" in vscode_tools.vscode_status()
    assert "мост не найден" in vscode_tools.vscode_open("a.txt")
    assert "мост не найден" in vscode_tools.vscode_close_all()


def test_auto_open_is_silent_without_bridge(project):
    """Авто-открытие никогда не мешает работе: без моста — пустая строка."""
    assert vscode_tools.auto_open("a.txt") == ""


def test_latest_snapshot_is_found_by_relative_path(project):
    (project / "src").mkdir()
    (project / "src" / "a.py").write_text("новое", encoding="utf-8")
    old = project / ".agent-cache" / "backups" / "2026-01-01-000000" / "src"
    old.mkdir(parents=True)
    (old / "a.py").write_text("старое", encoding="utf-8")

    found = vscode_tools._latest_snapshot(project / "src" / "a.py")

    assert found is not None
    assert found.read_text(encoding="utf-8") == "старое"


def test_latest_snapshot_without_backups(project):
    (project / "a.py").write_text("x", encoding="utf-8")

    assert vscode_tools._latest_snapshot(project / "a.py") is None


def test_vscode_diff_asks_for_original_without_snapshot(project):
    (project / "a.py").write_text("x", encoding="utf-8")
    _write_bridge(project, {"port": 61234, "token": "t"})

    result = vscode_tools.vscode_diff("a.py")

    assert "нет снапшота" in result


def test_relative_path_display(project):
    assert vscode_tools._rel(project / "src" / "a.py") == "src/a.py"
    assert vscode_tools._rel(project) == "."


def test_extension_name_matches_package_json():
    """Имя расширения в tools/vscode.py и в package.json не должны разойтись."""
    package = json.loads(
        (config.AGENT_HOME / "vscode-extension" / "package.json").read_text(encoding="utf-8")
    )

    assert package["name"] == vscode_tools.BRIDGE_EXTENSION
