"""Тесты определения стека проекта и загрузки навыков.

От этих двух модулей зависит, какие правила получит модель: стек выбирает
навыки по `applies_to`, а профиль — по явному списку имён.
"""

from __future__ import annotations

import json

from skills_loader import (
    load_skill_map, load_skills_for_stack, parse_front_matter, skill_applies_to,
)
from tools import stack


# ---------- Определение стека ----------

def test_empty_project_has_no_stack(project):
    assert stack.detect_stack(project) == []
    assert stack.stack_summary(project) == "не определён"
    assert stack.detect_tags(project) == set()


def test_php_project_with_laravel(project):
    (project / "composer.json").write_text(
        json.dumps({"require": {"laravel/framework": "^11.0"}}), encoding="utf-8")

    assert stack.detect_stack(project) == ["PHP (Laravel)"]
    assert "php" in stack.detect_tags(project)


def test_typescript_project_with_next(project):
    (project / "package.json").write_text(
        json.dumps({"dependencies": {"next": "15.0.0", "react": "19.0.0"}}),
        encoding="utf-8")
    (project / "tsconfig.json").write_text("{}", encoding="utf-8")

    tags = stack.detect_tags(project)
    assert stack.detect_stack(project) == ["TypeScript (Next.js)"]
    assert {"ts", "js", "next"} <= tags


def test_python_project(project):
    (project / "requirements.txt").write_text("fastapi==0.115\n", encoding="utf-8")

    assert stack.detect_stack(project) == ["Python (FastAPI)"]


def test_django_by_manage_py(project):
    (project / "manage.py").write_text("", encoding="utf-8")
    (project / "requirements.txt").write_text("django\n", encoding="utf-8")

    assert stack.detect_stack(project) == ["Python (Django)"]


def test_android_kotlin_project(project):
    (project / "build.gradle.kts").write_text(
        'plugins { id("com.android.application") }', encoding="utf-8")
    (project / "AndroidManifest.xml").write_text("<manifest/>", encoding="utf-8")

    assert stack.detect_stack(project) == ["Android (Kotlin)"]


def test_swift_ios_project(project):
    (project / "Package.swift").write_text("// swift-tools-version:5.9",
                                           encoding="utf-8")

    assert stack.detect_stack(project) == ["iOS (Swift)"]


def test_other_markers(project):
    (project / "go.mod").write_text("module x\n", encoding="utf-8")
    (project / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    (project / "Gemfile").write_text("source 'x'\n", encoding="utf-8")
    (project / "index.html").write_text("<html></html>", encoding="utf-8")

    found = stack.detect_stack(project)

    assert {"Go", "Rust", "Ruby", "HTML/CSS"} <= set(found)


def test_stack_of_missing_dir_is_empty(tmp_path):
    assert stack.detect_stack(tmp_path / "нет") == []


# ---------- Разбор SKILL.md ----------

def test_parse_front_matter():
    meta, body = parse_front_matter(
        "---\n"
        "name: my-skill\n"
        "applies_to: [php, laravel]\n"
        "description: что-то важное: с двоеточием\n"
        "---\n"
        "Правила навыка\n"
    )

    assert meta["name"] == "my-skill"
    assert meta["applies_to"] == ["php", "laravel"]
    assert meta["description"] == "что-то важное: с двоеточием"
    assert body.strip() == "Правила навыка"


def test_parse_front_matter_without_block_returns_content():
    meta, body = parse_front_matter("# Просто текст\n")

    assert meta == {}
    assert body == "# Просто текст\n"


def test_skill_applies_to_rules():
    assert skill_applies_to({}, {"php"}) is True                     # без applies_to
    assert skill_applies_to({"applies_to": ["php"]}, {"php"}) is True
    assert skill_applies_to({"applies_to": ["php"]}, {"python"}) is False
    assert skill_applies_to({"applies_to": ["php"]}, set()) is True   # стек неизвестен
    assert skill_applies_to({"applies_to": "php laravel"}, {"laravel"}) is True


# ---------- Загрузка навыков ----------

def _make_skill(base, name, content):
    path = base / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(content, encoding="utf-8")


def test_load_skill_map_skips_dirs_without_skill_md(project):
    _make_skill(project / "skills", "good", "---\nname: good\n---\nтело")
    (project / "skills" / "empty").mkdir()
    (project / "skills" / "readme.txt").write_text("не навык", encoding="utf-8")

    assert set(load_skill_map(str(project / "skills"))) == {"good"}
    assert load_skill_map(str(project / "нет")) == {}


def test_load_skill_map_accepts_lowercase_filename(project):
    skill = project / "skills" / "lower"
    skill.mkdir(parents=True)
    (skill / "skill.md").write_text("тело", encoding="utf-8")

    assert load_skill_map(str(project / "skills")) == {"lower": "тело"}


def test_load_skills_for_stack_filters_by_tags(project):
    base = project / "skills"
    _make_skill(base, "php-conventions", "---\napplies_to: [php]\n---\nphp-правила")
    _make_skill(base, "code-quality", "---\nname: code-quality\n---\nобщие правила")

    for_php = load_skills_for_stack(str(base), {"php"})
    for_python = load_skills_for_stack(str(base), {"python"})

    assert set(for_php) == {"php-conventions", "code-quality"}
    assert set(for_python) == {"code-quality"}


def test_load_skills_for_stack_strips_front_matter(project):
    base = project / "skills"
    _make_skill(base, "skill", "---\nname: skill\n---\nтолько тело")

    loaded = load_skills_for_stack(str(base), {"php"})

    assert loaded["skill"] == "только тело"
    assert "name: skill" not in loaded["skill"]


def test_only_profile_list_ignores_applies_to(project):
    """Профиль грузит ровно свои навыки, независимо от стека проекта."""
    base = project / "skills"
    _make_skill(base, "php-conventions", "---\napplies_to: [php]\n---\nphp")
    _make_skill(base, "python-conventions", "---\napplies_to: [python]\n---\npython")

    loaded = load_skills_for_stack(str(base), {"python"}, only={"php-conventions"})

    assert set(loaded) == {"php-conventions"}
