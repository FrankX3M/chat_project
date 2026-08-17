# Анонимный чат

Рабочая версия по мотивам `CLAUDE.md` и `project-structure.md`: анонимная авторизация
по `device_id`, настройки/фильтры, матчинг через Redis-очередь, WebSocket-чат
(`message` / `typing` / `leave`), реконнект с grace-period — и production-фронтенд
(экран настроек → поиск → чат) за nginx на 80 порту. Модерация, жалобы, полноценная
KYC-верификация 18+ и админка — за рамками текущей версии, но заложены точки
расширения (заглушка `content_filter`, самодекларация возраста вместо KYC), чтобы
не переписывать архитектуру, когда их будете добавлять.

## Стек

Python 3.11+, FastAPI (async), SQLAlchemy 2.0 (async) + Alembic, PostgreSQL, Redis,
Pydantic v2, JWT (python-jose), nginx (reverse proxy + статика), pytest +
pytest-asyncio + fakeredis, Docker Compose.

## Структура

```
server/app/
  api/v1/          auth, settings, search, rooms, stats — REST
  ws/               router.py (WS endpoint), connection_manager, event_handlers
                     (здесь же фоновый matchmaking_loop)
  matchmaking/      queue.py (Redis), matcher.py (алгоритм), filters.py (совместимость)
  chat/             room_manager.py, message_service.py
  moderation/       rate_limiter.py (работает), content_filter.py (заглушка-пайплайн)
  models/, schemas/, db/, core/
server/alembic/     миграции — начальная ревизия (init schema) уже в репозитории
server/tests/       test_matchmaking.py, test_ws_flow.py, test_settings.py, test_reports.py (skip)
clients/web/        production-фронтенд (index.html, без сборки)
infra/              docker-compose.yml (postgres + redis + server + nginx), nginx/nginx.conf
shared/ws-events.md  человекочитаемое зеркало WS-контракта из schemas/ws_events.py
test-client.html    отладочный клиент с сырым WS-логом (для разработчиков, не для конечных пользователей)
```

## Что реализовано

- `POST /api/v1/auth/anonymous`, `POST /api/v1/auth/refresh` — анонимная авторизация по `device_id`, JWT access+refresh.
- `GET/PUT /api/v1/settings` — собственный пол/возраст, тема общения, фильтры собеседника (пол/возраст), цветовая тема.
  - `is_18_plus_mode` (тема "Флирт 18+") требует самодекларации: `self_declared_adult=true` + `age>=18` в том же запросе засчитывают `is_age_verified=true`. Без этого — `422`. Это самодекларация (`method=self_declaration` из `project-structure.md` 3.8), не полноценная KYC-проверка документов.
- `GET /api/v1/stats/online` — сколько сокетов сейчас подключено (для счётчика "Находятся в чате: N").
- `POST /api/v1/search/{start,cancel}`, `GET /api/v1/search/status` — постановка в очередь (Redis) с учётом темы/пола/возраста, rate limit на `/search/start`.
- `GET /api/v1/rooms/{id}/messages`, `POST /api/v1/rooms/{id}/leave`.
- `WS /ws/connect?token=...` — `join_queue`, `cancel_queue`, `message`, `typing`, `leave` → `matched`, `message`, `typing`, `partner_left`, `queue_position`, `error`.
- Фоновый цикл матчинга (`matchmaking_loop`) ищет совместимые пары в очереди (тема + пол + возрастные диапазоны) и создаёт `chat_rooms`.
- Реконнект: при разрыве сокета — grace-period `ROOM_RECONNECT_GRACE_SECONDS` (по умолчанию 20с), затем `end_reason=timeout`.
- Приватность: сырой IP никогда не сохраняется, только `ip_hash` (SHA-256 + соль).
- **Production-фронтенд** (`clients/web/index.html`): экран настроек (тема/пол/возраст/цветовая схема, точь-в-точь как в референсе) → поиск с лоадером → чат (сообщения, "печатает…", "Далее"/"Стоп"). Без технических полей — адрес API берётся из текущего origin страницы.
- **nginx** отдаёт фронтенд на 80 порту и проксирует `/api`, `/ws`, `/health`, `/docs` на бэкенд — сайт открывается по чистому IP/домену без порта.

## Что осознанно не реализовано

Жалобы/баны, полноценная KYC-верификация (сейчас только самодекларация возраста),
админка, реальные правила `content_filter`, `tasks/cleanup.py` (TTL хранения
сообщений), масштабирование WS на несколько инстансов через Redis Pub/Sub,
шардирование очереди по теме. Для каждого — уже есть место в структуре (см.
комментарии в коде), чтобы не ломать архитектуру при добавлении.

## Запуск через Docker Compose (рекомендуется)

Поднимает разом postgres + redis + backend + nginx; сайт открывается на 80 порту
хоста без указания порта в адресе:

```bash
cd server && cp .env.example .env && cd ..
cd infra
docker compose up --build -d
docker compose ps
```

Открыть `http://<IP-машины>/` — например `http://192.168.0.233/`. Свагger по-прежнему
доступен на `http://<IP>/docs` (проксируется тем же nginx).

