"""Тесты файловых инструментов: чтение, запись, точечная правка, поиск.

Правки — самая рискованная часть агента, поэтому проверяются границы
(read_range), сохранение переводов строк (CRLF/LF) и поведение на ошибках.
"""

from __future__ import annotations

from tools import filesystem as fs


# ---------- Чтение ----------

def test_read_file_missing(tmp_path):
    assert fs.read_file(str(tmp_path / "нет.txt")).startswith("ERROR")


def test_read_file_returns_content(project):
    path = project / "a.txt"
    path.write_text("привет\nмир", encoding="utf-8")

    assert fs.read_file(str(path)) == "привет\nмир"


def test_read_file_truncates_large_files(project):
    path = project / "big.txt"
    path.write_text("x" * (fs.MAX_READ_BYTES + 1000), encoding="utf-8")

    result = fs.read_file(str(path))

    assert result.startswith("[файл обрезан")
    assert len(result) < fs.MAX_READ_BYTES + 1000
    assert "read_range" in result


def test_read_range_numbers_lines_and_limits_window(project):
    path = project / "lines.txt"
    path.write_text("\n".join(f"строка{i}" for i in range(1, 801)) + "\n",
                    encoding="utf-8")

    result = fs.read_range(str(path), 10, 12)
    assert result.splitlines() == [
        "    10: строка10", "    11: строка11", "    12: строка12",
    ]

    # Окно больше MAX_READ_RANGE_LINES строк — обрезается сверху.
    wide = fs.read_range(str(path), 1, fs.MAX_READ_RANGE_LINES + 100)
    assert len(wide.splitlines()) == fs.MAX_READ_RANGE_LINES


def test_read_range_swaps_reversed_bounds(project):
    path = project / "lines.txt"
    path.write_text("a\nb\nc\n", encoding="utf-8")

    assert fs.read_range(str(path), 3, 1) == "     3: c"


def test_read_range_missing_file(tmp_path):
    assert fs.read_range(str(tmp_path / "нет.txt")).startswith("ERROR")


# ---------- Запись ----------

def test_write_file_creates_dirs(project):
    target = project / "deep" / "nested" / "file.txt"

    result = fs.write_file(str(target), "текст")

    assert target.read_text(encoding="utf-8") == "текст"
    assert "Записано" in result


# ---------- Точечная правка ----------

def test_edit_file_replaces_first_occurrence_only(project):
    path = project / "a.txt"
    path.write_text("foo bar foo\n", encoding="utf-8")

    result = fs.edit_file(str(path), "foo", "baz")

    assert path.read_text(encoding="utf-8") == "baz bar foo\n"
    assert "всего вхождений: 2" in result          # модель предупреждена


def test_edit_file_replace_all(project):
    path = project / "a.txt"
    path.write_text("foo foo foo\n", encoding="utf-8")

    result = fs.edit_file(str(path), "foo", "baz", replace_all=True)

    assert path.read_text(encoding="utf-8") == "baz baz baz\n"
    assert "3 шт." in result


def test_edit_file_keeps_crlf(project):
    """Файл с CRLF остаётся с CRLF, даже если фрагмент пришёл с \\n."""
    path = project / "a.txt"
    path.write_bytes("строка1\r\nстрока2\r\n".encode("utf-8"))

    fs.edit_file(str(path), "строка1", "правка")

    assert path.read_bytes() == "правка\r\nстрока2\r\n".encode("utf-8")


def test_edit_file_keeps_lf(project):
    path = project / "a.txt"
    path.write_bytes("one\ntwo\n".encode("utf-8"))

    fs.edit_file(str(path), "one", "1")

    assert path.read_bytes() == b"1\ntwo\n"


def test_edit_file_fragment_not_found(project):
    path = project / "a.txt"
    path.write_text("текст\n", encoding="utf-8")

    result = fs.edit_file(str(path), "другой текст", "x")

    assert result.startswith("ERROR")
    assert path.read_text(encoding="utf-8") == "текст\n"


def test_edit_file_empty_old_text(project):
    path = project / "a.txt"
    path.write_text("текст\n", encoding="utf-8")

    assert fs.edit_file(str(path), "", "x").startswith("ERROR")


# ---------- Обзор проекта и листинг ----------

def test_project_outline_skips_noise_dirs(project):
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "dep.js").write_text("", encoding="utf-8")

    outline = fs.project_outline(str(project), depth=2)

    assert "src/" in outline and "main.py" in outline
    assert "node_modules" not in outline


def test_project_outline_respects_max_entries(project):
    for i in range(10):
        (project / f"file{i}.txt").write_text("", encoding="utf-8")

    outline = fs.project_outline(str(project), depth=1, max_entries=4)

    assert "обрезано на 4 записях" in outline


def test_list_dir_marks_directories(project):
    (project / "dir").mkdir()
    (project / "file.txt").write_text("", encoding="utf-8")

    assert fs.list_dir(str(project)) == "dir/\nfile.txt"
    assert fs.list_dir(str(project / "file.txt")).endswith("это файл, а не папка (читай его через read_file)")

    assert fs.list_dir(str(project / "нет")).startswith("ERROR")


# ---------- Поиск ----------

def test_grep_default_extensions_and_include_filter(project):
    (project / "code.py").write_text("needle = 1\n", encoding="utf-8")
    (project / "text.txt").write_text("needle = 1\n", encoding="utf-8")

    by_default = fs.grep("needle", str(project))
    assert "code.py:1: needle = 1" in by_default
    assert "text.txt" not in by_default              # .txt вне CODE_EXTENSIONS

    assert "text.txt" in fs.grep("needle", str(project), include=".txt")
    assert "text.txt" in fs.grep("needle", str(project), include="*")


def test_grep_skips_vendor_dirs(project):
    (project / "vendor").mkdir()
    (project / "vendor" / "lib.php").write_text("needle\n", encoding="utf-8")

    assert fs.grep("needle", str(project)) == "Совпадений не найдено"


def test_grep_reports_bad_regex_and_missing_dir(tmp_path):
    assert fs.grep("([", str(tmp_path)).startswith("ERROR: некорректный regex")
    assert fs.grep("x", str(tmp_path / "нет")).startswith("ERROR")


def test_grep_accepts_single_file(project):
    (project / "code.py").write_text("needle = 1\nhay\n", encoding="utf-8")
    (project / "other.py").write_text("needle = 2\n", encoding="utf-8")

    # Путь к файлу — ищем только в нём, include игнорируется
    assert fs.grep("needle", "code.py") == "code.py:1: needle = 1"
    assert fs.grep("needle", str(project / "code.py"), include=".md") == \
        "code.py:1: needle = 1"
    assert fs.grep("нет-такого", "code.py") == "Совпадений не найдено"


def test_grep_limits_results(project, monkeypatch):
    monkeypatch.setattr(fs, "MAX_GREP_RESULTS", 3)
    (project / "many.py").write_text("hit\n" * 10, encoding="utf-8")

    result = fs.grep("hit", str(project))

    assert "обрезано" in result
    matches = [line for line in result.splitlines() if line.endswith(": hit")]
    assert len(matches) == 3
