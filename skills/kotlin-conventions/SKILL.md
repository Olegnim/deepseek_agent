---
name: kotlin-conventions
description: Правила для Kotlin-кода (JVM/Android)
applies_to: [kotlin, jvm, android, ktor, coroutines, gradle]
---

# Kotlin: соглашения

Рекомендации опираются на официальные Coding conventions (kotlinlang.org) и
Kotlin style guide для Android.

- Именование: `PascalCase` — классы, `camelCase` — функции и свойства,
  `UPPER_SNAKE_CASE` — константы (`const val`).
- Предпочитай `val` вместо `var` и неизменяемые коллекции (`listOf`, `mapOf`);
  простые функции — с expression body (`fun f() = ...`), ставь trailing comma.
- Порядок в классе: свойства и `init`-блоки → вторичные конструкторы → методы →
  `companion object`; связанные объявления держи рядом.
- Имя файла = имя основного класса (или описывает содержимое); избегай
  бессмысленных имён вроде `Util`.
- Null-safety: избегай `!!`; используй `?.`, `?:`, `requireNotNull`, `check`.
- Для DTO и простых значений — `data class`; не мутируй разделяемое состояние.
- `when` вместо цепочек `if/else`; делай ветки исчерпывающими для `sealed`/`enum`.
- Scope-функции (`let`/`apply`/`also`/`run`/`with`) — по назначению, без глубокой вложенности.
- Корутины: используй `suspend` вместо блокирующих вызовов, не применяй `GlobalScope`;
  `Dispatchers.IO` — для ввода-вывода; не глотай `CancellationException`.
- Не оставляй `println` для отладки — используй logging (SLF4J, Timber) или `os_log`.
- Синтаксис проверяется автолинтом (`kotlinc`); сборка: Gradle (`./gradlew test`);
  версии зависимостей — в `libs.versions.toml`, если он есть в проекте.
  Форматирование — ktlint/`spotlessApply`.
