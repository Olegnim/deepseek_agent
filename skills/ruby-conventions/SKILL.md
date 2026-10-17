---
name: ruby-conventions
description: Правила для Ruby и Rails
applies_to: [ruby, rails, gem, bundler]
---

# Ruby / Rails: соглашения

- Синтаксис одного файла — `ruby -c file.rb` (это делает автолинт), тесты —
  `bundle exec rspec` (или `bundle exec rails test`), стиль — `bundle exec rubocop`.
  После правок гемфайла — `bundle install`.
- Стиль: 2 пробела, `snake_case` — методы/переменные, `CamelCase` — классы и
  модули, `SCREAMING_SNAKE_CASE` — константы; предикаты — с `?`, опасные
  (меняют объект) — с `!`, но `!` не заменяет исключения.
- Не «магические» хеши: `Struct`/`Data`/keyword-аргументы вместо
  `options = {}`; `attr_reader` вместо ручных геттеров.
- Исключения: свои классы от `StandardError`, не `rescue Exception`, не глуши
  `rescue nil`; в Rails — `rescue_from` в контроллере.
- Rails: логика — в моделях/сервисах (`app/services`), контроллеры тонкие;
  сильные параметры (`params.require(...).permit(...)`); N+1 — `includes`/
  `preload`; фоновые задачи — ActiveJob, а не «в контроллере».
- Миграции: не правь применённые, добавляй новую; внешние ключи и индексы — сразу.
- Безопасность: `find_by` вместо `where(...).first`, никакого `eval`, SQL —
  через placeholders (`where("name = ?", name)`), `html_safe` — только с
  проверенным содержимым.
- Тесты: RSpec — `describe`/`context`/`it`, фабрики (`FactoryBot`), без `sleep`
  в тестах.
- Секреты — `Rails.application.credentials`/переменные окружения, не в коде;
  логи — `Rails.logger`, не `puts` в правках.
