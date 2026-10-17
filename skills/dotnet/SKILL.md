---
name: dotnet
description: Правила для .NET-проектов (ASP.NET Core, EF Core, xUnit)
applies_to: [dotnet, net, aspnetcore, csharp, cs, efcore]
---

# .NET: проект, сборка, тесты

- Сборка и проверка: `dotnet build` (или `dotnet build <solution>.sln`),
  тесты — `dotnet test`; форматирование — `dotnet format`. Полный `dotnet test`
  прогоняй после правок логики, точечную проверку синтаксиса делай сборкой
  проекта, а не файла.
- Структура решения: `src/<Project>/`, `tests/<Project>.Tests/`, общие настройки
  в `Directory.Build.props`, версии пакетов — централизованно
  (`Directory.Packages.props`), если так принято в проекте.
- `*.csproj`: не правь руками сгенерированные `obj/`, `bin/`; зависимости
  добавляй точечно (`<PackageReference Include="..." Version="..." />`),
  версии не дублируй в разных проектах.
- ASP.NET Core: регистрация сервисов в `Program.cs` (`builder.Services`),
  конфигурация через `appsettings.json` + `appsettings.{Environment}.json`,
  секреты — user-secrets или переменные окружения. Контроллеры тонкие, логика —
  в сервисах; валидация — через атрибуты/`FluentValidation`; ошибки — `ProblemDetails`.
- EF Core: миграции (`dotnet ef migrations add <Name>`), не правь уже
  применённые миграции; запросы — `AsNoTracking()` для чтения, `Include` против
  N+1, `CancellationToken` в асинхронных вызовах.
- Тесты: xUnit/NUnit по проекту, `<Method>_<Scenario>_<Expected>` в именах,
  подмена зависимостей — через интерфейсы (`Moq`/`NSubstitute`), интеграционные —
  `WebApplicationFactory`.
- Логи — структурированные (`ILogger` с параметрами-плейсхолдерами), не
  склеивай строки вручную.
- Кроссплатформенность: пути — `Path.Combine`/`Path.GetTempPath`, файлы —
  `File.ReadAllTextAsync` с явной `Encoding`; не полагайся на регистр имён файлов.

> Автолинт агента для `.cs` не настроен (дешёвой проверки «только синтаксис» у
> C# нет): после правок запускай `dotnet build` через `run_shell`.
