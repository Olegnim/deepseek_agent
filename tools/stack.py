"""Определение технологического стека проекта.

Нужно, чтобы агент был универсальным: вместо жёстко зашитых «PHP/Python» он
смотрит на маркерные файлы проекта (composer.json, package.json, pyproject.toml,
go.mod, ...) и понимает, с чем имеет дело. Стек попадает в системный промпт,
по нему же удобно подсказывать команды проверки и подбирать навыки.

Зависимостей нет — только стандартная библиотека.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Конфиги зависимостей, из которых вытаскиваем фреймворк.
_JS_FRAMEWORKS = (
    ("next", "Next.js"),
    ("nuxt", "Nuxt"),
    ("@angular/core", "Angular"),
    ("vue", "Vue"),
    ("svelte", "Svelte"),
    ("react", "React"),
    ("solid-js", "Solid"),
    ("express", "Express"),
    ("fastify", "Fastify"),
    ("nest", "NestJS"),
    ("vite", "Vite"),
)

_PHP_FRAMEWORKS = (
    ("laravel/framework", "Laravel"),
    ("symfony/framework-bundle", "Symfony"),
    ("yiisoft/yii2", "Yii2"),
    ("cakephp/cakephp", "CakePHP"),
)

_PY_FRAMEWORKS = (
    ("django", "Django"),
    ("flask", "Flask"),
    ("fastapi", "FastAPI"),
    ("aiohttp", "aiohttp"),
)


def _read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _js_deps(root: Path) -> list[str]:
    data = _read_json(root / "package.json")
    deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = data.get(key)
        if isinstance(value, dict):
            deps.update(value)
    return list(deps)


def _php_deps(root: Path) -> list[str]:
    data = _read_json(root / "composer.json")
    deps = {}
    for key in ("require", "require-dev"):
        value = data.get(key)
        if isinstance(value, dict):
            deps.update(value)
    return list(deps)


def _py_names(root: Path) -> list[str]:
    names: list[str] = []
    for name in ("requirements.txt", "requirements-dev.txt"):
        path = root / name
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                names += [line.split("==")[0].strip() for line in text.splitlines()]
            except OSError:
                pass
    for name in ("pyproject.toml", "setup.cfg", "setup.py"):
        path = root / name
        if path.is_file():
            try:
                names.append(path.read_text(encoding="utf-8", errors="ignore").lower())
            except OSError:
                pass
    return names


def _first_match(items: list[str], table: tuple) -> str | None:
    haystack = " ".join(items).lower()
    for needle, label in table:
        if needle in haystack:
            return label
    return None


def _has_any(root: Path, names: tuple[str, ...]) -> bool:
    return any((root / n).exists() for n in names)


def _file_contains(path: Path, needle: str) -> bool:
    """Есть ли подстрока в файле (регистр не важен). Отсутствующий файл — False."""
    try:
        return needle.lower() in path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


def _has_source(root: Path, suffix: str) -> bool:
    """Есть ли исходники с таким расширением в типовых папках проекта."""
    for sub in ("", "src", "app", "src/main", "Sources"):
        base = root / sub if sub else root
        if base.is_dir() and next(base.glob(f"*.{suffix}"), None) is not None:
            return True
    return False


def detect_stack(root: str | Path = ".") -> list[str]:
    """Возвращает список распознанных стеков проекта (может быть пустым)."""
    root = Path(root)
    if not root.is_dir():
        return []

    found: list[str] = []

    # --- PHP ---
    if _has_any(root, ("composer.json", "composer.lock", "artisan", "index.php")):
        framework = _first_match(_php_deps(root), _PHP_FRAMEWORKS)
        found.append(f"PHP ({framework})" if framework else "PHP")

    # --- JS / TS ---
    if (root / "package.json").is_file():
        deps = _js_deps(root)
        framework = _first_match(deps, _JS_FRAMEWORKS)
        label = "JS/TS"
        if (root / "tsconfig.json").is_file():
            label = "TypeScript"
        found.append(f"{label} ({framework})" if framework else f"{label} (Node)")

    # --- Python ---
    if _has_any(root, ("pyproject.toml", "requirements.txt", "setup.py", "manage.py")):
        framework = "Django" if (root / "manage.py").is_file() \
            else _first_match(_py_names(root), _PY_FRAMEWORKS)
        found.append(f"Python ({framework})" if framework else "Python")

    # --- Прочие популярные ---
    if _has_any(root, ("go.mod",)):
        found.append("Go")
    if _has_any(root, ("Cargo.toml",)):
        found.append("Rust")
    if _has_any(root, ("Gemfile",)):
        found.append("Ruby")

    # --- JVM: Java / Kotlin / Android ---
    jvm_marker = _has_any(root, (
        "pom.xml", "build.gradle", "build.gradle.kts",
        "settings.gradle", "settings.gradle.kts", "AndroidManifest.xml",
    ))
    if jvm_marker:
        is_android = (root / "AndroidManifest.xml").is_file() \
            or _file_contains(root / "build.gradle", "com.android") \
            or _file_contains(root / "build.gradle.kts", "com.android")
        is_kotlin = (root / "build.gradle.kts").is_file() or _has_source(root, "kt")
        if is_android:
            found.append("Android (Kotlin)" if is_kotlin else "Android (Java)")
        elif is_kotlin:
            found.append("Kotlin (JVM)")
        else:
            found.append("Java (JVM)")

    # --- Swift / iOS ---
    has_xcode = _has_any(root, ("Package.swift", "Podfile", "Cartfile")) \
        or next(root.glob("*.xcodeproj"), None) is not None \
        or next(root.glob("*.xcworkspace"), None) is not None
    if has_xcode:
        found.append("iOS (Swift)")
    elif _has_source(root, "swift"):
        found.append("Swift")

    # --- Статический фронтенд ---
    public_html = (root / "public").is_dir() and any((root / "public").glob("*.html"))
    if any(root.glob("*.html")) or public_html:
        found.append("HTML/CSS")

    return found


def stack_summary(root: str | Path = ".") -> str:
    """Стек одной строкой — для системного промпта и `:doctor`."""
    stack = detect_stack(root)
    return ", ".join(stack) if stack else "не определён"


def detect_tags(root: str | Path = ".") -> set[str]:
    """Теги стека для отбора навыков (applies_to в SKILL.md).

    Например, «PHP (Laravel)» → {"php", "laravel"}, «JS/TS (Next.js)» →
    {"js", "ts", "next", "js"} — слова в нижнем регистре.
    """
    tags: set[str] = set()
    for label in detect_stack(root):
        for token in re.split(r"[^a-z0-9]+", label.lower()):
            if token:
                tags.add(token)
    if "typescript" in tags:
        tags.update({"ts", "js"})
    if "javascript" in tags:
        tags.update({"js", "ts"})
    return tags
