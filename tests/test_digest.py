"""Тесты выжимки из вывода инструментов (tools/digest.py).

Проверяем главное: в контекст не уходит простыня, но ничего не теряется —
полный текст лежит в .agent-cache/output, а в выжимке видны ошибки.
"""

from __future__ import annotations

import re

import config
from tools import digest


def _saved_path(result: str) -> str:
    m = re.search(r"Полный вывод сохранён: (\S+)", result)
    assert m, result
    return m.group(1)


# ---------- Ключевые слова ----------

def test_keywords_from_drops_stop_words_and_short_tokens():
    words = digest.keywords_from("найди file path TestRunner в project_root")

    assert "TestRunner" in words
    assert "project_root" in words
    assert "file" not in words            # стоп-слово
    assert all(len(w) >= 3 for w in words)


def test_keywords_from_accepts_dict_arguments():
    words = digest.keywords_from({"path": "tools/search.py", "pattern": "def"})

    assert any("search" in w for w in words)


# ---------- compress ----------

def test_small_text_passes_through(project):
    text = "exit=0\nSTDOUT:\nhello\nSTDERR:\n"

    assert digest.compress("run_shell", text) == text


def test_big_text_is_compressed_and_saved(project):
    lines = [f"строка {i}" for i in range(1, 1001)]
    lines[500] = "ERROR: сборка упала"
    text = "\n".join(lines)

    result = digest.compress("run_shell", text, keywords=["сборка"])

    assert len(result) < len(text)
    assert "выжимка из вывода run_shell" in result
    assert "1: строка 1" in result                     # начало сохранено
    assert "1000: строка 1000" in result               # конец сохранён
    assert "ERROR: сборка упала" in result             # ошибка видна
    assert "строк пропущено" in result

    saved = _saved_path(result)
    full = (config.PROJECT_ROOT / saved).read_text(encoding="utf-8")
    assert full == text                                # ничего не потеряно


def test_compress_keeps_keyword_lines(project):
    text = "\n".join(["шум"] * 400 + ["os.environ['API_KEY']"] + ["шум"] * 400)

    result = digest.compress("grep", text, keywords=["API_KEY"])

    assert "os.environ['API_KEY']" in result


def test_compress_is_idempotent_for_digests(project):
    text = "\n".join(f"line {i}" for i in range(2000))
    once = digest.compress("run_shell", text)

    assert digest.compress("run_shell", once) == once


def test_compress_respects_disabled_setting(project, apply_config):
    apply_config({"tools": {"output": {"enabled": False}}})
    text = "\n".join(str(i) for i in range(5000))

    assert digest.compress("run_shell", text) == text


def test_compress_keeps_output_dir_small(project, apply_config):
    apply_config({"tools": {"output": {"max_chars": 200, "keep_files": 2}}})
    text = "\n".join(f"строка {i}" for i in range(300))

    for _ in range(4):
        digest.compress("run_shell", text)

    out_dir = config.cache_dir(config.PROJECT_ROOT) / "output"
    assert len(list(out_dir.iterdir())) <= 2


# ---------- excerpt (веб-страницы) ----------

def test_excerpt_selects_relevant_paragraphs(project):
    text = "\n\n".join([
        "Введение: общая информация о библиотеке.",
        "Установка: pip install example-package",
        "Асинхронность: используйте asyncio.gather для параллельных запросов.",
        "Лицензия: MIT.",
    ] * 40)

    result = digest.excerpt(text, ["asyncio"], max_chars=400)

    assert "asyncio.gather" in result
    assert "фрагменты по словам" in result
    assert len(result) < len(text)


def test_excerpt_without_matches_returns_head(project):
    text = "\n\n".join(["абзац про кошек"] * 200)

    result = digest.excerpt(text, ["kubernetes"], max_chars=300)

    assert "абзац про кошек" in result
    assert "нет слов kubernetes" in result


def test_compress_result_skips_reading_tools(project):
    text = "\n".join(f"line {i}" for i in range(5000))

    assert digest.compress_result("read_file", text, {"path": "big.py"}) == text
    assert digest.compress_result("filesystem__read_file", text, {}) == text
    assert "выжимка" in digest.compress_result("run_shell", text, {"command": "pytest"})


def test_excerpt_small_text_passes_through(project):
    assert digest.excerpt("короткий текст", ["что"], max_chars=1000) == "короткий текст"
