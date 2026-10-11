"""Тесты конфигурации: приоритеты, подстановки, разбор значений.

Проверяется то, из-за чего чаще всего «агент смотрит не туда»: какой корень
проекта выбран, какой конфиг перекрыл какой, как раскрылись пути и лимиты.
"""

from __future__ import annotations

import json

import pytest

import config


# ---------- Приоритет корня проекта ----------

def test_defaults_used_without_any_config(project):
    """Проект без конфига: работают значения из DEFAULTS."""
    assert config.PROJECT_ROOT == project
    assert config.MODEL == config.DEFAULTS["api"]["model"]
    assert config.shell_timeout() == config.DEFAULTS["tools"]["shell_timeout"]
    assert config.lint_settings()["enabled"] is True


def test_project_config_overrides_agent_config(apply_config):
    """`.agent.config.json` проекта перекрывает agent.config.json и дефолты."""
    apply_config({
        "api": {"model": "test-model", "temperature": 0.7},
        "tools": {"shell_timeout": 5},
        "lint": {"enabled": False},
    })
    assert config.MODEL == "test-model"
    assert config.TEMPERATURE == 0.7
    assert config.shell_timeout() == 5
    assert config.lint_settings()["enabled"] is False


def test_flag_beats_env_and_config(tmp_path, project, apply_config, monkeypatch,
                                   no_registry_env):
    """Флаг -p важнее и переменной окружения, и конфига в папке запуска."""
    apply_config({"paths": {"project_root": str(tmp_path / "from_config")}})
    monkeypatch.setenv("DEEPSEEK_PROJECT_ROOT", str(tmp_path / "from_env"))
    flag_root = tmp_path / "from_flag"
    flag_root.mkdir()

    assert config.setup(str(flag_root)) == flag_root
    assert config.PROJECT_ROOT == flag_root


def test_env_beats_config_in_cwd(tmp_path, project, apply_config, monkeypatch,
                                 no_registry_env):
    """DEEPSEEK_PROJECT_ROOT важнее paths.project_root из конфига в папке запуска."""
    apply_config({"paths": {"project_root": str(tmp_path / "from_config")}})
    from_env = tmp_path / "from_env"
    from_env.mkdir()
    monkeypatch.setenv("DEEPSEEK_PROJECT_ROOT", str(from_env))

    assert config.resolve_project_root() == from_env


def test_project_root_from_config_in_cwd(tmp_path, project, apply_config,
                                         monkeypatch, no_registry_env):
    """Без флага и переменной корень берётся из конфига в папке запуска."""
    monkeypatch.delenv("DEEPSEEK_PROJECT_ROOT", raising=False)
    target = tmp_path / "real_project"
    target.mkdir()
    apply_config({"paths": {"project_root": str(target)}})

    assert config.setup() == target


def test_paths_project_root_in_config_cannot_move_root(tmp_path, project,
                                                       apply_config):
    """paths.project_root из проектного конфига не переопределяет уже решённый корень."""
    apply_config({"paths": {"project_root": str(tmp_path / "somewhere_else")}})

    assert config.PROJECT_ROOT == project
    assert config.PATHS["project_root"] == str(project)


# ---------- Подстановки ----------

def test_substitutions_in_strings_lists_and_dicts(project, apply_config,
                                                  monkeypatch, no_registry_env):
    """${env:VAR} и ${agent_home} раскрываются в строках и вложенных списках."""
    monkeypatch.setenv("TEST_TOKEN", "abc123")
    apply_config({
        "paths": {"plugins_dirs": ["${agent_home}/plugins", "plugins"]},
        "agent": {"instructions": ["токен: ${env:TEST_TOKEN}"]},
    })

    assert config.PATHS["plugins_dirs"][0] == f"{config.AGENT_HOME}/plugins"
    assert "abc123" in config.agent_instructions()


@pytest.mark.xfail(reason="известный дефект config.setup(): первый проход подстановок "
                          "выполняется без переменной project_root, поэтому "
                          "${project_root} в конфиге превращается в пустую строку "
                          "и путь теряет корень проекта", strict=False)
def test_project_root_substitution_in_config_values(project, apply_config):
    apply_config({"paths": {"skills_dir": "${project_root}/my-skills"}})

    assert config.PATHS["skills_dir"] == f"{project}/my-skills"


