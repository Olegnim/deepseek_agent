# Разработка

## Структура папки агента

```
<AGENT_HOME>/                 # папка агента — определяется автоматически из расположения agent.py
├── agent.py                  # точка входа
├── config.py                 # поиск конфигов, project_root, agent_home
├── agent.config.json         # настройки агента (шаблон для git, без секретов)
├── mcp_integration.py        # клиент MCP-серверов
├── skills_loader.py          # загрузка навыков
├── plugins_loader.py         # подключение плагинов (доп. инструменты из plugins/)
├── tools/                    # filesystem, search, digest, shell, linter, git, web, vscode, cache, snapshot, stack, loop_guard
├── skills/                   # встроенные навыки (навыки проекта подхватятся отдельно)
├── plugins/                  # (опционально) плагины: .py с функцией register(api)
├── .agent.config.json        # ЛОКАЛЬНЫЙ оверрайд и секреты (в git не попадает)
├── .vscode/tasks.json        # готовые задачи VS Code
├── vscode-extension/         # расширение-мост: агент открывает файлы прямо в VS Code
├── docs/                     # документация (настройки, интеграции, проблемы)
├── tests/                    # pytest
└── mcp_config.json           # MCP-серверы (пути — через ${project_root})
```

Пути и приоритет конфигов — в [`configuration.md`](configuration.md).

## Тесты

```powershell
python -m pip install -r "<AGENT_HOME>\requirements-dev.txt"   # pytest
cd "<AGENT_HOME>"
python -m pytest                      # все тесты, ~3 секунды
python -m pytest tests/test_config.py -v
```

Если `python -m pytest` пишет «No module named pytest» — pytest поставлен не в тот
интерпретатор: сверьте `python -c "import sys; print(sys.executable)"` с выводом
`python -m pip -V` (в `--doctor` есть блок **Пакеты Python** с пометкой о pytest).

Тесты не ходят в сеть, не обращаются к DeepSeek API и не требуют внешних утилит:
модель подменяется заглушками, страницы — фейковым «опенером», а временные проекты
создаются в `tmp_path`.

| Файл | Что покрывает |
|---|---|
| `tests/test_config.py` | приоритет корня проекта (`-p` > env > конфиг > cwd), слоистые конфиги, подстановки (в т.ч. `${project_root}`), лимиты, профили, пути к ресурсам, выбор Python-команды |
| `tests/test_filesystem.py` | `read_file`/`read_range` (границы и обрезка), `write_file`, `edit_file` (первое вхождение, `replace_all`, CRLF/LF), `grep`, схема проекта |
| `tests/test_search.py` | `search_code` (группировка, контекст, `fixed`, лимиты), `file_outline` (Python/PHP/JS), `read_symbol`, `diff_files`, `find_files`, `project_map` |
| `tests/test_digest.py` | выжимка из большого вывода: ошибки/начало/конец, сохранение полного текста в `.agent-cache/output`, лимит сохранённых файлов, фрагменты по ключевым словам |
| `tests/test_linter.py` | выбор правила по расширению, OK/ОШИБКА, пропуск без утилиты, подстановка интерпретатора, отсутствие `__pycache__` в проекте, добавление отчёта к правке |
| `tests/test_agent_core.py` | песочница `safe_path`, выполнение инструментов, снапшот+линт вокруг `write_file`, отказ пользователя, список инструментов для модели, системный промпт, команды REPL, токены, настройки API из конфига проекта |
| `tests/test_agent_loop.py` | цикл задачи: пары assistant→tool, ошибки инструментов и битый JSON аргументов, loop-guard, лимит шагов, сбой API, ретраи |
| `tests/test_loop_guard.py` | предупреждение, остановка, сброс счётчика при другом результате |
| `tests/test_plan_mode.py` | режимы планирования, блокировка правок, автопилот после `:plan approve`, прогресс в `PLAN.md` |
| `tests/test_stack_skills.py` | определение стека по маркерным файлам, front-matter `SKILL.md`, отбор навыков по `applies_to` и по профилю |
| `tests/test_plugins.py` | плагины: регистрация инструментов, `dangerous`, изоляция ошибок (битый плагин не роняет агента), запрет перекрывать встроенные инструменты |
| `tests/test_snapshot_cache.py` | снапшоты (путь, лимит `max_backups`), подсчёт и очистка `.agent-cache` |
| `tests/test_web.py` | SSRF-фильтр адресов, преобразование HTML, разбор выдачи DuckDuckGo (без сети) |
| `tests/test_mcp.py` | конфиг MCP, подстановки, схемы инструментов, префикс `сервер__инструмент`, ошибки вызова, roots/list |
| `tests/test_vscode.py` | дескриптор моста и битые данные, песочница путей, сообщения при закрытом редакторе |
| `tests/test_shell_git.py` | рабочая папка и код возврата shell, убийство команды по таймауту, git status/diff/log (включая русский текст в диффе) |
| `tests/test_api_features.py` | thinking/`reasoning_effort`, `max_tokens`, `top_p`, стриминг и склейка `tool_calls`, vision |

Прогон должен быть полностью зелёным: известные дефекты 0.1.0 (настройки `api.*`
при `-p`, `${project_root}` в конфиге, секция `tools.lint`, кодировка вывода git)
исправлены — `xfail`-маркеров в тестах больше нет.

## Плагины (доп. инструменты)

Плагин — обычный `.py`-файл в папке `plugins/` проекта (или агента): папки
задаются ключом `paths.plugins_dirs`, ищутся по цепочке «проект → папка агента»
и подключаются на старте (`plugins_loader.py`). Файлы, начинающиеся с `_`,
пропускаются.

```python
# plugins/hello.py
def register(api):
    def hello(**args):
        return f"Привет, {args.get('name') or 'мир'}!"

    api.add_tool(
        name="hello",
        description="Поздороваться с пользователем",
        parameters={"type": "object", "properties": {"name": {"type": "string"}}},
        func=hello,
    )
```

- Обработчик вызывается как `func(**args)`, результат приводится к строке и
  проходит тот же бюджет вывода (`tools.output`), что и у встроенных
  инструментов. Аргумент `path` проходит песочницу `safe_path`.
- `dangerous=True` — инструмент спрашивает подтверждение (как `write_file`) и
  блокируется в режиме планирования.
- Перекрыть встроенный инструмент или MCP-имя нельзя: такой инструмент
  пропускается с сообщением об ошибке.
- В `register(api)` доступны `api.project_root`, `api.settings`,
  `api.find_resource("schema.json")`.
- Ошибка в плагине (исключение, нет `register`, недопустимое имя инструмента) не
  роняет агента: она печатается при старте и видна в `--doctor`.

**Плагин — это код в процессе агента**, поэтому подключайте только доверенные
папки; ключ `paths.plugins_dirs` не должен указывать на чужие каталоги.
