"""Загрузка навыков (skills) из папок с SKILL.md.

Формат: каждая подпапка = один навык с файлом SKILL.md.

Порядок поиска задаётся в config.py (paths.skills_dir) — обычно:
1. <PROJECT_ROOT>/skills/   — навыки проекта
2. <AGENT_HOME>/skills/     — навыки самого агента

Обе папки объединяются: навыки проекта имеют приоритет по имени.
"""

import os


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
