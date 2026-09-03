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

## Браузер, STT и провайдеры ModelHub/Mafsolin/Router AI

Рабочий overlay профиля сохранён в
`runtime/afsol-provider-config.example.yaml`. Он использует нативный для
Afsol формат `custom_providers` и содержит:

- Camofox как явный browser backend (`browser.cloud_provider: camofox`) с
  включённым `managed_persistence`. Адрес Camofox задаётся только в
  `CAMOFOX_URL` в `.env`;
- Groq для голосовых сообщений (`stt.provider: groq`) с моделью
  `whisper-large-v3-turbo`, ключ `GROQ_API_KEY`;
- Router Hermes / Router AI для vision —
  `https://routerai.ru/api/v1`, модель `google/gemini-3.1-flash-lite`, ключ
  `ROUTER_HERMES_API_KEY`;
- Mafsolin Search для `web_search` — отдельный MCP-сервер `mcp_servers.search`,
  ключ `MAFSOLIN_SEARCH_API_KEY`; это не `web.search_backend` и не LLM-модель
  провайдера Mafsolin;
- Выбор web-search backend: overlay включает **оба** инструмента —
  нативный `web_search`/`web_extract` (toolset `web`, с keyless free-tier
  fallback при отсутствии платного ключа) и Mafsolin Search через MCP
  (toolset `mcp-search`). Модель видит два независимых инструмента поиска
  и не привязана намертво к одному backend'у. Чтобы закрепить только один,
  убери соответствующий toolset из overlay (см. комментарий в
  `runtime/afsol-provider-config.example.yaml`);
- `ModelHub` — `https://modelhub.my/v1`, ключ из `MODELHUB_API_KEY`,
  10 моделей, default `claude-sonnet-5`;
- `Mafsolin` — `https://api.mafsolin.space/v1`, ключ из
  `MAFSOLIN_SEARCH_API_KEY`, 9 моделей, default
  `antigravity/gemini-3.6-flash-high`.

У Router Hermes, ModelHub и Mafsolin намеренно оставлено
`discover_models: false`: списки моделей — явные allowlist, чтобы автоматический
каталог провайдера не изменил поведение после обновления Hermes. Все реальные
ключи остаются в `/home/afsol/.hermes/.env`; в Git хранятся только ссылки
`${...}`.

MCP-сервер поиска запускается из `/home/afsol/.hermes/mcp/search-mcp-server.py`
и передаёт в него `MAFSOLIN_SEARCH_API_KEY`. Если в профиле включён toolset
`mcp-search`, инструмент `web_search` будет доступен агенту через этот сервер.
В overlay этот toolset уже указан рядом с `hermes-cli`.

Прямая проверка MCP-вызова 2026-09-01: инструмент `web_search` найден, запрос
вернул `ok=true`, 3 результата; Mafsolin внутри выполнил failover
`linkup-search` → `tavily-search`.

При контрольной проверке 2026-09-01 оба endpoint-а вернули `200` на
авторизованный `/v1/models`. Из старого live-списка ModelHub исключены три ID,
которые API больше не возвращает: `deepseek-v4-flash`, `deepseek-v4-pro` и
`grok-4-5`. Модель Mafsolin
`antigravity/claude-sonnet-4-6` также исключена после трёх последовательных
проверок: endpoint её больше не возвращает. Доступные дополнительные модели
не добавлялись автоматически — это позволяет сначала проверить их отдельно и
затем осознанно расширить allowlist.

Для Camofox перед запуском проверьте доступность адреса из `CAMOFOX_URL` и
выполните `/browser status`: одна только запись `cloud_provider` не запускает
сам Camofox-сервис. На старом сервере текущий Camofox отвечает `200` на
`/health` и `/tabs`; для отдельного нового VPS его адрес должен быть локальным
для того VPS либо сетево доступным ему.

Для восстановления на новом профиле сначала сделайте копию конфига, затем
объедините только нужные верхнеуровневые ключи из overlay с локальным
`config.yaml`; не копируйте файл поверх полного профиля. После этого проверьте:

```bash
runuser -u afsol -- env HERMES_HOME=/home/afsol/.hermes \
  /home/afsol/hermes-agent/venv/bin/hermes config check
```

При обновлении upstream overlay не нужно переписывать: он хранится отдельным
файлом и должен проходить review вместе с изменениями списка моделей. Если
ключ ротируется, меняется только `.env`, а не Git-файл.

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
