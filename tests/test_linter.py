"""Тесты автолинта: выбор правила, отчёт, поведение без утилиты.

Проверки идут через тот же интерпретатор, что запускает тесты
(`python -m py_compile`), поэтому внешние утилиты (php, javac, kotlinc)
для тестов не нужны.
"""

from __future__ import annotations

import config
from tools import linter

PY_RULE = {
    "ext": [".py"],
    "command": "python -m py_compile {file}",
    "label": "python -m py_compile",
}


def _apply_rules(apply_config, rules, enabled=True):
    apply_config({"lint": {"enabled": enabled, "rules": rules, "timeout": 30}})


def test_lint_disabled_returns_none(project, apply_config):
    _apply_rules(apply_config, [PY_RULE], enabled=False)
    (project / "ok.py").write_text("x = 1\n", encoding="utf-8")

    assert linter.lint_enabled() is False
    assert linter.lint_file(project / "ok.py") is None


def test_rule_selected_by_extension(project, apply_config):
    _apply_rules(apply_config, [
        {"ext": [".php", ".phtml"], "command": "php -l {file}", "label": "php -l"},
        PY_RULE,
    ])

    assert linter.find_rule("a.php")["label"] == "php -l"
    assert linter.find_rule("a.PY")["label"] == "python -m py_compile"
    assert linter.find_rule("a.txt") is None
    assert linter.find_rule("Makefile") is None          # без расширения


def test_valid_file_reports_ok(project, apply_config):
    _apply_rules(apply_config, [PY_RULE])
    (project / "ok.py").write_text("x = 1\n", encoding="utf-8")

    assert linter.lint_file(project / "ok.py") == "линт python -m py_compile: OK"


def test_broken_file_reports_error_with_output(project, apply_config):
    _apply_rules(apply_config, [PY_RULE])
    (project / "broken.py").write_text("def f(:\n", encoding="utf-8")

    report = linter.lint_file(project / "broken.py")

    assert report.startswith("линт python -m py_compile: ОШИБКА")
    assert "broken.py" in report


def test_missing_tool_is_skipped(project, apply_config):
    _apply_rules(apply_config, [
        {"ext": [".php"], "command": "php-no-such-binary -l {file}", "label": "php -l"},
    ])
    (project / "a.php").write_text("<?php\n", encoding="utf-8")

    assert "утилита «php-no-such-binary» не найдена" in linter.lint_file(project / "a.php")


def test_missing_file_and_no_rule_return_none(project, apply_config):
    _apply_rules(apply_config, [PY_RULE])

    assert linter.lint_file(project / "нет-такого.py") is None
    assert linter.lint_file(project / "нет-такого.txt") is None


def test_lint_result_only_touches_write_and_edit(project, apply_config):
    _apply_rules(apply_config, [PY_RULE])
    (project / "ok.py").write_text("x = 1\n", encoding="utf-8")

    # Не файловый инструмент — результат не меняется.
    assert linter.lint_result("read_file", {"path": str(project / "ok.py")},
                              "содержимое") == "содержимое"
    # Ошибка правки — линт не запускается.
    assert linter.lint_result("write_file", {"path": str(project / "x.py")},
                              "ERROR: не записалось").startswith("ERROR")
    # Успешная правка — отчёт добавляется.
    report = linter.lint_result("write_file", {"path": str(project / "ok.py")},
                                "Записано")
    assert report.startswith("Записано\nлинт python -m py_compile: OK")


def test_describe_rules_marks_missing_tools(project, apply_config):
    _apply_rules(apply_config, [
        {"ext": [".php"], "command": "php-no-such-binary -l {file}", "label": "php"},
        PY_RULE,
    ])

    lines = linter.describe_rules()

    assert any("php-no-such-binary" in line and "нет утилиты" in line for line in lines)
    assert any(".py" in line and "нет утилиты" not in line for line in lines)


def test_python_rule_uses_current_interpreter(project, apply_config):
    """`python ...` в правиле заменяется на интерпретатор, которым идёт агент.

    Иначе правило не работало бы на macOS/Linux, где команды `python` нет.
    """
    _apply_rules(apply_config, [PY_RULE])

    command = linter.manual_command(PY_RULE)

    assert command.startswith(f'"{config.python_exe()}"')
    assert "{file}" not in command


def test_python_launcher_flag_is_dropped(project, apply_config):
    """`py -3 ...` (launcher Windows) не тащит свой флаг к конкретному python."""
    rule = {"ext": [".py"], "command": "py -3 -m py_compile {file}",
            "label": "py_compile"}
    _apply_rules(apply_config, [rule])

    command = linter.manual_command(rule)

    assert command == f'"{config.python_exe()}" -m py_compile'


def test_lint_output_is_decoded_as_utf8(project, apply_config):
    """Вывод утилиты в UTF-8 не превращается в мусор (локаль Windows — cp1251)."""
    rule = {
        "ext": [".py"],
        "command": ('python -c "import sys; '
                    "sys.stderr.buffer.write('ошибка'.encode('utf-8')); "
                    'sys.exit(1)" {file}'),
        "label": "utf8",
    }
    _apply_rules(apply_config, [rule])
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")

    report = linter.lint_file(project / "a.py")

    assert "ОШИБКА" in report
    assert "ошибка" in report


def test_lint_does_not_create_pycache_in_project(project, apply_config):
    """Байткод линта не сыплется в дерево проекта: он идёт в кэш интерпретатора."""
    _apply_rules(apply_config, [PY_RULE])
    (project / "ok.py").write_text("x = 1\n", encoding="utf-8")

    assert linter.lint_file(project / "ok.py") == "линт python -m py_compile: OK"
    assert not (project / "__pycache__").exists()


def test_python_rule_with_quoted_path_and_spaces(project, apply_config):
    """Путь к интерпретатору с пробелами в кавычках — рабочее правило.

    Раньше первое слово разбиралось по первому пробелу, поэтому такая команда
    считалась отсутствующей утилитой и линт молча пропускался.
    """
    rule = {"ext": [".py"],
            "command": '"C:/Program Files/Python/python.exe" -m py_compile {file}',
            "label": "py_compile"}
    _apply_rules(apply_config, [rule])
    (project / "ok.py").write_text("x = 1\n", encoding="utf-8")

    assert linter._missing_tool(rule["command"]) is None
    assert linter.lint_file(project / "ok.py") == "линт py_compile: OK"
    assert linter.manual_command(rule).startswith(f'"{config.python_exe()}"')
