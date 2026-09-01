# Hermes Afsol: downstream workflow

Этот репозиторий хранит современную downstream-ветку Hermes для инстанса
Afsol. Официальная репа подключена как `upstream`, приватная GitHub-репа — как
`origin`.

## Границы данных

- В Git находятся код, тесты, updater и пользовательские модули.
- Профиль `/home/afsol/.hermes`, `config.yaml`, `.env`, `auth.json`, память,
  логи и токены находятся вне Git.
- Перед deployment резервируются профиль и рабочая конфигурация.
- Updater не меняет профиль, секреты или работающий systemd-сервис.

## Сохранённые Afsol-особенности

В downstream перенесены лимиты провайдеров, Obsidian Telegram Bridge,
idempotent Telegram publishing, OpenViking session-search fallback и проверки
ошибок. Для cron сохранена выдача с префиксом `⏰`. Чтобы старое поведение
непривязанных задач продолжало следовать активной глобальной модели, в профиле
Afsol перед запуском этой ветки нужно явно оставить:

```yaml
cron:
  model_drift_guard: false
```

Если параметр не задан, актуальный upstream по умолчанию использует защиту от
непреднамеренной смены платного provider/model и останавливает drifted-задачу.

Для Telegram Business → Obsidian используются те же изолированные секреты и
пути профиля. В `config.yaml` включение выглядит так:

```yaml
platforms:
  telegram:
    extra:
      business_memory_enabled: true
      business_owner_ids: ["<owner_id>"]
      business_auto_reply_enabled: false
```

Путь к vault и SQLite-буферу задаются только в окружении сервиса (или в его
локальном `.env`), например `OBSIDIAN_VAULT_PATH` и
`OBSIDIAN_BRIDGE_DB`. Автоответ Business выключен по умолчанию; если он нужен,
включайте его вместе с явным `business_auto_reply_user_ids`. Обработчик
пишет только текстовые Business-сообщения, помечает удаления и передаёт
`business_connection_id` в Telegram API, чтобы ответы не ушли из нужного
Business-чата. Обработать накопившиеся факты в Obsidian можно так:

```bash
python -m obsidian_telegram_bridge process --no-llm
```

Команду запускайте под владельцем профиля и указывайте конкретный vault; не
кладите токены в Git.

## Обновление upstream

Запускать из чистой ветки `main`:

```bash
python scripts/update_upstream.py --ref v2026.8.31 --dry-run
python scripts/update_upstream.py --ref v2026.8.31 --branch migration/afsol-upstream-2026.8.31
pytest -q
runuser -u afsol -- env HERMES_HOME=/home/afsol/.hermes /home/afsol/hermes-agent/venv/bin/hermes config check
```

Updater проверяет remote `upstream`, чистое дерево и ветку `main`, разрешает
tag в immutable commit и создаёт отдельную review-ветку. При конфликте он
ничего не выбирает автоматически. После разрешения нужны тесты,
`hermes config check`, сборка/проверка deployment и сохранение предыдущей
версии для отката. Для обычного обновления порядок такой: `git fetch --prune
upstream`, запуск updater из чистой `main`, проверка созданной ветки, затем
отдельный review/merge в `main`; production-профиль и systemd переключаются
после этого отдельной операцией.

## Текущий migration snapshot

Ветка `migration/afsol-upstream-2026.8.31` начинается с актуального
`upstream/main` (`18a76be124d7c16ed98b629a358b23fef76a7f46`) и содержит
перенесённые Afsol-модули. Это кандидат для review и отдельной сборки;
production на него автоматически не переключается.
