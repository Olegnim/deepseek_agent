---
name: python-conventions
description: Правила для Python-кода в этом проекте
applies_to: [python, py, django, flask, fastapi, aiohttp]
---

# Python: соглашения

- PEP 8: отступы 4 пробела, строки до ~100 символов, `snake_case` для функций
  и переменных, `PascalCase` для классов, `UPPER_CASE` для констант.
- Типизируй публичные функции (`def f(x: int) -> str:`), при необходимости
  используй `from __future__ import annotations`.
- Импорты: сначала stdlib, затем сторонние, затем локальные; абсолютные.
- Не оставляй `print()` для отладки — используй `logging`.
- Исключения: лови конкретные типы, не глуши их `except: pass`.
- Файлы и ресурсы — через `with open(...) as f:`.
- Не собирай SQL и shell-команды склейкой строк (f-строки в `cursor.execute`,
  `shell=True`) — используй параметры и списки аргументов.
- Синтаксис проверяется автолинтом (`python -m py_compile`); тесты —
  `python -m pytest`, если в проекте есть `pytest`.
- Форматирование и линт — `ruff` (или black + flake8), типы — `mypy`/`pyright`.
- Публичный API документируй docstring (PEP 257).
- Секреты — из окружения (`os.environ`), не в коде и не в репозитории.
