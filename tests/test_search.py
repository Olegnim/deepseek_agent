"""Тесты инструментов поиска и навигации (tools/search.py).

Проверяются три вещи: результат компактный и группированный, ничего лишнего
не читается целиком, а сравнение файлов показывает только изменения.
"""

from __future__ import annotations

import config
from tools import search


# ---------- search_code ----------

def test_search_code_groups_matches_by_file(project):
    (project / "src").mkdir()
    (project / "src" / "a.py").write_text(
        "def load():\n    return 1\n\ndef save():\n    return 2\n", encoding="utf-8")
    (project / "src" / "b.py").write_text("load()\n", encoding="utf-8")

    result = search.search_code("load", str(project), ".py")

    assert "Найдено 2 совпадений в 2 файлах" in result
    assert "src/a.py (1)" in result and "src/b.py (1)" in result
    assert "1: def load():" in result


def test_search_code_context_lines(project):
    (project / "a.py").write_text("one\ntwo\nneedle\nfour\n", encoding="utf-8")

    result = search.search_code("needle", str(project), ".py", context=1)

    assert "~    2: two" in result
    assert "     3: needle" in result
    assert "~    4: four" in result


def test_search_code_fixed_and_ignore_case(project):
    (project / "a.py").write_text("A.B = 1\naXb = 2\n", encoding="utf-8")

    assert "aXb" not in search.search_code("A.B", str(project), ".py", fixed=True)
    assert search.search_code("a.b", str(project), ".py",
                              fixed=True, ignore_case=True).count(":") >= 2


def test_search_code_files_only(project):
    (project / "a.py").write_text("hit\nhit\n", encoding="utf-8")
    (project / "b.py").write_text("hit\n", encoding="utf-8")

    result = search.search_code("hit", str(project), ".py", files_only=True)

    assert "Файлов с совпадениями: 2" in result
    assert "a.py (2)" in result


def test_search_code_respects_max_results(project):
    (project / "a.py").write_text("hit\n" * 50, encoding="utf-8")

    result = search.search_code("hit", str(project), ".py", max_results=5)

    assert "показано 5 из 50" in result


def test_search_code_no_matches_and_bad_regex(project):
    assert search.search_code("нет_такого", str(project)).startswith("Совпадений не найдено")
    assert search.search_code("([", str(project)).startswith("ERROR: некорректный regex")


def test_search_code_single_file(project):
    path = project / "one.py"
    path.write_text("alpha\nbeta\n", encoding="utf-8")

    result = search.search_code("beta", str(path))

    assert "one.py (1)" in result


# ---------- file_outline ----------

def test_file_outline_python_symbols(project):
    path = project / "mod.py"
    path.write_text(
        '"""Модуль."""\n'
        "\n"
        "class Repo:\n"
        '    """Хранилище."""\n'
        "\n"
        "    def find(self):\n"
        "        return 1\n"
        "\n"
        "def main():\n"
        "    pass\n",
        encoding="utf-8",
    )

    result = search.file_outline(str(path))

    assert "mod.py — Python" in result
    assert "class Repo" in result and "Хранилище" in result
    assert "def find" in result and "def main" in result
    assert "read_symbol" in result


def test_file_outline_python_syntax_error_is_reported(project):
    path = project / "broken.py"
    path.write_text("def oops(:\n    pass\n", encoding="utf-8")

    result = search.file_outline(str(path))

    assert "не разбирается как Python" in result


def test_file_outline_php_and_js(project):
    php = project / "a.php"
    php.write_text("<?php\nclass User {\n    public function save() {}\n}\n",
                   encoding="utf-8")
    js = project / "a.js"
    js.write_text("export function run() {\n  return 1;\n}\n", encoding="utf-8")

    assert "class User" in search.file_outline(str(php))
    assert "function save" in search.file_outline(str(php))
    assert "function run" in search.file_outline(str(js))


