---
name: csharp-conventions
description: Правила для C#-кода (.NET)
applies_to: [csharp, cs, dotnet, net, aspnetcore, unity]
---

# C#: соглашения

- Целевая версия и nullable-контекст — как в `*.csproj` (`<TargetFramework>`,
  `<Nullable>enable</Nullable>`); не меняй TFM «на глаз» и не отключай
  nullable-предупреждения без причины.
- Именование: `PascalCase` — типы, методы, свойства, события; `camelCase` —
  параметры и локальные переменные; `_camelCase` — приватные поля (если так
  принято в проекте); `I`-префикс у интерфейсов (`IRepository`).
- Один файл — один публичный тип (исключение — вложенные/мелкие DTO).
  Namespace — file-scoped (`namespace Shop.Api;`), совпадает с папками.
- Асинхронность: `async`/`await` без `.Result` и `.Wait()` (дедлок), суффикс
  `Async` у методов, `CancellationToken` последним параметром, `ConfigureAwait`
  — только в библиотеках.
- Исключения: свои типы наследуй от `Exception` (или `ApplicationException`
  проекта), не глуши `catch { }`, используй `when`-фильтры, не бросай
  исключения для управления потоком.
- Ресурсы — `using`/`await using`; `IDisposable`/`IAsyncDisposable` для своих типов.
- NULL и коллекции: по умолчанию `IReadOnlyList<T>`/`IEnumerable<T>` в
  параметрах, материализуй (`ToList()`) только когда нужно; `string?` вместо
  «магических» проверок.
- LINQ — читаемыми шагами, без побочных эффектов в `Select`; в горячих циклах
  предпочитай обычный `for`/`foreach`.
- Не оставляй отладочный код (`Console.WriteLine`, `Debug.WriteLine`) в правках —
  используй `ILogger<T>`/`Serilog` проекта.
- Строки: интерполяция `$"..."` для коротких, `StringBuilder` в циклах,
  `StringComparison.Ordinal` для сравнений без культуры.
- Секреты — из конфигурации (`IConfiguration`, user-secrets, переменные
  окружения), не в коде и не в репозитории.
