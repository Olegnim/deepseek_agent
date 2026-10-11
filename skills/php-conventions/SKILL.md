---
name: php-conventions
description: Правила для PHP-кода в этом проекте
---

- Используй `declare(strict_types=1);` в каждом файле.
- Классы — в `App\` namespace, PSR-4 автозагрузка.
- После правки PHP-файла запускай `php -l <file>` для проверки синтаксиса.
- Избегай `var_dump`, `print_r` в коммитах.