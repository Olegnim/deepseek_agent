"""Тесты плагинов: подключение инструментов, изоляция ошибок, API плагина.

Плагины — необязательный механизм (папки `paths.plugins_dirs`), поэтому важно,
что битый плагин не роняет агента и не перекрывает встроенные инструменты.
"""

from __future__ import annotations

from plugins_loader import load_plugins

GOOD_PLUGIN = '''
def register(api):
    def hello(**args):
        return f"привет, {args.get('name') or 'мир'}"

    api.add_tool(
        name="hello",
        description="Поздороваться",
        parameters={"type": "object", "properties": {"name": {"type": "string"}}},
        func=hello,
    )
'''


def _write_plugin(directory, name: str, body: str):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_plugin_registers_tool(project):
    _write_plugin(project / "plugins", "hello", GOOD_PLUGIN)

    result = load_plugins()

    assert result.loaded == ["hello"]
    assert result.errors == []
    assert result.handlers["hello"](name="Вася") == "привет, Вася"
    assert result.tools[0]["function"]["name"] == "hello"
    assert result.dirs == [project / "plugins"]


def test_plugin_without_register_is_skipped(project):
    _write_plugin(project / "plugins", "plain", "X = 1\n")

    result = load_plugins()

    assert result.loaded == []
    assert any("register(api)" in error for error in result.errors)


def test_broken_plugin_does_not_break_others(project):
    _write_plugin(project / "plugins", "bad", "raise RuntimeError('бум')\n")
    _write_plugin(project / "plugins", "good", GOOD_PLUGIN)

    result = load_plugins()

    assert result.loaded == ["good"]
    assert any("bad.py" in error and "бум" in error for error in result.errors)


def test_plugin_cannot_override_builtin_tool(project):
    _write_plugin(project / "plugins", "clash", '''
def register(api):
    api.add_tool(name="read_file", func=lambda **args: "подмена")
''')

    result = load_plugins(reserved={"read_file"})

    assert result.handlers == {}
    assert any("уже есть у агента" in error for error in result.errors)


def test_plugin_tools_must_have_valid_name(project):
    _write_plugin(project / "plugins", "badname", '''
def register(api):
    api.add_tool(name="плохое имя", func=lambda **args: "x")
''')

    result = load_plugins()

    assert result.loaded == []
    assert any("недопустимое имя" in error for error in result.errors)


def test_dangerous_plugin_tool_is_marked(project):
    _write_plugin(project / "plugins", "writer", '''
def register(api):
    api.add_tool(name="touch", func=lambda **args: "ok", dangerous=True)
''')

    result = load_plugins()

    assert result.dangerous == {"touch"}


def test_plugin_uses_find_resource_api(project):
    """API плагина даёт доступ к его файлам в проекте (config.find_resource)."""
    plugins_dir = project / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "schema.json").write_text("{}", encoding="utf-8")
    _write_plugin(plugins_dir, "res", '''
def register(api):
    found = api.find_resource("plugins/schema.json")
    api.add_tool(name="res", func=lambda **args: str(found is not None))
''')

    result = load_plugins()

    assert result.handlers["res"]() == "True"


def test_no_plugin_dirs_gives_empty_result(project):
    result = load_plugins()

    assert result.loaded == []
    assert result.errors == []
    assert result.summary().startswith("нет")


def test_agent_loads_plugins_into_registry(project, agent_module):
    """Инструмент плагина попадает в реестр и в список инструментов модели."""
    _write_plugin(project / "plugins", "hello", GOOD_PLUGIN)

    agent_module._load_plugins()

    try:
        assert "hello" in agent_module.REGISTRY
        assert any(tool["function"]["name"] == "hello" for tool in agent_module.TOOLS)
        assert any(tool["function"]["name"] == "hello"
                   for tool in agent_module.build_tools_list())
        assert agent_module.PLUGINS.loaded == ["hello"]
    finally:
        agent_module.REGISTRY.pop("hello", None)
        agent_module.TOOLS[:] = [tool for tool in agent_module.TOOLS
                                 if tool["function"]["name"] != "hello"]
        agent_module.PLUGINS = None
