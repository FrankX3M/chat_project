# Нагрузочное тестирование Anon Chat API

`load_test.py` — эмулятор пользователей (HTTP + WebSocket) с анализом метрик
в реальном времени (RPS, error rate, p50/p95/p99 latency) и алертами при
деградации. Общая документация по параметрам — см. комментарии в самом файле
(`python3 load_test.py --help`) и `scenario.example.json` для общего формата.

> ⚠️ Гоняйте на проде только с ведома команды и в согласованное окно —
> сценарии ниже создают реальную нагрузку на матчмейкинг и БД.

## Установка

```bash
cd scripts/load-test
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt --break-system-packages
```

## Локально (через docker-compose)

```bash
# из корня репозитория
docker compose -f infra/docker-compose.yml up -d

cd scripts/load-test
python3 load_test.py --protocol http --host 127.0.0.1 --port 8000 \
    --scenario scenario.anon-chat.json \
    --users 50 --ramp-up 15 --duration 60
```

`scenario.anon-chat.json` — сценарий под этот проект: анонимный логин
(`POST /api/v1/auth/anonymous`) → постановка в очередь (`POST /api/v1/search/start`)
→ периодический `GET /health`. `search/start` защищён рейт-лимитом
(`search_start_rate_limit` / `search_start_rate_window_seconds` в конфиге) —
при большом числе пользователей ожидаемо увидите часть `429` в отчёте, это
не баг скрипта, а проверка того, что рейт-лимит действительно работает под
нагрузкой.

## WebSocket (матчмейкинг + чат)

WS требует токен из REST-логина — используйте `--ws-auth-url`, скрипт сам
залогинит каждого виртуального пользователя и подставит токен в путь:

```bash
python3 load_test.py --protocol ws --host 127.0.0.1 --port 8000 \
    --ws-auth-url /api/v1/auth/anonymous \
    --ws-auth-body '{{"device_id": "loadtest-{id}"}}' \
    --ws-auth-token-path access_token \
    --ws-path "/ws/connect?token={token}" \
    --ws-message '{{"event":"join_queue","payload":{{}}}}' \
    --users 100 --ramp-up 20 --duration 120 --ws-wait-reply
```

Это шлёт событие `join_queue` (см. `shared/ws-events.md`) сразу после
подключения и ждёт ответ (`queue_position`/`matched`/...) как round-trip.
Для более сложных сценариев (join_queue → дождаться matched → message →
leave) на данный момент проще написать отдельный WS-клиент поверх
`websockets`, взяв `ws_virtual_user` в `load_test.py` за основу — сценарии
с ветвлением по входящим событиям пока не поддержаны декларативно.

## Прод

```bash
python3 load_test.py --protocol http --host <PROD_IP> --port 443 --tls \
    --scenario scenario.anon-chat.json \
    --users 500 --ramp-up 60 --duration 300 \
    --error-rate-threshold 2 --p95-threshold-ms 500 \
    --out-dir report-$(date +%Y%m%d-%H%M)
```

Пороги (`--error-rate-threshold`, `--p95-threshold-ms`) стоит сначала
откалибровать небольшим прогоном (20-30 пользователей) в спокойное время,
чтобы не ловить ложные алерты на нормальной латентности прод-окружения.

Итоговые файлы (`summary.json`, `raw_records.csv`, `load_test_report.png`)
сохраняются в `--out-dir` — добавьте эту папку в `.gitignore`, если не
хотите коммитить отчёты прогонов.