Если контейнеры уже были подняты раньше без nginx — пересоздайте их:

```bash
docker compose down
docker compose up --build -d
```

Обновить только код после правок (без потери данных в Postgres):

```bash
docker compose up --build -d server nginx
```

### Если `alembic upgrade head` падает с "Can't locate revision ..."

Значит в volume `postgres_data` уже записана метка ревизии, которой нет в текущем
коде — обычно это следы более раннего запуска с другим (не сохранённым в архиве)
набором миграций. Раз это тестовые данные — проще всего снести volume и накатить
чистую схему заново:

```bash
docker compose down -v
docker compose up --build -d
```

Если данные в Postgres терять нельзя — вместо этого зайти в контейнер и вручную
сбросить таблицу версии, дальше `alembic upgrade head` применит актуальную схему
с нуля (это ок только если реальных таблиц ещё тоже нет — иначе будет конфликт):

```bash
docker compose exec postgres psql -U anon_chat -d anon_chat -c "DROP TABLE IF EXISTS alembic_version;"
docker compose up --build -d server
```

## Готовность к переезду на VPS + домен

Фронтенд (`clients/web/index.html`) обращается к API и WebSocket только по
относительным путям (`window.location.origin`), поэтому сам файл менять не нужно.
При переезде:

1. Прописать домен в `infra/nginx/nginx.conf` (`server_name your-domain.com`).
2. Добавить TLS: `listen 443 ssl;` + сертификаты (например, certbot/Let's Encrypt),
   в `docker-compose.yml` — открыть `443:443` (закомментированная строка уже там).
3. Сузить CORS в `server/app/main.py` (`allow_origins=["*"]` → конкретный домен).
4. Задать постоянные `JWT_SECRET`/`IP_HASH_SALT` в `.env` (см. "Секреты" ниже) —
   без этого приложение работает безопасно, но каждый рестарт разлогинивает всех.

## Секреты (JWT_SECRET / IP_HASH_SALT)

Раньше оба значения по умолчанию были захардкожены как `change-me-in-production`
прямо в коде — если их не поменять руками, любой, кто прочитал исходники или
README, мог подделать JWT-токен любого пользователя (нашли security-сканом,
CWE-798, CVSS 9.1). Исправлено:

- Если `JWT_SECRET`/`IP_HASH_SALT` не заданы в `.env` — при старте процесса
  генерируется случайный секрет (`secrets.token_hex(32)`). Безопасно из коробки,
  но рестарт сервера инвалидирует все текущие JWT — пользователи просто получат
  новую анонимную сессию, для этого продукта не критично.
- Если кто-то явно впишет в `.env` буквально `change-me-in-production` —
  приложение откажется стартовать с понятной ошибкой, а не тихо запустится
  с известным всем секретом.
- Для стабильных сессий между рестартами (рекомендуется на VPS/проде) — задать
  реальные значения один раз:
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"   # для JWT_SECRET
  python3 -c "import secrets; print(secrets.token_hex(32))"   # для IP_HASH_SALT — отдельным вызовом, не то же значение
  ```
  и вписать в `.env` (`JWT_SECRET=...`, `IP_HASH_SALT=...`), затем перезапустить
  контейнер `server`.

## Локальный запуск без Docker (для разработки бэкенда)

```bash
cd server
cp .env.example .env
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# postgres + redis (или через docker compose -f ../infra/docker-compose.yml up -d postgres redis)
alembic upgrade head   # миграция уже в репозитории (alembic/versions/), генерировать заново не нужно

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

В этом режиме фронтенд nginx не поднят — открывайте `clients/web/index.html`
напрямую в браузере (двойным кликом): страница обратится к `http://<хост>:8000`,
только если открыта с того же origin. Для локальной разработки удобнее раздать её
через любой статический сервер на том же порту, что и API, либо просто
использовать полный Docker Compose запуск выше.

## Тестовый веб-клиент для отладки (test-client.html)

Для отладки на уровне сырых WS-событий (не для конечных пользователей) в корне
репозитория остался `test-client.html` — с полями "Адрес API", `device_id` и логом
всех исходящих/входящих событий. Полезен, когда нужно быстро проверить, что именно
летит по сокету, без прицела на красивый UI. Обычным пользователям показывать не
нужно — для них `clients/web/index.html` за nginx.

## Тесты

```bash
cd server
pytest -v
```

19 тестов проходят без поднятия реального Postgres/Redis (SQLite in-memory +
fakeredis, реальный ASGI-стек FastAPI для `/settings` и `/stats/online`), 1 skip
(жалобы — вне текущей версии).

## Следующие шаги (по CLAUDE.md)

1. `moderation/content_filter.py` — реальные правила и/или внешний сервис.
2. `reports`, `bans`, `admin` — модели уже описаны в `project-structure.md`, эндпоинты не реализованы.
3. Полноценная KYC-верификация возраста (сейчас — только самодекларация).
4. `tasks/cleanup.py` — периодическая очистка старых сообщений (TTL).
5. Redis Pub/Sub для `connection_manager` при переходе на несколько инстансов сервера.
6. TLS/домен для nginx (см. "Готовность к переезду на VPS" выше).