def test_file_outline_directory_lists_code_files(project):
    (project / "pkg").mkdir()
    (project / "pkg" / "x.py").write_text("def a():\n    pass\n", encoding="utf-8")

    result = search.file_outline(str(project / "pkg"))

    assert "pkg/x.py" in result


# ---------- read_symbol ----------

def test_read_symbol_returns_body(project):
    path = project / "mod.py"
    path.write_text(
        "import os\n"
        "\n"
        "def outer():\n"
        "    value = 1\n"
        "    return value\n"
        "\n"
        "def other():\n"
        "    pass\n",
        encoding="utf-8",
    )

    result = search.read_symbol("outer", str(path))

    assert "mod.py:3-5" in result
    assert "value = 1" in result
    assert "def other" not in result


def test_read_symbol_truncates_long_body(project):
    path = project / "mod.py"
    body = "\n".join(f"    x{i} = {i}" for i in range(200))
    path.write_text(f"def big():\n{body}\n", encoding="utf-8")

    result = search.read_symbol("big", str(path), max_lines=20)

    assert "тело обрезано" in result
    assert "read_range" in result


def test_read_symbol_searches_project_and_reports_ambiguity(project):
    (project / "a.py").write_text("def target():\n    pass\n", encoding="utf-8")
    (project / "b.py").write_text("def target():\n    pass\n", encoding="utf-8")

    result = search.read_symbol("target", str(project))

    assert "встречается в 2 файлах" in result
    assert "a.py:1" in result and "b.py:1" in result


def test_read_symbol_not_found(project):
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")

    assert search.read_symbol("missing", str(project)).startswith("ERROR")


# ---------- diff_files ----------

def test_diff_files_shows_only_changes(project):
    a = project / "old.txt"
    b = project / "new.txt"
    a.write_text("one\ntwo\nthree\n", encoding="utf-8")
    b.write_text("one\nTWO\nthree\n", encoding="utf-8")

    result = search.diff_files(str(a), str(b))

    assert "+TWO" in result and "-two" in result
    assert "+1 / -1" in result
    assert "old.txt -> new.txt" in result


def test_diff_files_identical(project):
    a = project / "a.txt"
    a.write_text("same\n", encoding="utf-8")

    assert search.diff_files(str(a), str(a)).startswith("Файлы идентичны")


def test_diff_files_missing_file(project):
    assert search.diff_files(str(project / "no1"), str(project / "no2")).startswith(
        "ERROR: файл не найден")


def test_diff_files_trims_huge_diff_but_keeps_full_copy(project, apply_config):
    apply_config({"tools": {"output": {"max_chars": 400}}})
    a = project / "a.txt"
    b = project / "b.txt"
    a.write_text("\n".join(f"line{i}" for i in range(500)), encoding="utf-8")
    b.write_text("\n".join(f"changed{i}" for i in range(500)), encoding="utf-8")

    result = search.diff_files(str(a), str(b))

    assert "дифф обрезан" in result
    saved = result.split("Полный дифф: ")[1].split(" — ")[0]
    assert (config.PROJECT_ROOT / saved).is_file()


# ---------- find_files / project_map ----------

def test_find_files_skips_noise_dirs(project):
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "dep.py").write_text("", encoding="utf-8")

    result = search.find_files("**/*.py", str(project))

    assert "src/main.py" in result
    assert "node_modules" not in result


def test_find_files_reports_empty(project):
    assert search.find_files("*.nomatch", str(project)).startswith("Файлов по маске")


def test_find_files_accepts_single_file(project):
    (project / "main.py").write_text("", encoding="utf-8")

    assert search.find_files("*.py", "main.py") == "main.py"
    assert search.find_files("*", "нет.py").startswith("ERROR: путь не найден")


def test_project_map_limits_depth(project):
    (project / "src").mkdir()
    (project / "src" / "deep").mkdir()
    (project / "src" / "deep" / "file.py").write_text("", encoding="utf-8")

    result = search.project_map(depth=1, max_entries=20)

    assert "src/" in result
    assert "file.py" not in result
