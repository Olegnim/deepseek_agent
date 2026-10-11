---
name: kotlin-conventions
description: Правила для Kotlin-кода (JVM/Android)
applies_to: [kotlin, jvm, android, ktor, coroutines, gradle]
---

# Kotlin: соглашения

- Именование: `PascalCase` — классы, `camelCase` — функции и свойства,
  `UPPER_SNAKE_CASE` — константы (`const val`).
- Предпочитай `val` вместо `var` и неизменяемые коллекции (`listOf`, `mapOf`).
- Null-safety: избегай `!!`; используй `?.`, `?:`, `requireNotNull`, `check`.
- Для DTO и простых значений — `data class`; не мутируй разделяемое состояние.
- `when` вместо цепочек `if/else`; делай ветки исчерпывающими для `sealed`/`enum`.
- Функции делай небольшими, у публичных — явный возвращаемый тип.
- Scope-функции (`let`/`apply`/`also`/`run`/`with`) — по назначению, без глубокой вложенности.
- Корутины: используй `suspend` вместо блокирующих вызовов, не применяй `GlobalScope`;
  `Dispatchers.IO` — для ввода-вывода; не глотай `CancellationException`.
- Не оставляй `println` для отладки — используй logging (SLF4J, Timber).
- Сборка: Gradle (`./gradlew test`); версии зависимостей — в `libs.versions.toml`,
  если он есть в проекте.
