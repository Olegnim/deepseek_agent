"""Тесты автолинта: выбор правила, отчёт, поведение без утилиты.

Проверки идут через тот же интерпретатор, что запускает тесты
(`python -m py_compile`), поэтому внешние утилиты (php, javac, kotlinc)
для тестов не нужны.
"""

from __future__ import annotations

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
