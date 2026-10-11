---
name: swift-conventions
description: Правила для Swift-кода (платформы Apple)
applies_to: [swift, ios, macos, apple, xcode, spm]
---

# Swift: соглашения

Рекомендации опираются на Swift API Design Guidelines.

- Следуй API Design Guidelines: ясность в месте вызова важнее краткости; имена
  читаются как грамматические фразы на английском.
- Методы с побочным эффектом — глаголы (`sort()`), без эффекта — существительные
  (`sorted()`); мутирующие/немутирующие пары: `verb` / `-ed`/`-ing`.
- Булевы свойства и методы — утверждения (`isEmpty`, `isEnabled`).
- Именование: `UpperCamelCase` — типы, `lowerCamelCase` — свойства/функции/члены enum.
- Предпочитай `let` вместо `var`; value-типы (`struct`, `enum`) — по умолчанию.
- Optionals: избегай force unwrap (`!`) и `try!`; используй `guard let`/`if let`, `??`.
- Ошибки — через `throws`/`try/catch`; `try?` применяй осознанно, не глотай ошибку молча.
- Общую логику выноси в протоколы и `extension`; расширения группируй по назначению.
- Concurrency: `async/await`, `actor` для изолированного состояния, UI — `@MainActor`;
  проверяй `Task.isCancelled`.
- Публичный API документируй `///` (DocC); используй `os.Logger` вместо `print`.
- Синтаксис проверяется автолинтом (`swiftc -parse`); сборка/тесты: Xcode
  (`xcodebuild test -scheme ...`) или SwiftPM (`swift build`, `swift test`).
- Секреты — в Keychain, xcconfig или окружении, не в коде.
