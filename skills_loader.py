"""Загрузка навыков (skills) из папок с SKILL.md.

Формат: каждая подпапка = один навык с файлом SKILL.md.

Порядок поиска задаётся в config.py (paths.skills_dir) — обычно:
1. <PROJECT_ROOT>/skills/   — навыки проекта
2. <AGENT_HOME>/skills/     — навыки самого агента

Обе папки объединяются: навыки проекта имеют приоритет по имени.
"""

import os
import re

_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
_LIST_SPLIT_RE = re.compile(r"[,\s]+")


def _parse_scalar(value: str):
    """Разбирает значение из front-matter: список [a, b] или строка."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        items = [v.strip().strip("'\"") for v in value[1:-1].split(",")]
        return [v for v in items if v]
    return value.strip("'\"")


def parse_front_matter(content: str) -> tuple[dict, str]:
    """Разделяет SKILL.md на метаданные и текст.

    Метаданные — простой YAML-подобный блок в начале файла:

        ---
        name: php-web
        description: Правила для веб-проектов на PHP
        applies_to: [php, laravel, symfony]
        ---

    Возвращает (meta, body). Без блока — ({}, content).
    """
    match = _FRONT_MATTER_RE.match(content)
    if not match:
        return {}, content

    meta: dict = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = _parse_scalar(value)

    return meta, content[match.end():]


def skill_applies_to(meta: dict, tags: set[str] | None) -> bool:
    """Подходит ли навык стеку проекта.

    Навык без `applies_to` грузится всегда. Навык с `applies_to` — только если
    пересекается с тегами стека. Если стек не определён (tags пуст) — грузим
    всё (fail-open), иначе агент остался бы без правил в незнакомом проекте.
    """
    raw = meta.get("applies_to")
    if not raw:
        return True
    if not tags:
        return True

    if isinstance(raw, str):
        wanted = [t for t in _LIST_SPLIT_RE.split(raw.lower()) if t]
    else:
        wanted = [str(t).strip().lower() for t in raw if str(t).strip()]
    return any(tag in tags for tag in wanted)


def _find_skill_md(skill_dir: str) -> str | None:
    """Ищет SKILL.md, учитывая регистр имени файла на разных ОС."""
    primary = os.path.join(skill_dir, "SKILL.md")
    if os.path.isfile(primary):
        return primary
    for alt in ("skill.md", "Skill.md", "SKILL.md.txt"):
        alt_path = os.path.join(skill_dir, alt)
        if os.path.isfile(alt_path):
            return alt_path
    return None


def load_skill_map(base: str) -> dict[str, str]:
    """Возвращает {имя_навыка: содержимое SKILL.md} для одной папки."""
    if not base or not os.path.isdir(base):
        return {}

    skills: dict[str, str] = {}
    for entry in sorted(os.listdir(base)):
        skill_dir = os.path.join(base, entry)
        if not os.path.isdir(skill_dir):
            continue

        skill_md = _find_skill_md(skill_dir)
        if not skill_md:
            continue

        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except OSError:
            continue

        if content:
            skills[entry] = content

    return skills


def load_skills(base: str) -> str:
    """Собирает содержимое всех SKILL.md одной папки в текстовый блок."""
    blocks = [
        f"### Skill: {name}\n{content}"
        for name, content in load_skill_map(base).items()
    ]
    return "\n\n".join(blocks)


def load_skills_for_stack(
    base: str,
    tags: set[str] | None = None,
    only: set[str] | None = None,
) -> dict[str, str]:
    """Навыки из папки, подходящие стеку проекта (без front-matter в тексте).

    tags — теги стека (config/tools.stack.detect_tags). Навыки без `applies_to`
    попадают всегда; с `applies_to` — только при совпадении темы.

    only — явный список имён навыков (профиль агента): если задан, грузятся
    ровно эти навыки, а `applies_to` не учитывается.
    """
    result: dict[str, str] = {}
    for name, content in load_skill_map(base).items():
        meta, body = parse_front_matter(content)
        if only is not None:
            if name not in only:
                continue
        elif not skill_applies_to(meta, tags):
            continue
        result[name] = body.strip() or content.strip()
    return result