def test_unknown_substitution_becomes_empty(project, apply_config):
    """Неизвестная подстановка не роняет загрузку — превращается в пустую строку."""
    apply_config({"api": {"base_url": "https://${unknown_host}/v1"}})

    assert config.BASE_URL == "https:///v1"


# ---------- Разбор значений ----------

@pytest.mark.parametrize("raw,expected", [
    (None, 0),
    (0, 0),
    (65536, 65536),
    ("65536", 65536),
    ("128k", 128_000),
    ("1M", 1_000_000),
    (" 64 K ", 64_000),
    ("abc", 0),
    ("", 0),
])
def test_parse_token_count(raw, expected):
    assert config.parse_token_count(raw) == expected


def test_fmt_tokens():
    assert config.fmt_tokens(1_000_000) == "1 000 000"


def test_deep_merge_is_recursive_and_does_not_mutate_base():
    base = {"a": {"b": 1, "c": 2}, "list": [1]}
    merged = config.deep_merge(base, {"a": {"c": 3}, "list": [1, 2]})

    assert merged == {"a": {"b": 1, "c": 3}, "list": [1, 2]}
    assert base == {"a": {"b": 1, "c": 2}, "list": [1]}       # base не изменён


def test_broken_json_is_skipped(project, capsys):
    """Битый JSON не роняет агент: файл пропускается с сообщением."""
    (project / ".agent.config.json").write_text("{ это не json", encoding="utf-8")

    config.setup(str(project))

    assert "[config]" in capsys.readouterr().out
    assert config.MODEL == config.DEFAULTS["api"]["model"]


# ---------- Пути к ресурсам ----------

def test_backup_dir_and_cache_dir_are_inside_project(project):
    assert config.backup_dir(project) == project / ".agent-cache" / "backups"
    assert config.cache_dir(project) == project / ".agent-cache"


def test_absolute_backup_dir_is_used_as_is(tmp_path, project, apply_config):
    outside = tmp_path / "snapshots"
    apply_config({"paths": {"backup_dir": str(outside)}})

    assert config.backup_dir() == outside
    # cache_dir для внешнего каталога — .agent-cache в проекте (не папка проекта).
    assert config.cache_dir(project) == project / ".agent-cache"


def test_mcp_config_and_skills_search_project_first(project):
    """Ресурсы ищутся сначала в проекте, затем рядом с агентом."""
    project_mcp = project / "mcp_config.json"
    project_mcp.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    (project / "skills").mkdir()

    paths = config.mcp_config_paths(project)
    assert paths[0] == project_mcp
    assert config.AGENT_HOME / "mcp_config.json" in paths
    assert config.skills_candidates(project) == [project / "skills",
                                                 config.AGENT_HOME / "skills"]


def test_plugins_candidates_returns_only_existing_dirs(project):
    assert config.plugins_candidates(project) == []
    plugins = project / "plugins"
    plugins.mkdir()

    assert config.plugins_candidates(project) == [plugins]


# ---------- Профили ----------

def test_profile_switch_and_unknown_profile(apply_config):
    apply_config({"profiles": {"mine": {"description": "Мой профиль",
                                        "skills": ["code-quality"]}}})

    assert "mine" in config.profile_names()
    assert config.set_profile("mine") == "mine"
    assert config.active_profile()["description"] == "Мой профиль"
    assert config.set_profile("no-such-profile") == "no-such-profile"
    assert config.active_profile() == {}          # неизвестный профиль — авто
    assert config.set_profile("") == ""           # "" = авто по стеку


def test_settings_summary_mentions_project(project):
    summary = config.settings_summary()

    assert str(project) in summary
    assert "model:" in summary


def test_lint_section_works_as_top_level_key(project, apply_config):
    """Рабочий вариант — секция lint верхнего уровня."""
    apply_config({"lint": {"enabled": False}})

    assert config.lint_settings()["enabled"] is False


@pytest.mark.xfail(reason="известный дефект config.setup(): DEFAULTS всегда содержит "
                          "секцию lint, поэтому fallback на tools.lint недостижим — "
                          "там заданные правила автолинта игнорируются", strict=False)
def test_lint_section_falls_back_to_tools_lint(project, apply_config):
    """Правила автолинта задуманы работоспособными и в секции tools.lint."""
    apply_config({"tools": {"lint": {"enabled": False}}})

    assert config.lint_settings()["enabled"] is False
