---
name: devops
description: Правила для контейнеров, Kubernetes и CI
applies_to: [devops, docker, kubernetes, k8s, helm, terraform, ci]
---

# DevOps: контейнеры, K8s, CI

- Docker: многоступенчатая сборка (`builder` → `runtime`), базовый образ
  фиксируй тегом/дайджестом, `.dockerignore` обязателен, `USER` не-root,
  `ENV`/`ARG` для конфигурации, а не хардкод путей.
- Секреты в образы не попадают: ни в `ENV`, ни в `COPY . .` — только
  build-секреты, переменные окружения или secret-объекты кластера.
- `HEALTHCHECK` и явный `ENTRYPOINT`/`CMD` (exec-форма `["app", "--flag"]`,
  чтобы сигналы доходили до процесса).
- Compose: версии образов фиксируй, `depends_on`+healthcheck, именованные
  volume вместо bind-mount в продакшене, `restart: unless-stopped`.
- Kubernetes: манифесты в `k8s/` (или Helm-чарт), `resources.requests/limits`
  обязательны, `liveness`/`readiness` probes, `securityContext` (non-root,
  readOnlyRootFilesystem по возможности), конфигурация — `ConfigMap`/`Secret`,
  не «в образе». Не правь руками то, чем управляет Helm/Kustomize.
- CI (GitHub Actions и аналоги): пины версий действий (`@v4`), `permissions:`
  минимальные, кэш зависимостей, матрица версий там, где важна совместимость,
  секреты — только через хранилище секретов, никаких `echo $TOKEN`.
- Инфраструктура как код (Terraform): `terraform fmt`/`validate`/`plan` перед
  `apply`, состояние — в удалённом backend, не в репозитории; ресурсы —
  с `for_each`, без копипасты.
- Проверяй перед правкой: `docker build`/`docker compose config`,
  `kubectl apply --dry-run=server`, `actionlint`/`yamllint` для CI-файлов —
  но не запускай `apply`/`deploy` без явного подтверждения пользователя.
- Логи и метрики: структурированный вывод в stdout/stderr, конфигурация через
  окружение, health-эндпоинт у сервиса.
