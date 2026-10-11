"""Общие фикстуры тестов.

Запуск из корня проекта (там, где лежат `agent.py` и `tools/`):

    python -m pytest

Тесты не ходят в сеть, не обращаются к DeepSeek API и не требуют внешних
утилит (`php`, `javac`, `kotlinc` и т.п.): всё нужное создаётся во временных
папках. Модули агента берутся из корня репозитория, а не из установленного
пакета, поэтому тестируется именно текущий код.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from tools import snapshot  # noqa: E402
from tools import vscode as vscode_tools  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Временный проект: cwd, PROJECT_ROOT и каталог снапшотов указывают на него.

    По завершении теста настройки возвращаются к папке самого агента, а модуль
    снапшотов забывает временный корень.
    """
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.chdir(root)
    config.setup(str(root))
    snapshot.set_project_root(root)
    _reset_probe()

    try:
        yield root
    finally:
        snapshot.set_project_root(None)
        config.setup(str(ROOT))
        _reset_probe()


@pytest.fixture
def apply_config(project):
    """Пишет `.agent.config.json` в проект и перечитывает настройки.

    Имитирует запуск с `-p <проект>`: конфиг проекта читается заново, как это
    делает `main_async` через `config.setup()`.
    """
    def _apply(data: dict):
        (project / ".agent.config.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        config.setup(str(project))
        return project

    return _apply


@pytest.fixture
def agent_module(project):
    """Модуль `agent` с PROJECT_ROOT, направленным на временный проект."""
    import agent

    agent.PROJECT_ROOT = project
    agent.CONFIRM_MODE = False
    yield agent
    agent.PROJECT_ROOT = Path(ROOT)


@pytest.fixture
def no_registry_env(monkeypatch):
    """Читает переменные окружения только из os.environ.

    На Windows `config.env_value` дополнительно смотрит в реестр (`setx` пишет
    туда). В тестах это сделало бы результат зависимым от машины, поэтому на
    время теста реестр отключается.
    """
    monkeypatch.setattr(
        config, "env_value",
        lambda name, default="": os.environ.get(name) or default,
    )


def _reset_probe() -> None:
    """Сбрасывает кэш живости моста VS Code (см. tools/vscode.py)."""
    vscode_tools._probe["at"] = 0.0
    vscode_tools._probe["alive"] = False
